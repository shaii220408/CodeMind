import uuid

from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models.models import Document, GeneratedDocument, Project, ProjectAnalysis
from app.tasks.celery_app import analyze_project, generate_project_documentation


def test_analysis_and_documentation_jobs_persist_revision_scoped_results():
    suffix = uuid.uuid4().hex
    db = SessionLocal()
    try:
        project = Project(name=f"analysis-jobs-{suffix}", index_revision=7)
        db.add(project)
        db.flush()
        db.add_all([
            Document(
                project_id=project.id,
                path="README.md",
                language="markdown",
                content_hash="a" * 64,
                content="# Sample\n\n```powershell\ndocker compose up\n```\n",
            ),
            Document(
                project_id=project.id,
                path="src/main.py",
                language="python",
                content_hash="b" * 64,
                content='"""Sample module."""\ndef run():\n    return 1\n',
            ),
        ])
        db.commit()
        project_id = project.id

        analysis_result = analyze_project.apply(args=(project_id, 7)).get()
        assert analysis_result["status"] == "COMPLETED"
        analysis = db.scalar(select(ProjectAnalysis).where(
            ProjectAnalysis.project_id == project_id,
            ProjectAnalysis.index_revision == 7,
        ))
        assert analysis is not None and analysis.status == "COMPLETED"
        assert analysis.health["total_files"] == 2
        assert analysis.health["test_coverage"]["available"] is False

        docs_result = generate_project_documentation.apply(args=(project_id, 7)).get()
        assert docs_result["status"] == "COMPLETED"
        generated = db.scalars(select(GeneratedDocument).where(
            GeneratedDocument.project_id == project_id,
            GeneratedDocument.index_revision == 7,
        )).all()
        assert len(generated) >= 5
        assert {item.kind for item in generated} >= {"overview", "setup", "module", "api", "architecture"}
        db.refresh(analysis)
        assert analysis.documentation_status == "COMPLETED"
    finally:
        db.rollback()
        if "project_id" in locals():
            db.execute(delete(Project).where(Project.id == project_id))
        db.commit()
        db.close()
