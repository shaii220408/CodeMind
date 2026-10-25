import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.main import app
from app.models.models import GraphEdge, GraphNode, Project, User, UserToken
from app.services import ingestion
from app.services.knowledge_graph import extract_python_graph, extract_tree_sitter_graph
from app.services.security import hash_password, hash_token


def test_python_ast_extracts_entities_imports_calls_and_lines():
    graph = extract_python_graph(
        "from helpers import parse\n\nclass Service:\n    def run(self):\n        parse()\n",
        "src/service.py",
    )
    kinds = {(node.kind, node.qualified_name) for node in graph.nodes}
    assert ("file", "src/service.py") in kinds
    assert ("module", "src.service") in kinds
    assert ("class", "src.service.Service") in kinds
    assert ("method", "src.service.Service.run") in kinds
    call = next(edge for edge in graph.edges if edge.relation == "calls")
    imported = next(edge for edge in graph.edges if edge.relation == "import")
    assert call.target_name == "parse" and call.start_line == 5 and call.end_line == 5
    assert imported.target_name == "helpers:parse" and imported.start_line == 1


def test_invalid_python_does_not_emit_inferred_edges():
    graph = extract_python_graph("def broken(:\n    call()\n", "broken.py")
    assert {node.kind for node in graph.nodes} == {"file", "module"}
    assert not [edge for edge in graph.edges if edge.relation in {"calls", "import"}]


def test_calls_in_decorators_and_defaults_belong_to_enclosing_module():
    graph = extract_python_graph("@register(factory())\ndef handler(item=default_value()):\n    run()\n", "handlers.py")
    calls = {(edge.source, edge.target_name) for edge in graph.edges if edge.relation == "calls"}
    assert ("handlers", "register") in calls
    assert ("handlers", "factory") in calls
    assert ("handlers", "default_value") in calls
    assert ("handlers.handler", "run") in calls


def test_graph_index_is_atomic_incremental_and_project_scoped(tmp_path, monkeypatch):
    suffix = uuid.uuid4().hex
    project = Project(name=f"graph-{suffix}")
    other = Project(name=f"graph-other-{suffix}")
    db = SessionLocal()
    try:
        db.add_all([project, other])
        db.commit()
        project_id, other_id = project.id, other.id
        monkeypatch.setattr(ingestion, "embed_many", lambda texts: [[0.0] * 384 for _ in texts])

        (tmp_path / "api.py").write_text("from helpers import work\ndef caller():\n    work()\n", encoding="utf-8")
        (tmp_path / "helpers.py").write_text("def work():\n    return 1\n", encoding="utf-8")
        ingestion.index_repository(db, project_id, str(tmp_path))

        nodes = db.scalars(select(GraphNode).where(GraphNode.project_id == project_id)).all()
        assert any(node.qualified_name == "api.caller" for node in nodes)
        helper = next(node for node in nodes if node.qualified_name == "helpers.work")
        call = db.scalar(select(GraphEdge).where(
            GraphEdge.project_id == project_id,
            GraphEdge.relation == "calls",
            GraphEdge.target_node_id == helper.id,
        ))
        assert call is not None and call.resolution == "inferred"
        initial_ids = {node.id for node in nodes}

        # A queued snapshot from before a newer upload was reserved cannot
        # overwrite the current document or graph state.
        assert ingestion.index_repository(db, project_id, str(tmp_path), generation=99) == "SKIPPED_STALE"
        assert {node.id for node in db.scalars(select(GraphNode).where(GraphNode.project_id == project_id)).all()} == initial_ids

        # Repeated indexing of the same snapshot is idempotent at the row level.
        ingestion.index_repository(db, project_id, str(tmp_path))
        repeated_nodes = db.scalars(select(GraphNode).where(GraphNode.project_id == project_id)).all()
        assert len(repeated_nodes) == len(initial_ids)
        initial_ids = {node.id for node in repeated_nodes}

        # A simulated failure after graph replacement has begun rolls back to the
        # previous graph, because all updates share the indexing transaction.
        (tmp_path / "helpers.py").write_text("def revised():\n    return 2\n", encoding="utf-8")
        (tmp_path / "api.py").unlink()
        def fail_commit():
            raise RuntimeError("simulated commit failure")

        with monkeypatch.context() as patch:
            patch.setattr(db, "commit", fail_commit)
            with pytest.raises(RuntimeError, match="simulated commit failure"):
                ingestion.index_repository(db, project_id, str(tmp_path))
        db.rollback()
        retained = db.scalars(select(GraphNode).where(GraphNode.project_id == project_id)).all()
        assert {node.id for node in retained} == initial_ids

        ingestion.index_repository(db, project_id, str(tmp_path))
        remaining = db.scalars(select(GraphNode).where(GraphNode.project_id == project_id)).all()
        assert not any(node.qualified_name == "api.caller" for node in remaining)
        assert any(node.qualified_name == "helpers.revised" for node in remaining)
        assert not db.scalars(select(GraphEdge).where(
            GraphEdge.project_id == project_id, GraphEdge.relation == "calls",
        )).all()

        # Same file paths in another project cannot see or replace these rows.
        ingestion.index_repository(db, other_id, str(tmp_path))
        other_nodes = db.scalars(select(GraphNode).where(GraphNode.project_id == other_id)).all()
        assert other_nodes
        assert {node.id for node in other_nodes}.isdisjoint({node.id for node in remaining})
    finally:
        db.rollback()
        db.execute(delete(Project).where(Project.id.in_([project.id, other.id])))
        db.commit()
        db.close()


