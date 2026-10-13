from benchmarks.evaluate import score_sources


def test_benchmark_scores_recall_reciprocal_rank_and_citations():
    metrics=score_sources(
        ["src/Expected.java"],
        [{"file":"src/Other.java"},{"file":"src/Expected.java"}],
        [{"file":"src/Expected.java"},{"file":"src/Wrong.java"}],
        top_k=2,
    )

    assert metrics["recall_at_k"]==1.0
    assert metrics["reciprocal_rank"]==0.5
    assert metrics["citation_correct"]==1
    assert metrics["citation_total"]==2
