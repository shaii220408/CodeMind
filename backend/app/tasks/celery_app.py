from celery import Celery
from app.core.config import settings
celery=Celery("coderag",broker=settings.redis_url,backend=settings.redis_url)
celery.conf.task_track_started=True

@celery.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=2)
def index_project(self, project_id: str, zip_path: str | None = None, repository_url: str | None = None):
    import tempfile, os
    from app.db.session import SessionLocal
    from app.models.models import IndexJob
    from app.services.ingestion import safe_extract,index_repository,reindex_saved_documents
    from app.services.repository import clone_repository
    db=SessionLocal()
    succeeded = False
    try:
        job = db.query(IndexJob).filter(IndexJob.celery_task_id == self.request.id).first()
        if job:
            job.status = "PROCESSING"
            job.error = None
            db.commit()
        if zip_path:
            with tempfile.TemporaryDirectory() as root:
                safe_extract(
                    zip_path,
                    root,
                    settings.max_archive_mb * 1024 * 1024,
                    settings.max_archive_files,
                )
                index_repository(db,project_id,root)
        elif repository_url:
            with tempfile.TemporaryDirectory() as root:
                checkout=os.path.join(root,"checkout")
                clone_repository(repository_url,checkout)
                index_repository(db,project_id,checkout)
        else:
            reindex_saved_documents(db, project_id)
        if job:
            job.status = "COMPLETED"
            db.commit()
        succeeded = True
        return {"status":"COMPLETED"}
    except Exception as exc:
        db.rollback()
        job = db.query(IndexJob).filter(IndexJob.celery_task_id == self.request.id).first()
        if job:
            if self.request.retries >= self.max_retries:
                job.status = "FAILED"
                # Keep the stored diagnostic useful without returning stack traces to clients.
                job.error = f"{type(exc).__name__}: {exc}"[:2000]
            else:
                job.status = "PROCESSING"
            db.commit()
        raise
    finally:
        db.close()
        # Keep the archive available for Celery autoretries; remove it after
        # success or after the final failed attempt.
        if zip_path and (succeeded or self.request.retries >= self.max_retries):
            try:
                os.unlink(zip_path)
            except FileNotFoundError:
                pass