def test_graph_api_enforces_ownership_and_reports_direct_callers(tmp_path, monkeypatch):
    suffix = uuid.uuid4().hex
    password = "graph-test-password-strong"
    owner = User(email=f"owner-{suffix}@example.test", password_hash=hash_password(password))
    stranger = User(email=f"stranger-{suffix}@example.test", password_hash=hash_password("stranger-password-strong"))
    db = SessionLocal()
    try:
        db.add_all([owner, stranger])
        db.flush()
        project = Project(owner_id=owner.id, name=f"graph-api-{suffix}")
        db.add(project)
        db.commit()
        owner_email, stranger_email, project_id = owner.email, stranger.email, project.id
        owner_token_value = f"graph-owner-{suffix}"
        stranger_token_value = f"graph-stranger-{suffix}"
        db.add_all([
            UserToken(user_id=owner.id, token_hash=hash_token(owner_token_value), expires_at=datetime.utcnow() + timedelta(days=1)),
            UserToken(user_id=stranger.id, token_hash=hash_token(stranger_token_value), expires_at=datetime.utcnow() + timedelta(days=1)),
        ])
        db.commit()
        monkeypatch.setattr(ingestion, "embed_many", lambda texts: [[0.0] * 384 for _ in texts])
        (tmp_path / "api.py").write_text(
            "from helpers import work\ndef caller():\n    work()\n    wrapper()\n\ndef wrapper():\n    caller()\n",
            encoding="utf-8",
        )
        (tmp_path / "helpers.py").write_text("def work():\n    return 1\n", encoding="utf-8")
        ingestion.index_repository(db, project_id, str(tmp_path))

        with TestClient(app) as client:
            owner_headers = {"Authorization": f"Bearer {owner_token_value}"}
            stranger_headers = {"Authorization": f"Bearer {stranger_token_value}"}
            graph = client.get(f"/api/projects/{project_id}/graph", headers=owner_headers)
            assert graph.status_code == 200
            assert graph.json()["supported_languages"] == ["python"]
            helper = next(node for node in graph.json()["nodes"] if node["qualified_name"] == "helpers.work")
            impact = client.get(f"/api/projects/{project_id}/graph/impact?node_id={helper['id']}", headers=owner_headers)
            assert impact.status_code == 200
            assert [item["qualified_name"] for item in impact.json()["callers"]] == ["api.caller"]
            assert impact.json()["callers"][0]["resolution"] == "inferred"
            assert impact.json()["transitive_dependents"] == []
            transitive = client.get(
                f"/api/projects/{project_id}/graph/impact?node_id={helper['id']}&max_depth=5",
                headers=owner_headers,
            )
            assert transitive.status_code == 200
            assert transitive.json()["scope"] == "bounded_transitive_callers"
            assert transitive.json()["max_depth"] == 5
            assert [item["qualified_name"] for item in transitive.json()["transitive_dependents"]] == ["api.wrapper"]
            assert transitive.json()["transitive_dependents"][0]["depth"] == 2
            assert client.get(
                f"/api/projects/{project_id}/graph/impact?node_id={helper['id']}&max_depth=6",
                headers=owner_headers,
            ).status_code == 422
            file_impact = client.get(f"/api/projects/{project_id}/graph/impact?path=helpers.py", headers=owner_headers)
            assert file_impact.status_code == 200
            assert {item["relation"] for item in file_impact.json()["direct_dependents"]} == {"calls", "import"}
            assert client.get(f"/api/projects/{project_id}/graph", headers=stranger_headers).status_code == 404
    finally:
        db.rollback()
        db.execute(delete(UserToken).where(UserToken.user_id.in_([owner.id, stranger.id])))
        db.execute(delete(Project).where(Project.id == project.id))
        db.execute(delete(User).where(User.id.in_([owner.id, stranger.id])))
        db.commit()
        db.close()


