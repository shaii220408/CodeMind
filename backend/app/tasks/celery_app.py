from celery import Celery
from app.core.config import settings

celery = Celery("coderag", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.task_track_started = True
celery.conf.broker_connection_retry_on_startup = True


@celery.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=2)
def index_project(self, project_id: str, zip_path: str, generation: int | None = None):
    import os
    import tempfile

    from app.db.session import SessionLocal
    from app.services.ingestion import index_repository, safe_extract

    db = SessionLocal()
    succeeded = False
    try:
        with tempfile.TemporaryDirectory() as root:
            safe_extract(
                zip_path,
                root,
                settings.max_upload_mb * 1024 * 1024,
                settings.max_archive_files,
            )
            result = index_repository(db, project_id, root, generation)
        if result == "SKIPPED_STALE":
            succeeded = True
            return {"status": result}
        succeeded = True
        return {"status": "COMPLETED"}
    finally:
        db.close()
        if succeeded or self.request.retries >= self.max_retries:
            try:
                os.unlink(zip_path)
            except FileNotFoundError:
                pass
            try:
                os.rmdir(os.path.dirname(zip_path))
            except OSError:
                pass


@celery.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=2)
def sync_github_project(self, project_id: str, branch: str | None, generation: int):
    import tempfile

    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.models import Project
    from app.services.github import download_public_snapshot
    from app.services.ingestion import index_repository

    db = SessionLocal()
    repository_url = None
    try:
        project = db.scalar(select(Project).where(Project.id == project_id))
        if project is None or project.index_generation != generation:
            return {"status": "SKIPPED_STALE"}
        repository_url = project.repository_url
        if not repository_url:
            raise ValueError("Project has no GitHub repository URL")

        with tempfile.TemporaryDirectory(prefix="codemind-github-") as root:
            metadata = download_public_snapshot(
                repository_url,
                branch,
                root,
                settings.max_archive_files,
            )
            result = index_repository(db, project_id, root, generation, repository_metadata=metadata)
        if result == "SKIPPED_STALE":
            return {"status": result}
        return {"status": "COMPLETED", "commit_sha": metadata["commit_sha"]}
    except Exception:
        db.rollback()
        if self.request.retries >= self.max_retries:
            failure_db = SessionLocal()
            try:
                project = failure_db.scalar(select(Project).where(Project.id == project_id).with_for_update())
                if project is not None and project.index_generation == generation:
                    project.sync_status = "SYNC_FAILED"
                    failure_db.commit()
            finally:
                failure_db.close()
        raise
    finally:
        db.close()


@celery.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=2)
def analyze_project(self, project_id: str, index_revision: int):
    from datetime import datetime

    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.models import Dependency, Document, GraphEdge, GraphNode, Project, ProjectAnalysis
    from app.services.code_analysis import analyze_documents

    db = SessionLocal()
    try:
        project = db.scalar(select(Project).where(Project.id == project_id))
        if project is None or project.index_revision != index_revision:
            return {"status": "SKIPPED_STALE"}
        row = db.scalar(select(ProjectAnalysis).where(
            ProjectAnalysis.project_id == project_id,
            ProjectAnalysis.index_revision == index_revision,
        ).with_for_update())
        if row is None:
            row = ProjectAnalysis(project_id=project_id, index_revision=index_revision)
            db.add(row)
            db.flush()
        row.status = "RUNNING"
        row.error = None
        row.updated_at = datetime.utcnow()
        db.commit()

        documents = db.scalars(select(Document).where(Document.project_id == project_id).order_by(Document.path)).all()
        dependencies = db.scalars(select(Dependency).where(Dependency.project_id == project_id)).all()
        nodes = db.scalars(select(GraphNode).where(GraphNode.project_id == project_id)).all()
        edges = db.scalars(select(GraphEdge).where(GraphEdge.project_id == project_id)).all()
        health, findings = analyze_documents(documents, dependencies, nodes, edges)
        row = db.scalar(select(ProjectAnalysis).where(
            ProjectAnalysis.project_id == project_id,
            ProjectAnalysis.index_revision == index_revision,
        ).with_for_update())
        current = db.scalar(select(Project.index_revision).where(Project.id == project_id))
        if current != index_revision:
            row.status = "STALE"
        else:
            row.health = health
            row.findings = findings
            row.status = "COMPLETED"
        row.error = None
        row.updated_at = datetime.utcnow()
        db.commit()
        return {"status": row.status, "finding_count": len(findings)}
    except Exception:
        db.rollback()
        if self.request.retries >= self.max_retries:
            row = db.scalar(select(ProjectAnalysis).where(
                ProjectAnalysis.project_id == project_id,
                ProjectAnalysis.index_revision == index_revision,
            ))
            if row:
                row.status = "FAILED"
                row.error = "Static analysis failed. Check worker health and retry this scan."
                row.updated_at = datetime.utcnow()
                db.commit()
        raise
    finally:
        db.close()


