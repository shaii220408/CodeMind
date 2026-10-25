from alembic import op
import sqlalchemy as sa


revision = "0006_assistant_sources_github"
down_revision = "0005_project_index_generation"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    project_columns = {column["name"] for column in inspector.get_columns("projects")}
    chat_columns = {column["name"] for column in inspector.get_columns("chat_messages")}
    if "repository_branch" not in project_columns:
        op.add_column("projects", sa.Column("repository_branch", sa.String(length=200), nullable=True))
    if "repository_commit_sha" not in project_columns:
        op.add_column("projects", sa.Column("repository_commit_sha", sa.String(length=40), nullable=True))
    if "sync_status" not in project_columns:
        op.add_column(
            "projects",
            sa.Column("sync_status", sa.String(length=30), nullable=False, server_default="NOT_CONFIGURED"),
        )
    if "retrieved_sources" not in chat_columns:
        op.add_column(
            "chat_messages",
            sa.Column("retrieved_sources", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    project_columns = {column["name"] for column in inspector.get_columns("projects")}
    chat_columns = {column["name"] for column in inspector.get_columns("chat_messages")}
    if "retrieved_sources" in chat_columns:
        op.drop_column("chat_messages", "retrieved_sources")
    for column in ("sync_status", "repository_commit_sha", "repository_branch"):
        if column in project_columns:
            op.drop_column("projects", column)
