from sqlalchemy import text
from app.db.session import Base, engine
from app.models.models import Project, Document, Chunk, Dependency

def init_db():
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(conn)
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_documents_fts ON documents USING gin(to_tsvector('simple', path || ' ' || content))"))
