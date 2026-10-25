from alembic import op
from sqlalchemy import inspect, text

from app.db.session import Base
from app.models import models  # noqa: F401

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=bind)
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("projects")}
    if "owner_id" not in columns:
        op.add_column("projects", models.Project.__table__.c.owner_id.copy())
    foreign_keys = inspector.get_foreign_keys("projects")
    if not any(fk.get("name") == "fk_projects_owner_id_users" for fk in foreign_keys):
        op.create_foreign_key("fk_projects_owner_id_users", "projects", "users", ["owner_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"], if_not_exists=True)
    bind.execute(text("CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops)"))
    bind.execute(text("CREATE INDEX IF NOT EXISTS idx_documents_fts ON documents USING gin(to_tsvector('simple', path || ' ' || content))"))


def downgrade():
    # Keep user data by default; destructive teardown is intentionally explicit.
    op.drop_index("ix_projects_owner_id", table_name="projects")
