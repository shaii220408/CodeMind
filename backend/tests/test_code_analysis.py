from types import SimpleNamespace

from app.services.code_analysis import analyze_documents
from app.services.documentation import generate_project_documents


def test_static_review_redacts_secret_and_reports_complexity_and_duplicates():
    shared = "\n".join(f"    value_{index} = value_{index} + 1" for index in range(8))
    first = SimpleNamespace(id="1", path="a.py", language="python", content=(
        "API_TOKEN = 'ghp_very_secret_value_123'\n"
        "def risky(text):\n    return eval(text)\n"
        "def tangled(a):\n"
        "    if a:\n        if a > 1:\n            if a > 2:\n                if a > 3:\n                    if a > 4:\n                        if a > 5:\n                            if a > 6:\n                                if a > 7:\n                                    if a > 8:\n                                        if a > 9:\n                                            return 1\n"
        + shared + "\n"
    ))
    second = SimpleNamespace(id="2", path="b.py", language="python", content=shared)
    health, findings = analyze_documents([first, second])
    assert health["total_files"] == 2
    assert health["complexity"]["high_complexity_functions"] == 1
    assert health["test_coverage"] == {"available": False, "value": None, "reason": "No reliable coverage artifact is attached to this indexed revision."}
    assert any(item["rule_id"] == "SEC-DYNAMIC-EVAL" for item in findings)
    assert any(item["rule_id"] == "MAINT-DUPLICATE-BLOCK" for item in findings)
    credential = next(item for item in findings if item["rule_id"] == "SEC-HARDCODED-CREDENTIAL")
    assert "ghp_very_secret_value_123" not in credential["evidence"]
    assert "[REDACTED]" in credential["evidence"]
    assert credential["origin"] == "static_rule"


def test_health_reports_complexity_unavailable_without_python_and_no_fake_coverage():
    doc = SimpleNamespace(id="1", path="main.js", language="javascript", content="export const main = () => 1;\n")
    health, _ = analyze_documents([doc])
    assert health["complexity"]["available"] is False
    assert health["complexity"]["average_python_cyclomatic"] is None
    assert health["test_coverage"]["available"] is False
    assert health["source_lines"] == 1


def test_generated_docs_include_only_detected_routes_and_resolved_mermaid_edges():
    project = SimpleNamespace(name="sample", index_revision=3)
    doc = SimpleNamespace(
        id="doc", path="app/routes.py", language="python",
        content='"""Route module."""\nfrom fastapi import APIRouter\nrouter = APIRouter()\n@router.get("/items")\ndef list_items():\n    """List items."""\n    return []\n\ndef helper(client):\n    return client.get("/not-a-route")\n',
    )
    left = SimpleNamespace(id="node-a", kind="module", source_path="app/routes.py", start_line=1, end_line=7, name="routes", qualified_name="app.routes")
    right = SimpleNamespace(id="node-b", kind="class", source_path="app/models.py", start_line=3, end_line=8, name="Item", qualified_name="app.models.Item")
    edges = [SimpleNamespace(source_node_id=left.id, target_node_id=right.id, relation="import", resolution="inferred")]
    generated = generate_project_documents(project, [doc], [left, right], edges)
    api = next(item for item in generated if item["kind"] == "api")
    architecture = next(item for item in generated if item["kind"] == "architecture")
    setup = next(item for item in generated if item["kind"] == "setup")
    assert "GET" in api["markdown"] and "`/items`" in api["markdown"]
    assert "/not-a-route" not in api["markdown"]
    assert "app/routes.py#L4" in api["markdown"]
    assert "--> |import|" not in architecture["markdown"]
    assert "-->|import|" in architecture["markdown"]
    assert "No README setup instructions were indexed" in setup["markdown"]
    assert all(item["source_refs"] is not None for item in generated)
