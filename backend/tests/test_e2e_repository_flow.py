"""PostgreSQL-backed repository upload -> index -> dependency search -> cited ask."""

import io
import zipfile

from fastapi.testclient import TestClient

from app.api import routes
from app.core.config import settings
from app.db.session import SessionLocal
from app.main import app
from app.models.models import Project
from app.services.rate_limit import limit_ask_requests, limit_dependency_requests, limit_upload_requests
from app.services.llm import AnswerResult


def test_upload_index_dependency_search_and_cited_ask(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    vector = [1.0] + [0.0] * (settings.embedding_dim - 1)
    monkeypatch.setattr("app.services.ingestion.embed_many", lambda texts: [vector for _ in texts])
    monkeypatch.setattr("app.retrieval.hybrid.embed_many", lambda _texts: [vector])
    enqueued = []

    def capture_task(*_args, **kwargs):
        enqueued.extend(kwargs.get("args", _args))

    monkeypatch.setattr(routes.index_project, "apply_async", capture_task)
    monkeypatch.setattr(
        routes, "answer",
        lambda _question, evidence: AnswerResult(
            f"Found {evidence[0]['symbol']} in {evidence[0]['file']}." if evidence else "Insufficient evidence.",
            "fallback" if evidence else "abstention",
            [{"file": evidence[0]["file"], "start_line": evidence[0]["start_line"], "end_line": evidence[0]["end_line"], "symbol": evidence[0]["symbol"]}] if evidence else [],
        ),
    )
    app.dependency_overrides[limit_ask_requests] = lambda: None
    app.dependency_overrides[limit_dependency_requests] = lambda: None
    app.dependency_overrides[limit_upload_requests] = lambda: None
    project_id = None
    try:
        with TestClient(app) as client:
            created = client.post("/api/projects", json={"name": "repository flow e2e"})
            assert created.status_code == 200
            project_id = created.json()["id"]

            repository = io.BytesIO()
            with zipfile.ZipFile(repository, "w") as archive:
                archive.writestr(
                    "src/NotificationService.java",
                    "package sample;\npublic class NotificationService {\n  public void retryNotification() {}\n}\n",
                )
                archive.writestr(
                    "src/NotificationController.java",
                    "package sample;\npublic class NotificationController {\n  private NotificationService service;\n}\n",
                )
            queued = client.post(
                f"/api/projects/{project_id}/upload",
                files={"file": ("repository.zip", repository.getvalue(), "application/zip")},
            )
            assert queued.status_code == 200
            task = routes.index_project.apply(
                args=enqueued,
                task_id=queued.json()["task_id"],
                throw=True,
            )
            assert task.get()["status"] == "COMPLETED"

            status = client.get(f"/api/projects/{project_id}/status")
            assert status.json()["status"] == "COMPLETED"
            files = client.get(f"/api/projects/{project_id}/files")
            assert files.status_code == 200
            assert len(files.json()) == 2
            source = client.get(f"/api/projects/{project_id}/files/src/NotificationService.java")
            assert source.status_code == 200
            assert "retryNotification" in source.json()["content"]

            edges = client.get(f"/api/projects/{project_id}/dependencies?target=NotificationService")
            assert edges.status_code == 200
            assert any(edge["source_file"] == "src/NotificationController.java" for edge in edges.json())

            answer = client.post(
                "/api/ask",
                json={"project_id": project_id, "question": "Where is retryNotification implemented?"},
            )
            assert answer.status_code == 200
            assert any(citation["file"] == "src/NotificationService.java" for citation in answer.json()["citations"])
    finally:
        app.dependency_overrides.pop(limit_ask_requests, None)
        app.dependency_overrides.pop(limit_dependency_requests, None)
        app.dependency_overrides.pop(limit_upload_requests, None)
        if project_id:
            with SessionLocal() as db:
                project = db.get(Project, project_id)
                if project:
                    db.delete(project)
                    db.commit()
