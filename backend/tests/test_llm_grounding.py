from app.services import llm


def test_deterministic_fallback_cites_only_supplied_evidence(monkeypatch):
    monkeypatch.setattr(llm.settings,"llm_api_key","")
    evidence=[{
        "file":"src/Service.py","start_line":12,"end_line":18,
        "symbol":"retry","content":"if attempts < limit: retry()",
    }]

    response=llm.answer("Where is retry implemented?",evidence)

    assert "src/Service.py (12-18)" in response
    assert "retry()" in response
    assert "another-file.py" not in response


def test_fallback_reports_insufficient_evidence(monkeypatch):
    monkeypatch.setattr(llm.settings,"llm_api_key","")

    assert "insufficient repository evidence" in llm.answer("Explain missing code",[])
