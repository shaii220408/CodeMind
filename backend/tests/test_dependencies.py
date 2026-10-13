from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.dependencies import analyze_impact, search_dependencies


def test_dependency_search_returns_joined_edge_fields_without_row_attribute_assumptions():
    edge = SimpleNamespace(
        source_document_id="doc-1", source_symbol="notify",
        target="NotificationService", relation_type="class_reference",
    )
    db = MagicMock()
    db.execute.return_value.all.return_value = [(edge, "src/Notifier.java")]

    rows = search_dependencies(db, "project-1", "NotificationService")

    assert rows == [{
        "source_document_id": "doc-1", "source_file": "src/Notifier.java",
        "source_symbol": "notify", "target": "NotificationService",
        "relation_type": "class_reference",
    }]


def test_dependency_search_empty_query_lists_project_edges():
    db = MagicMock()
    db.execute.return_value.all.return_value = []

    assert search_dependencies(db, "project-1", " ") == []
    assert db.execute.call_count == 1


def test_impact_analysis_traces_direct_and_transitive_dependents():
    docs = [
        ("auth", "src/AuthService.java"),
        ("api", "src/ApiService.java"),
        ("web", "src/WebController.java"),
    ]
    chunks = [("auth", "AuthService"), ("api", "ApiService"), ("web", "WebController")]
    edges = [
        SimpleNamespace(source_document_id="api", source_symbol="login", target="AuthService", relation_type="class_reference"),
        SimpleNamespace(source_document_id="web", source_symbol="handle", target="ApiService", relation_type="class_reference"),
    ]
    db = MagicMock()
    db.execute.return_value.all.side_effect = [
        docs, chunks,
        [(edge.source_document_id, edge.source_symbol, edge.target, edge.relation_type) for edge in edges],
    ]

    result = analyze_impact(db, "project-1", "AuthService")

    assert result["root_files"] == ["src/AuthService.java"]
    assert result["affected_files"] == [
        {"file": "src/ApiService.java", "depth": 1, "reasons": ["login — class_reference: AuthService"]},
        {"file": "src/WebController.java", "depth": 2, "reasons": ["handle — class_reference: ApiService"]},
    ]


def test_impact_analysis_matches_file_paths_and_returns_none_for_unknown_target():
    docs = [("repo", "src/repository.py")]
    db = MagicMock()
    db.execute.return_value.all.side_effect = [docs, [], []]

    assert analyze_impact(db, "project-1", "src/repository.py")["root_files"] == ["src/repository.py"]

    db.execute.return_value.all.side_effect = [docs, [], []]
    assert analyze_impact(db, "project-1", "MissingService") is None
