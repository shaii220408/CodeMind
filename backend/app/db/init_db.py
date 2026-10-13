from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.core.config import settings
from app.db.session import engine
from app.models.models import Project, Document, Chunk, Dependency, IndexJob  # noqa: F401

def init_db():
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    with engine.connect() as conn:
        existing = set(inspect(conn).get_table_names())
    if "projects" in existing and "alembic_version" not in existing:
        required_columns = {
            "projects": {"id", "name", "repository_url", "created_at", "updated_at"},
            "documents": {"id", "project_id", "path", "language", "content_hash", "content", "created_at", "updated_at"},
            "chunks": {"id", "project_id", "document_id", "symbol", "symbol_type", "start_line", "end_line", "content", "embedding", "metadata"},
            "dependencies": {"id", "project_id", "source_document_id", "source_symbol", "target", "relation_type"},
            "index_jobs": {"id", "project_id", "celery_task_id", "status", "error", "created_at"},
        }
        with engine.connect() as conn:
            inspector=inspect(conn)
            legacy_schema_matches=all(
                table in existing and columns.issubset({column["name"] for column in inspector.get_columns(table)})
                for table,columns in required_columns.items()
            )
        if not legacy_schema_matches:
            raise RuntimeError("Found a partial unversioned schema; refusing to modify it automatically")
        # Existing CodeRAG installs were created with metadata.create_all(). Stamp
        # the initial schema revision once, then let all future changes migrate.
        command.stamp(config, "0001_initial_schema")
    command.upgrade(config, "head")
