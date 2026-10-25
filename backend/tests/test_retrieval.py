from types import SimpleNamespace

from app.retrieval.hybrid import rrf


def test_rrf_rewards_documents_present_in_both_rankings():
    shared=SimpleNamespace(id="shared")
    semantic_only=SimpleNamespace(id="semantic")
    lexical_only=SimpleNamespace(id="lexical")

    ranked=rrf([[shared,semantic_only],[shared,lexical_only]])

    assert ranked[0]=="shared"
    assert set(ranked)=={"shared","semantic","lexical"}