def test_java_imported_static_calls_resolve_and_transitive_impact(tmp_path, monkeypatch):
    suffix = uuid.uuid4().hex
    db = SessionLocal()
    user = User(email=f"java-impact-{suffix}@example.test", password_hash="unused")
    db.add(user)
    db.flush()
    project = Project(owner_id=user.id, name=f"java-impact-{suffix}")
    db.add(project)
    db.flush()
    token_value = f"java-impact-token-{suffix}"
    db.add(UserToken(user_id=user.id, token_hash=hash_token(token_value), expires_at=datetime.utcnow() + timedelta(days=1)))
    project_id = project.id
    user_id = user.id
    db.commit()
    try:
        base = "package impact;\npublic class Base { public static void leaf() {} }\n"
        middle = "package impact;\nimport impact.Base;\npublic class Middle { public static void run(){ Base.leaf(); } }\n"
        top = "package impact;\nimport impact.Middle;\npublic class Top { public static void execute(){ Middle.run(); } }\n"
        graph = extract_tree_sitter_graph(middle, "src/Middle.java", "java")
        call = next(edge for edge in graph.edges if edge.relation == "calls")
        assert call.target_name == "Base.leaf"
        assert call.start_line == 3 and call.end_line == 3

        (tmp_path / "Base.java").write_text(base, encoding="utf-8")
        (tmp_path / "Middle.java").write_text(middle, encoding="utf-8")
        (tmp_path / "Top.java").write_text(top, encoding="utf-8")
        monkeypatch.setattr(ingestion, "embed_many", lambda texts: [[0.0] * 384 for _ in texts])
        ingestion.index_repository(db, project_id, str(tmp_path))

        headers = {"Authorization": f"Bearer {token_value}"}
        with TestClient(app) as client:
            impact = client.get(f"/api/projects/{project_id}/graph/impact?path=Base.java&max_depth=3", headers=headers)
        assert impact.status_code == 200, impact.text
        result = impact.json()
        assert [(item["qualified_name"], item["resolution"]) for item in result["callers"]] == [
            ("impact.Middle.run", "inferred")
        ]
        assert [(item["qualified_name"], item["depth"], item["resolution"]) for item in result["transitive_dependents"]] == [
            ("impact.Top.execute", 2, "inferred")
        ]
    finally:
        db.rollback()
        cleanup = SessionLocal()
        cleanup.execute(delete(Project).where(Project.id == project_id))
        cleanup.execute(delete(UserToken).where(UserToken.user_id == user_id))
        cleanup.execute(delete(User).where(User.id == user_id))
        cleanup.commit()
        cleanup.close()
        db.close()
