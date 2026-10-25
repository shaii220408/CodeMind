from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.models.models import Chunk, Dependency, Document, Project
from app.services.rate_limit import limit_dependency_requests
from app.core.config import settings


def test_project_create_list_and_overview_api_contract():
    project_id=None
    with TestClient(app) as client:
        try:
            created=client.post("/api/projects",json={"name":" API contract test "})
            assert created.status_code==200
            project=created.json()
            project_id=project["id"]
            assert project["name"]=="API contract test"
            assert project["repository_url"] is None

            listed=client.get("/api/projects")
            assert listed.status_code==200
            assert any(item["id"]==project_id for item in listed.json())

            overview=client.get(f"/api/projects/{project_id}/overview")
            assert overview.status_code==200
            assert overview.json()=={
                "project_id":project_id,"file_count":0,"chunk_count":0,"languages":{},
            }
        finally:
            if project_id:
                with SessionLocal() as db:
                    project=db.get(Project,project_id)
                    if project:
                        db.delete(project)
                        db.commit()


def test_dependency_search_and_impact_api_end_to_end():
    project_id = None
    app.dependency_overrides[limit_dependency_requests] = lambda: None
    with TestClient(app) as client:
        try:
            response = client.post("/api/projects", json={"name": "dependency API test"})
            assert response.status_code == 200
            project_id = response.json()["id"]
            with SessionLocal() as db:
                provider = Document(
                    project_id=project_id, path="src/NotificationService.java", language="java",
                    content_hash="b" * 64, content="class NotificationService {}",
                )
                consumer = Document(
                    project_id=project_id, path="src/Notifier.java", language="java",
                    content_hash="c" * 64, content="class Notifier {}",
                )
                db.add_all([provider, consumer])
                db.flush()
                db.add_all([
                    Chunk(project_id=project_id, document_id=provider.id, symbol="NotificationService", symbol_type="class", start_line=1, end_line=1, content="class NotificationService {}", embedding=None),
                    Chunk(project_id=project_id, document_id=consumer.id, symbol="notify", symbol_type="method", start_line=1, end_line=1, content="void notify() {}", embedding=None),
                    Dependency(project_id=project_id, source_document_id=consumer.id, source_symbol="notify", target="NotificationService", relation_type="class_reference"),
                ])
                consumer_id = consumer.id
                db.commit()

            found = client.get(f"/api/projects/{project_id}/dependencies?target=NotificationService")
            assert found.status_code == 200
            assert found.json() == [{
                "source_document_id": consumer_id,
                "source_file": "src/Notifier.java",
                "source_symbol": "notify",
                "target": "NotificationService",
                "relation_type": "class_reference",
            }]

            impact = client.get(f"/api/projects/{project_id}/impact?target=NotificationService")
            assert impact.status_code == 200
            assert impact.json()["root_files"] == ["src/NotificationService.java"]
            assert impact.json()["affected_files"][0]["file"] == "src/Notifier.java"
        finally:
            app.dependency_overrides.pop(limit_dependency_requests, None)
            if project_id:
                with SessionLocal() as db:
                    project = db.get(Project, project_id)
                    if project:
                        db.delete(project)
                        db.commit()


def test_configured_api_key_protects_api_routes(monkeypatch):
    monkeypatch.setattr(settings, "api_access_token", "t" * 48)
    with TestClient(app) as client:
        assert client.get("/api/projects").status_code == 401
        authorized = client.get("/api/projects", headers={"Authorization": f"Bearer {'t' * 48}"})
        assert authorized.status_code == 200
