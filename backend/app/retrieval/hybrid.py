import re

from sqlalchemy import select, text

from app.models.models import Chunk, Document
from app.services.embedding import embed_many

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "does", "for", "from",
    "how", "in", "is", "it", "of", "on", "or", "the", "to", "what", "where", "which", "who",
}


def _terms(value: str) -> set[str]:
    return {word for word in re.findall(r"[a-zA-Z_][a-zA-Z_0-9]{1,}", value.lower()) if word not in STOP_WORDS}


def rrf(rank_lists, k=60):
    scores = {}
    for items in rank_lists:
        for rank, item in enumerate(items, 1):
            scores[item.id] = scores.get(item.id, 0) + 1 / (k + rank)
    return sorted(scores, key=scores.get, reverse=True), scores


def retrieve(db, project_id, question, top_k=8):
    query = embed_many([question])[0]
    candidate_k = min(max(top_k * 4, 20), 100)
    semantic = db.scalars(
        select(Chunk)
        .where(Chunk.project_id == project_id, Chunk.embedding.is_not(None))
        .order_by(Chunk.embedding.cosine_distance(query))
        .limit(candidate_k)
    ).all()
    lexical = db.execute(
        text("""
          SELECT c.id FROM chunks c JOIN documents d ON d.id=c.document_id
          WHERE c.project_id=:pid AND to_tsvector('simple', d.path || ' ' || c.symbol || ' ' || c.content) @@ plainto_tsquery('simple', :q)
          ORDER BY ts_rank(to_tsvector('simple', d.path || ' ' || c.symbol || ' ' || c.content), plainto_tsquery('simple', :q)) DESC LIMIT :lim
        """), {"pid": project_id, "q": question, "lim": candidate_k}
    ).all()
    lexical_ids = [row[0] for row in lexical]
    lexical_chunks = db.scalars(select(Chunk).where(Chunk.id.in_(lexical_ids))).all() if lexical_ids else []
    lexical_order = {chunk.id: index for index, chunk in enumerate(lexical_chunks)}
    lexical_chunks.sort(key=lambda chunk: lexical_order[chunk.id])
    ids, rrf_scores = rrf([semantic, lexical_chunks])
    chunks = db.scalars(select(Chunk).where(Chunk.id.in_(ids))).all()
    by_id = {chunk.id: chunk for chunk in chunks}
    docs = {
        doc.id: doc.path
        for doc in db.scalars(select(Document).where(Document.id.in_([chunk.document_id for chunk in chunks]))).all()
    }
    query_terms = _terms(question)
    max_rrf = max(rrf_scores.values(), default=1) or 1
    candidates = []
    for chunk_id in ids:
        chunk = by_id.get(chunk_id)
        if chunk is None:
            continue
        path = docs.get(chunk.document_id, "")
        terms = _terms(f"{path} {chunk.symbol} {chunk.content}")
        coverage = len(query_terms & terms) / max(1, len(query_terms))
        normalized_rrf = rrf_scores[chunk_id] / max_rrf
        # Lightweight cross-signal reranker: exact query-term coverage is blended
        # with reciprocal-rank fusion so lexical and semantic candidates both count.
        score = 0.75 * coverage + 0.25 * normalized_rrf
        candidates.append({
            "id": chunk_id,
            "file": path,
            "symbol": chunk.symbol,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "content": chunk.content,
            "retrieval_score": round(score, 4),
            "retrieval_source": "rrf+term-rerank",
            "_coverage": coverage,
            "_rrf": rrf_scores[chunk_id],
        })
    candidates.sort(key=lambda item: (item["retrieval_score"], item["_rrf"]), reverse=True)
    results = []
    for candidate in candidates:
        coverage = candidate.pop("_coverage")
        candidate.pop("_rrf")
        if query_terms and coverage == 0:
            continue
        candidate["confidence"] = "high" if candidate["retrieval_score"] >= 0.55 else "medium" if candidate["retrieval_score"] >= 0.3 else "low"
        results.append(candidate)
        if len(results) >= top_k:
            break
    return results
