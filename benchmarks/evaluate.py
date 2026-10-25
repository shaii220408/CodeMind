#!/usr/bin/env python3
"""Evaluate CodeMind retrieval and citation quality against labelled questions."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import requests


def normalized(path: str) -> str:
    return path.replace("\\", "/").lstrip("./").casefold()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def evaluate(api_url: str, project_id: str, questions_path: Path, k: int, token: str | None = None) -> dict[str, Any]:
    questions = json.loads(questions_path.read_text(encoding="utf-8"))
    if not isinstance(questions, list) or not questions:
        raise ValueError("questions.json must contain a non-empty JSON array")

    warmup_started = time.perf_counter()
    warmup = requests.post(
        f"{api_url.rstrip('/')}/api/ask",
        headers={"Authorization": f"Bearer {token}"} if token else None,
        json={"project_id": project_id, "question": questions[0]["question"], "top_k": k},
        timeout=180,
    )
    warmup.raise_for_status()
    warmup_latency_ms = (time.perf_counter() - warmup_started) * 1000

    rows = []
    latencies = []
    retrieval_recall = []
    reciprocal_ranks = []
    correct_citations = 0
    total_citations = 0
    answers_with_correct_citation = 0

    for item in questions:
        relevant = {normalized(file) for file in item["relevant_files"]}
        started = time.perf_counter()
        response = requests.post(
            f"{api_url.rstrip('/')}/api/ask",
            headers={"Authorization": f"Bearer {token}"} if token else None,
            json={"project_id": project_id, "question": item["question"], "top_k": k},
            timeout=180,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        response.raise_for_status()
        payload = response.json()
        latencies.append(latency_ms)

        retrieved = payload.get("retrieved_sources", [])
        ranked_files = [normalized(source["file"]) for source in retrieved]
        hits = len(relevant.intersection(ranked_files))
        retrieval_recall.append(hits / len(relevant) if relevant else 0.0)
        first_relevant_rank = next(
            (rank for rank, file in enumerate(ranked_files, start=1) if file in relevant),
            None,
        )
        reciprocal_rank = 1 / first_relevant_rank if first_relevant_rank else 0.0
        reciprocal_ranks.append(reciprocal_rank)

        citations = payload.get("citations", [])
        citation_files = {normalized(citation["file"]) for citation in citations}
        citation_hits = sum(file in relevant for file in citation_files)
        correct_citations += citation_hits
        total_citations += len(citation_files)
        citation_ok = citation_hits > 0
        answers_with_correct_citation += int(citation_ok)

        rows.append(
            {
                "id": item["id"],
                "latency_ms": round(latency_ms, 1),
                "relevant_files": sorted(relevant),
                "retrieved_files": ranked_files,
                "recall_at_k": round(retrieval_recall[-1], 4),
                "reciprocal_rank": round(reciprocal_rank, 4),
                "citation_correct": citation_ok,
            }
        )

    count = len(rows)
    return {
        "project_id": project_id,
        "api_url": api_url.rstrip("/"),
        "k": k,
        "question_count": count,
        "warmup_latency_ms": round(warmup_latency_ms, 1),
        "metrics": {
            "recall_at_k": round(statistics.mean(retrieval_recall), 4),
            "mrr": round(statistics.mean(reciprocal_ranks), 4),
            "citation_accuracy": round(correct_citations / total_citations, 4)
            if total_citations
            else 0.0,
            "answers_with_correct_citation_rate": round(
                answers_with_correct_citation / count, 4
            ),
            "latency_ms_mean": round(statistics.mean(latencies), 1),
            "latency_ms_p50": round(percentile(latencies, 0.50), 1),
            "latency_ms_p95": round(percentile(latencies, 0.95), 1),
        },
        "definitions": {
            "recall_at_k": "Per-question fraction of labelled relevant files present in the top K retrieved sources, averaged over questions.",
            "mrr": "Mean reciprocal rank of the first retrieved source matching a labelled relevant file.",
            "citation_accuracy": "File-level precision: distinct relevant cited files divided by all distinct cited files.",
            "answers_with_correct_citation_rate": "Fraction of answers containing at least one citation to a labelled relevant file.",
            "latency": "Mean/percentile values are measured after one warmup request; warmup_latency_ms reports that first call separately.",
        },
        "results": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.getenv("CODERAG_API_URL", "http://localhost:8000"))
    parser.add_argument("--project-id", default=os.getenv("CODERAG_PROJECT_ID"))
    parser.add_argument(
        "--questions",
        type=Path,
        default=Path(__file__).with_name("questions.json"),
    )
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--token", default=os.getenv("CODERAG_TOKEN"), help="Bearer session token (or CODERAG_TOKEN)")
    args = parser.parse_args()
    if not args.project_id:
        parser.error("--project-id or CODERAG_PROJECT_ID is required")
    if not 1 <= args.k <= 30:
        parser.error("--k must be between 1 and 30")

    try:
        report = evaluate(args.api_url, args.project_id, args.questions, args.k, args.token)
    except (OSError, ValueError, requests.RequestException, KeyError) as error:
        print(f"Evaluation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

