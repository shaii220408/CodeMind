"""Create CodeRAG project, source, retrieval, and indexing tables."""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from app.core.config import settings

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("repository_url", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("path", sa.String(1000), nullable=False),
        sa.Column("language", sa.String(50), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("project_id", "path", name="uq_project_path"),
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(300), nullable=False, server_default="file"),
        sa.Column("symbol_type", sa.String(50), nullable=False, server_default="block"),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(settings.embedding_dim), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_table(
        "dependencies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_symbol", sa.String(300), nullable=True),
        sa.Column("target", sa.String(1000), nullable=False),
        sa.Column("relation_type", sa.String(50), nullable=False),
    )
    op.create_table(
        "index_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("celery_task_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="QUEUED"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for table, column, name in (
        ("documents", "project_id", "ix_documents_project_id"),
        ("documents", "content_hash", "ix_documents_content_hash"),
        ("chunks", "project_id", "ix_chunks_project_id"),
        ("chunks", "document_id", "ix_chunks_document_id"),
        ("dependencies", "project_id", "ix_dependencies_project_id"),
        ("index_jobs", "project_id", "ix_index_jobs_project_id"),
        ("index_jobs", "celery_task_id", "ix_index_jobs_celery_task_id"),
    ):
        op.create_index(name, table, [column])
    op.execute("CREATE INDEX idx_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops)")
    op.execute("CREATE INDEX idx_chunks_fts ON chunks USING gin(to_tsvector('simple', symbol || ' ' || content))")
    op.execute("CREATE INDEX idx_documents_fts ON documents USING gin(to_tsvector('simple', path || ' ' || content))")


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_documents_fts")
    op.execute("DROP INDEX IF EXISTS idx_chunks_fts")
    op.execute("DROP INDEX IF EXISTS idx_chunks_embedding")
    op.drop_table("index_jobs")
    op.drop_table("dependencies")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("projects")
