"""Add trigram indexes for responsive dependency and impact searches."""

from alembic import op

revision = "0002_dependency_search_indexes"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE INDEX ix_dependencies_target_trgm ON dependencies USING gin (target gin_trgm_ops)")
    op.execute("CREATE INDEX ix_dependencies_source_symbol_trgm ON dependencies USING gin (source_symbol gin_trgm_ops)")
    op.execute("CREATE INDEX ix_documents_path_trgm ON documents USING gin (path gin_trgm_ops)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_documents_path_trgm")
    op.execute("DROP INDEX IF EXISTS ix_dependencies_source_symbol_trgm")
    op.execute("DROP INDEX IF EXISTS ix_dependencies_target_trgm")
