from sqlalchemy import text

from app.db.session import Base, engine
from app.models.models import Chunk, Dependency, Document, GraphEdge, GraphNode, IndexJob, Project, User, UserToken


def init_db():
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(conn)
        # create_all does not alter a pre-existing projects table.
        conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS owner_id VARCHAR(36)"))
        conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS index_generation INTEGER NOT NULL DEFAULT 0"))
        conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS index_revision INTEGER NOT NULL DEFAULT 0"))
        conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS repository_branch VARCHAR(200)"))
        conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS repository_commit_sha VARCHAR(40)"))
        conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS sync_status VARCHAR(30) NOT NULL DEFAULT 'NOT_CONFIGURED'"))
        conn.execute(text("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS retrieved_sources JSON NOT NULL DEFAULT '[]'::json"))
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'fk_projects_owner_id_users'
                    ) THEN
                        ALTER TABLE projects
                        ADD CONSTRAINT fk_projects_owner_id_users
                        FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE;
                    END IF;
                END
                $$;
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_projects_owner_id ON projects (owner_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_documents_fts ON documents USING gin(to_tsvector('simple', path || ' ' || content))"))
