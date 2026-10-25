from alembic import op
import sqlalchemy as sa


revision = "0005_project_index_generation"
down_revision = "0004_python_knowledge_graph"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("projects")}
    if "index_generation" not in columns:
        op.add_column("projects", sa.Column("index_generation", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("projects")}
    if "index_generation" in columns:
        op.drop_column("projects", "index_generation")
