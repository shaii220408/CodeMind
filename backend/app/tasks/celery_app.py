from celery import Celery
from app.core.config import settings
celery=Celery("coderag",broker=settings.redis_url,backend=settings.redis_url)
celery.conf.task_track_started=True

@celery.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=2)
def index_project(self, project_id: str, zip_path: str):
    import tempfile, os
    from app.db.session import SessionLocal
    from app.services.ingestion import safe_extract,index_repository
    db=SessionLocal()
    try:
        with tempfile.TemporaryDirectory() as root:
            safe_extract(zip_path,root,100*1024*1024)
            index_repository(db,project_id,root)
        return {"status":"COMPLETED"}
    finally: db.close()
