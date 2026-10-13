from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine
from app.models.models import Chunk, Document, Project
from app.retrieval import hybrid


def test_hybrid_search_returns_project_scoped_cited_code(monkeypatch):
    monkeypatch.setattr(hybrid,"embed_many",lambda _texts:[[1.0]+[0.0]*(settings.embedding_dim-1)])
    with engine.connect() as connection:
        transaction=connection.begin()
        try:
            with Session(bind=connection,expire_on_commit=False) as db:
                project=Project(name="retrieval integration")
                db.add(project)
                db.flush()
                document=Document(
                    project_id=project.id,path="src/NotificationService.java",language="java",
                    content_hash="a"*64,content="class NotificationService retryNotification() { retry(); }",
                )
                db.add(document)
                db.flush()
                expected=Chunk(
                    project_id=project.id,document_id=document.id,symbol="retryNotification",
                    symbol_type="method",start_line=20,end_line=29,
                    content="NotificationService retry logic retries delivery",embedding=[1.0]+[0.0]*(settings.embedding_dim-1),
                    metadata={"language":"java"},
                )
                db.add(expected)
                db.flush()

                results=hybrid.retrieve(db,project.id,"Where is retry logic?",top_k=3)

                assert results
                assert results[0]["id"]==expected.id
                assert results[0]["file"]=="src/NotificationService.java"
                assert results[0]["start_line"]==20
                assert results[0]["retrieval_score"]>0
        finally:
            transaction.rollback()
