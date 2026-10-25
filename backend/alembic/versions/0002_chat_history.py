from alembic import op

from app.models.models import ChatMessage

revision = "0002_chat_history"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade():
    ChatMessage.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    ChatMessage.__table__.drop(bind=op.get_bind(), checkfirst=True)
