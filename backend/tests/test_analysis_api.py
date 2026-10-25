import uuid
from datetime import datetime, timedelta
from unittest.mock import Mock

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.api import analysis_routes
from app.db.session import SessionLocal
from app.main import app
from app.models.models import GeneratedDocument, Project, ProjectAnalysis, User, UserToken
from app.services.security import hash_password, hash_token


def test_analysis_scan_is_owner_scoped_and_duplicate_queue_is_idempotent(monkeypatch):
    suffix = uuid.uuid4().hex
    owner = User(email=f"analysis-owner-{suffix}@example.test", password_hash=hash_password("owner-analysis-password"))
    stranger = User(email=f"analysis-stranger-{suffix}@example.test", password_hash=hash_password("stranger-analysis-password"))
    owner_value, stranger_value = f"analysis-token-{suffix}", f"stranger-token-{suffix}"
    db = SessionLocal()
    try:
        db.add_all([owner, stranger])
        db.flush()
        project = Project(owner_id=owner.id, name=f"analysis-{suffix}", index_revision=4)
        db.add_all([
            project,
            UserToken(user_id=owner.id, token_hash=hash_token(owner_value), expires_at=datetime.utcnow() + timedelta(days=1)),
            UserToken(user_id=stranger.id, token_hash=hash_token(stranger_value), expires_at=datetime.utcnow() + timedelta(days=1)),
        ])
        db.commit()
        project_id, owner_id, stranger_id = project.id, owner.id, stranger.id
    finally:
        db.close()

    delay = Mock(return_value=SimpleTask())
    monkeypatch.setattr(analysis_routes.analyze_project, "delay", delay)
    try:
        with TestClient(app) as client:
            outsider = {"Authorization": f"Bearer {stranger_value}"}
            owner_headers = {"Authorization": f"Bearer {owner_value}"}
            assert client.get(f"/api/projects/{project_id}/analysis", headers=outsider).status_code == 404
            assert client.post(f"/api/projects/{project_id}/analysis/scan", headers=outsider).status_code == 404
            response = client.post(f"/api/projects/{project_id}/analysis/scan", headers=owner_headers)
            assert response.status_code == 200
            assert response.json()["status"] == "QUEUED"
            assert response.json()["index_revision"] == 4
            assert client.post(f"/api/projects/{project_id}/analysis/scan", headers=owner_headers).json()["status"] == "QUEUED"
            delay.assert_called_once_with(project_id, 4)
    finally:
        cleanup = SessionLocal()
        cleanup.execute(delete(Project).where(Project.id == project_id))
        cleanup.execute(delete(UserToken).where(UserToken.user_id.in_([owner_id, stranger_id])))
        cleanup.execute(delete(User).where(User.id.in_([owner_id, stranger_id])))
        cleanup.commit()
        cleanup.close()


def test_generated_document_preview_export_and_regeneration_are_project_scoped(monkeypatch):
    suffix = uuid.uuid4().hex
    owner = User(email=f"docs-owner-{suffix}@example.test", password_hash=hash_password("owner-docs-password"))
    stranger = User(email=f"docs-stranger-{suffix}@example.test", password_hash=hash_password("stranger-docs-password"))
    owner_value, stranger_value = f"docs-token-{suffix}", f"docs-stranger-token-{suffix}"
    db = SessionLocal()
    try:
        db.add_all([owner, stranger])
        db.flush()
        project = Project(owner_id=owner.id, name=f"docs-{suffix}", index_revision=2)
        db.add(project)
        db.flush()
        row = ProjectAnalysis(project_id=project.id, index_revision=2, status="COMPLETED", documentation_status="COMPLETED")
        generated = GeneratedDocument(project_id=project.id, index_revision=2, kind="overview", title="Project overview", scope_key="", markdown="# Safe draft\n", source_refs=["src/main.py"])
        db.add_all([
            row, generated,
            UserToken(user_id=owner.id, token_hash=hash_token(owner_value), expires_at=datetime.utcnow() + timedelta(days=1)),
            UserToken(user_id=stranger.id, token_hash=hash_token(stranger_value), expires_at=datetime.utcnow() + timedelta(days=1)),
        ])
        db.commit()
        project_id, document_id, owner_id, stranger_id = project.id, generated.id, owner.id, stranger.id
    finally:
        db.close()

    delay = Mock(return_value=SimpleTask())
    monkeypatch.setattr(analysis_routes, "generate_project_documentation", Mock(delay=delay))
    try:
        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {owner_value}"}
            assert client.get(f"/api/projects/{project_id}/docs/generated", headers=headers).json()["status"] == "COMPLETED"
            preview = client.get(f"/api/projects/{project_id}/docs/generated/{document_id}", headers=headers)
            assert preview.status_code == 200
            assert preview.json()["markdown"] == "# Safe draft\n"
            export = client.get(f"/api/projects/{project_id}/docs/generated/{document_id}/export", headers=headers)
            assert export.status_code == 200
            assert export.text == "# Safe draft\n"
            queued = client.post(f"/api/projects/{project_id}/docs/generate", headers=headers)
            assert queued.status_code == 200
            assert queued.json()["status"] == "QUEUED"
            assert client.post(f"/api/projects/{project_id}/docs/generate", headers=headers).json()["status"] == "QUEUED"
            delay.assert_called_once_with(project_id, 2)
            stranger_headers = {"Authorization": f"Bearer {stranger_value}"}
            assert client.get(f"/api/projects/{project_id}/docs/generated/{document_id}", headers=stranger_headers).status_code == 404
    finally:
        cleanup = SessionLocal()
        cleanup.execute(delete(Project).where(Project.id == project_id))
        cleanup.execute(delete(UserToken).where(UserToken.user_id.in_([owner_id, stranger_id])))
        cleanup.execute(delete(User).where(User.id.in_([owner_id, stranger_id])))
        cleanup.commit()
        cleanup.close()


class SimpleTask:
    id = "task-id"
