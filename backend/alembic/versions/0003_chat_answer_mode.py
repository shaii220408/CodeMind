from alembic import op
import sqlalchemy as sa

revision = "0003_chat_answer_mode"
down_revision = "0002_chat_history"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("chat_messages")}
    # Migration 0002 creates its table from the current model on fresh databases.
    if "answer_mode" not in columns:
        op.add_column("chat_messages", sa.Column("answer_mode", sa.String(length=20), nullable=True))


def downgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("chat_messages")}
    if "answer_mode" in columns:
        op.drop_column("chat_messages", "answer_mode")
