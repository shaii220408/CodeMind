import uuid
from datetime import datetime, timedelta
from unittest.mock import Mock

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api import routes
from app.db.session import SessionLocal
from app.main import app
from app.models.models import Project, User, UserToken
from app.services.security import hash_password, hash_token


def test_public_github_sync_queues_selected_branch_and_enforces_ownership(monkeypatch):
    suffix = uuid.uuid4().hex
    owner = User(email=f"github-sync-owner-{suffix}@example.test", password_hash=hash_password("github-sync-owner-password"))
    stranger = User(email=f"github-sync-stranger-{suffix}@example.test", password_hash=hash_password("github-sync-stranger-password"))
    owner_value, stranger_value = f"github-owner-{suffix}", f"github-stranger-{suffix}"
    db = SessionLocal()
    try:
        db.add_all([owner, stranger])
        db.flush()
        project = Project(owner_id=owner.id, name=f"github-sync-{suffix}", repository_url="https://github.com/octocat/Hello-World")
        db.add_all([
            project,
            UserToken(user_id=owner.id, token_hash=hash_token(owner_value), expires_at=datetime.utcnow() + timedelta(days=1)),
            UserToken(user_id=stranger.id, token_hash=hash_token(stranger_value), expires_at=datetime.utcnow() + timedelta(days=1)),
        ])
        db.commit()
        project_id, owner_id, stranger_id = project.id, owner.id, stranger.id
    finally:
        db.close()

    task = Mock(id="sync-task")
    dispatch = Mock(return_value=task)
    monkeypatch.setattr(routes.sync_github_project, "delay", dispatch)
    try:
        with TestClient(app) as client:
            owner_headers = {"Authorization": f"Bearer {owner_value}"}
            stranger_headers = {"Authorization": f"Bearer {stranger_value}"}
            denied = client.post(f"/api/projects/{project_id}/sync?branch=main", headers=stranger_headers)
            assert denied.status_code == 404
            response = client.post(f"/api/projects/{project_id}/sync?branch=main", headers=owner_headers)
            assert response.status_code == 200
            assert response.json()["status"] == "QUEUED"
            assert response.json()["branch"] == "main"
            dispatch.assert_called_once_with(project_id, "main", 1)
            db = SessionLocal()
            saved = db.scalar(select(Project).where(Project.id == project_id))
            assert saved.repository_branch == "main"
            assert saved.sync_status == "SYNCING"
            db.close()
    finally:
        cleanup = SessionLocal()
        cleanup.execute(delete(Project).where(Project.id == project_id))
        cleanup.execute(delete(UserToken).where(UserToken.user_id.in_([owner_id, stranger_id])))
        cleanup.execute(delete(User).where(User.id.in_([owner_id, stranger_id])))
        cleanup.commit()
        cleanup.close()
