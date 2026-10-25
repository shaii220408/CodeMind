from alembic import op
import sqlalchemy as sa


revision = "0004_python_knowledge_graph"
down_revision = "0003_chat_answer_mode"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "graph_nodes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.String(length=36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("qualified_name", sa.String(length=1200), nullable=False),
        sa.Column("source_path", sa.String(length=1000), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.UniqueConstraint("project_id", "source_path", "kind", "qualified_name", "start_line", name="uq_graph_node_source_identity"),
    )
    op.create_index("ix_graph_nodes_project_id", "graph_nodes", ["project_id"])
    op.create_index("ix_graph_nodes_document_id", "graph_nodes", ["document_id"])
    op.create_index("ix_graph_nodes_kind", "graph_nodes", ["kind"])
    op.create_index("ix_graph_nodes_source_path", "graph_nodes", ["source_path"])

    op.create_table(
        "graph_edges",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_node_id", sa.String(length=36), sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_node_id", sa.String(length=36), sa.ForeignKey("graph_nodes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("relation", sa.String(length=30), nullable=False),
        sa.Column("target_name", sa.String(length=1200), nullable=False),
        sa.Column("resolution", sa.String(length=20), nullable=False, server_default="unresolved"),
        sa.Column("source_path", sa.String(length=1000), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
    )
    op.create_index("ix_graph_edges_project_id", "graph_edges", ["project_id"])
    op.create_index("ix_graph_edges_source_node_id", "graph_edges", ["source_node_id"])
    op.create_index("ix_graph_edges_target_node_id", "graph_edges", ["target_node_id"])
    op.create_index("ix_graph_edges_relation", "graph_edges", ["relation"])
    op.create_index("ix_graph_edges_source_path", "graph_edges", ["source_path"])


def downgrade():
    op.drop_table("graph_edges")
    op.drop_table("graph_nodes")
