from alembic import op
import sqlalchemy as sa


revision = "0007_review_health_docs"
down_revision = "0006_assistant_sources_github"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("projects")}
    if "index_revision" not in columns:
        op.add_column("projects", sa.Column("index_revision", sa.Integer(), nullable=False, server_default="0"))
    tables = set(inspector.get_table_names())
    if "project_analyses" not in tables:
        op.create_table(
            "project_analyses",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("index_revision", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="QUEUED"),
            sa.Column("documentation_status", sa.String(20), nullable=False, server_default="NOT_STARTED"),
            sa.Column("health", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("findings", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column("error", sa.Text()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("project_id", "index_revision", name="uq_analysis_project_revision"),
        )
        op.create_index("ix_project_analyses_project_id", "project_analyses", ["project_id"])
        op.create_index("ix_project_analyses_index_revision", "project_analyses", ["index_revision"])
    if "generated_documents" not in tables:
        op.create_table(
            "generated_documents",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("index_revision", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(30), nullable=False),
            sa.Column("title", sa.String(300), nullable=False),
            sa.Column("scope_key", sa.String(1000), nullable=False, server_default=""),
            sa.Column("markdown", sa.Text(), nullable=False),
            sa.Column("source_refs", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("project_id", "index_revision", "kind", "scope_key", name="uq_generated_doc_project_revision_scope"),
        )
        op.create_index("ix_generated_documents_project_id", "generated_documents", ["project_id"])
        op.create_index("ix_generated_documents_index_revision", "generated_documents", ["index_revision"])


def downgrade():
    op.drop_table("generated_documents")
    op.drop_table("project_analyses")
    op.drop_column("projects", "index_revision")
