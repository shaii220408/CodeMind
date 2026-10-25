from pathlib import Path
import uuid

from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models.models import GraphEdge, GraphNode, Project
from app.services import ingestion
from app.services.knowledge_graph import extract_tree_sitter_graph


def test_tree_sitter_graph_extracts_java_javascript_and_typescript_entities():
    samples = {
        "java": (
            "package sample;\nimport sample.Base;\npublic class Worker extends Base implements Runnable {\n"
            "  public void run() { helper(); }\n}\nclass Base {}\n",
            {"class", "method"},
        ),
        "javascript": (
            "import { helper as run } from './utils.js';\nexport class Worker extends Base { execute() { return run(); } }\n",
            {"class", "method"},
        ),
        "typescript": (
            "import { helper } from './helper';\ninterface Runner extends Base { execute(): void; }\nexport class Worker implements Runner { execute(): void { helper(); work(); } }\n",
            {"interface", "class", "method"},
        ),
    }
    for language, (source, expected_kinds) in samples.items():
        graph = extract_tree_sitter_graph(source, f"src/Worker.{ {'java':'java','javascript':'js','typescript':'ts'}[language]}", language)
        assert expected_kinds.issubset({node.kind for node in graph.nodes})
        assert any(edge.relation == "import" for edge in graph.edges)
        assert any(edge.relation == "calls" for edge in graph.edges)
        assert any(edge.relation == "inherits" for edge in graph.edges), language
        if language in {"java", "typescript"}:
            assert any(edge.relation == "implements" for edge in graph.edges)
        if language == "typescript":
            assert any(node.kind == "method" and node.name == "execute" for node in graph.nodes)
        assert all(node.start_line <= node.end_line for node in graph.nodes)


def test_multilanguage_graph_persists_and_resolves_only_explicit_local_import(tmp_path, monkeypatch):
    suffix = uuid.uuid4().hex
    project = Project(name=f"multi-graph-{suffix}")
    db = SessionLocal()
    try:
        db.add(project)
        db.commit()
        project_id = project.id
        monkeypatch.setattr(ingestion, "embed_many", lambda texts: [[0.0] * 384 for _ in texts])
        (tmp_path / "utils.js").write_text("export function helper() { return true; }\n", encoding="utf-8")
        (tmp_path / "caller.js").write_text(
            "import { helper as run } from './utils.js';\nexport function start() { return run(); }\n",
            encoding="utf-8",
        )
        (tmp_path / "Service.java").write_text(
            "package demo;\ninterface Runner {}\nclass Base {}\nclass Service extends Base implements Runner { void execute() { work(); } }\n",
            encoding="utf-8",
        )
        ingestion.index_repository(db, project_id, str(tmp_path))
        nodes = db.scalars(select(GraphNode).where(GraphNode.project_id == project_id)).all()
        edges = db.scalars(select(GraphEdge).where(GraphEdge.project_id == project_id)).all()
        assert {node.source_path for node in nodes} == {"utils.js", "caller.js", "Service.java"}
        helper = next(node for node in nodes if node.qualified_name == "utils.helper")
        imported_call = next(edge for edge in edges if edge.relation == "calls" and edge.target_name == "run")
        assert imported_call.target_node_id == helper.id
        assert imported_call.resolution == "inferred"
        assert any(edge.relation == "inherits" and edge.target_node_id for edge in edges)
        assert any(edge.relation == "implements" and edge.target_node_id for edge in edges)
        assert any(edge.relation == "calls" and edge.target_node_id is None and edge.resolution == "unresolved" for edge in edges)
    finally:
        db.rollback()
        db.execute(delete(Project).where(Project.id == project.id))
        db.commit()
        db.close()