@celery.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=2)
def generate_project_documentation(self, project_id: str, index_revision: int):
    from datetime import datetime

    from sqlalchemy import delete, select

    from app.db.session import SessionLocal
    from app.models.models import Document, GeneratedDocument, GraphEdge, GraphNode, Project, ProjectAnalysis
    from app.services.documentation import generate_project_documents

    db = SessionLocal()
    try:
        project = db.scalar(select(Project).where(Project.id == project_id))
        if project is None or project.index_revision != index_revision:
            return {"status": "SKIPPED_STALE"}
        analysis = db.scalar(select(ProjectAnalysis).where(
            ProjectAnalysis.project_id == project_id,
            ProjectAnalysis.index_revision == index_revision,
        ).with_for_update())
        if analysis is None:
            analysis = ProjectAnalysis(project_id=project_id, index_revision=index_revision)
            db.add(analysis)
            db.flush()
        analysis.documentation_status = "RUNNING"
        analysis.updated_at = datetime.utcnow()
        db.commit()

        documents = db.scalars(select(Document).where(Document.project_id == project_id).order_by(Document.path)).all()
        nodes = db.scalars(select(GraphNode).where(GraphNode.project_id == project_id)).all()
        edges = db.scalars(select(GraphEdge).where(GraphEdge.project_id == project_id)).all()
        generated = generate_project_documents(project, documents, nodes, edges)
        current = db.scalar(select(Project.index_revision).where(Project.id == project_id))
        analysis = db.scalar(select(ProjectAnalysis).where(
            ProjectAnalysis.project_id == project_id,
            ProjectAnalysis.index_revision == index_revision,
        ).with_for_update())
        if current != index_revision:
            analysis.documentation_status = "STALE"
        else:
            db.execute(delete(GeneratedDocument).where(
                GeneratedDocument.project_id == project_id,
                GeneratedDocument.index_revision == index_revision,
            ))
            for item in generated:
                db.add(GeneratedDocument(
                    project_id=project_id,
                    index_revision=index_revision,
                    kind=item["kind"],
                    title=item["title"],
                    scope_key=item["scope_key"],
                    markdown=item["markdown"],
                    source_refs=item["source_refs"],
                ))
            analysis.documentation_status = "COMPLETED"
        analysis.updated_at = datetime.utcnow()
        db.commit()
        return {"status": analysis.documentation_status, "document_count": len(generated)}
    except Exception:
        db.rollback()
        if self.request.retries >= self.max_retries:
            analysis = db.scalar(select(ProjectAnalysis).where(
                ProjectAnalysis.project_id == project_id,
                ProjectAnalysis.index_revision == index_revision,
            ))
            if analysis:
                analysis.documentation_status = "FAILED"
                analysis.updated_at = datetime.utcnow()
                db.commit()
        raise
    finally:
        db.close()
