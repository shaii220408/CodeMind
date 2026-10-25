import uuid
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db.session import SessionLocal
from app.main import app
from app.models.models import Document, Project, User, UserToken
from app.services.security import hash_token


def test_source_viewer_returns_indexed_lines_and_enforces_ownership():
    suffix = uuid.uuid4().hex
    owner = User(email=f"source-owner-{suffix}@example.test", password_hash="unused")
    stranger = User(email=f"source-stranger-{suffix}@example.test", password_hash="unused")
    owner_token = f"source-owner-token-{suffix}"
    stranger_token = f"source-stranger-token-{suffix}"
    db = SessionLocal()
    try:
        db.add_all([owner, stranger])
        db.flush()
        project = Project(owner_id=owner.id, name=f"source-view-{suffix}")
        db.add(project)
        db.flush()
        document = Document(
            project_id=project.id,
            path="src/main.py",
            language="python",
            content_hash="a" * 64,
            content="one\ntwo\nthree\n",
        )
        db.add_all([
            document,
            UserToken(user_id=owner.id, token_hash=hash_token(owner_token), expires_at=datetime.utcnow() + timedelta(days=1)),
            UserToken(user_id=stranger.id, token_hash=hash_token(stranger_token), expires_at=datetime.utcnow() + timedelta(days=1)),
        ])
        project_id = project.id
        db.commit()

        with TestClient(app) as client:
            owner_headers = {"Authorization": f"Bearer {owner_token}"}
            stranger_headers = {"Authorization": f"Bearer {stranger_token}"}
            response = client.get(
                f"/api/projects/{project_id}/source",
                params={"path": "src/main.py", "start_line": 2, "end_line": 3},
                headers=owner_headers,
            )
            assert response.status_code == 200
            assert response.json() == {
                "path": "src/main.py",
                "start_line": 2,
                "end_line": 3,
                "content": "two\nthree",
            }
            assert client.get(
                f"/api/projects/{project_id}/source",
                params={"path": "../main.py"},
                headers=owner_headers,
            ).status_code == 404
            assert client.get(
                f"/api/projects/{project_id}/source",
                params={"path": "src/main.py", "start_line": 1, "end_line": 501},
                headers=owner_headers,
            ).status_code == 422
            assert client.get(
                f"/api/projects/{project_id}/source",
                params={"path": "src/main.py"},
                headers=stranger_headers,
            ).status_code == 404
            assert client.post(
                f"/api/projects/{project_id}/sync",
                headers=stranger_headers,
            ).status_code == 404
    finally:
        db.rollback()
        db.execute(delete(Project).where(Project.name == f"source-view-{suffix}"))
        db.execute(delete(UserToken).where(UserToken.user_id.in_([owner.id, stranger.id])))
        db.execute(delete(User).where(User.email.in_([owner.email, stranger.email])))
        db.commit()
        db.close()
