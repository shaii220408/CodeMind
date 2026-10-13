"""Run the sample repository through CodeRAG and report retrieval/latency metrics."""

import argparse
import json
import tempfile
import time
import zipfile
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = Path(__file__).with_name("questions.json")


def score_sources(expected, ranked, citations, top_k):
    expected_set = set(expected)
    top_paths = [item["file"] for item in ranked[:top_k]]
    relevant_rank = next((i for i, path in enumerate(top_paths, 1) if path in expected_set), None)
    correct_citations = sum(1 for item in citations if item["file"] in expected_set)
    return {
        "recall_at_k": float(any(path in expected_set for path in top_paths)),
        "reciprocal_rank": 1 / relevant_rank if relevant_rank else 0.0,
        "citation_correct": correct_citations,
        "citation_total": len(citations),
    }


def make_repository_zip(directory: Path, output: Path):
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in directory.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(directory).as_posix())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--repository", type=Path, default=ROOT / "sample_repo")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--output", type=Path, default=Path("benchmark-report.json"))
    args = parser.parse_args()
    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as temp_dir, httpx.Client(base_url=args.base_url, timeout=60) as client:
        archive_path = Path(temp_dir) / "sample.zip"
        make_repository_zip(args.repository, archive_path)
        response = client.post("/api/projects", json={"name": f"benchmark-{int(time.time())}"})
        response.raise_for_status()
        project_id = response.json()["id"]
        upload_started = time.perf_counter()
        with archive_path.open("rb") as archive:
            response = client.post(
                f"/api/projects/{project_id}/upload",
                files={"file": ("sample.zip", archive, "application/zip")},
            )
        response.raise_for_status()
        deadline = time.monotonic() + args.timeout_seconds
        while time.monotonic() < deadline:
            status = client.get(f"/api/projects/{project_id}/status")
            status.raise_for_status()
            state = status.json()
            if state["status"] == "COMPLETED":
                break
            if state["status"] == "FAILED":
                raise RuntimeError(f"Indexing failed: {state.get('error') or 'no error details'}")
            time.sleep(2)
        else:
            raise TimeoutError("Indexing did not finish before the configured timeout")
        indexing_seconds = time.perf_counter() - upload_started

        rows = []
        recall_total = reciprocal_rank_total = citation_correct = citation_total = 0
        query_seconds = []
        for item in questions:
            query_started = time.perf_counter()
            response = client.post("/api/ask", json={
                "project_id": project_id,
                "question": item["question"],
                "top_k": args.top_k,
            })
            response.raise_for_status()
            elapsed = time.perf_counter() - query_started
            result = response.json()
            metrics = score_sources(item["expected_sources"], result["retrieved_sources"], result["citations"], args.top_k)
            recall_total += metrics["recall_at_k"]
            reciprocal_rank_total += metrics["reciprocal_rank"]
            citation_correct += metrics["citation_correct"]
            citation_total += metrics["citation_total"]
            query_seconds.append(elapsed)
            rows.append({
                "question": item["question"],
                "expected_sources": item["expected_sources"],
                "answer": result["answer"],
                "retrieved_sources": result["retrieved_sources"],
                "citations": result["citations"],
                "query_latency_seconds": round(elapsed, 4),
                "groundedness_score": None,
            })

    report = {
        "project_id": project_id,
        "top_k": args.top_k,
        "indexing_latency_seconds": round(indexing_seconds, 4),
        "mean_query_latency_seconds": round(sum(query_seconds) / len(query_seconds), 4),
        "recall_at_k": recall_total / len(rows),
        "mrr": reciprocal_rank_total / len(rows),
        "citation_accuracy": citation_correct / citation_total if citation_total else 0.0,
        "groundedness": "manual review required; score each answer 0 (unsupported), 1 (partially supported), or 2 (well supported)",
        "results": rows,
    }
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, indent=2))
    print(f"Detailed answers and evidence: {args.output.resolve()}")


if __name__ == "__main__":
    main()
