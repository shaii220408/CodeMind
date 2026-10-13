"""Project-scoped dependency search and bounded reverse impact traversal."""

import re
from collections import deque
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.models import Chunk, Dependency, Document

MAX_IMPACT_FILES = 200
MAX_GRAPH_ROWS = 100_000


def search_dependencies(
    db: Session, project_id: str, target: str | None = None,
    limit: int = 200, offset: int = 0,
):
    stmt = (
        select(Dependency, Document.path)
        .join(Document, Document.id == Dependency.source_document_id)
        .where(Dependency.project_id == project_id)
    )
    if target and target.strip():
        # Escape LIKE metacharacters: search text must remain a literal substring.
        escaped = target.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        stmt = stmt.where(or_(
            Dependency.target.ilike(pattern, escape="\\"),
            Dependency.source_symbol.ilike(pattern, escape="\\"),
            Document.path.ilike(pattern, escape="\\"),
        ))
    rows = db.execute(
        stmt.order_by(Dependency.target, Document.path, Dependency.source_symbol, Dependency.id)
        .limit(limit).offset(offset)
    ).all()
    return [
        {
            "source_document_id": edge.source_document_id,
            "source_file": path,
            "source_symbol": edge.source_symbol,
            "target": edge.target,
            "relation_type": edge.relation_type,
        }
        for edge, path in rows
    ]


def _dependency_tokens(value: str) -> set[str]:
    """Return likely symbol/module names from imports and type references."""
    candidates = {value.strip().casefold()}
    candidates.update(token.casefold() for token in re.findall(r"[A-Za-z_$][\w$]*", value))
    for dotted in re.findall(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+", value):
        candidates.add(dotted.casefold())
        candidates.add(dotted.rsplit(".", 1)[-1].casefold())
    return {candidate for candidate in candidates if candidate}


def analyze_impact(db: Session, project_id: str, target: str, limit: int = MAX_IMPACT_FILES):
    """Find direct and transitive files that depend on a repository path or symbol."""
    query = target.strip().replace("\\", "/").casefold()
    if not query:
        return None

    documents = db.execute(
        select(Document.id, Document.path).where(Document.project_id == project_id)
    ).all()
    chunk_rows = db.execute(
        select(Chunk.document_id, Chunk.symbol).where(Chunk.project_id == project_id)
        .limit(MAX_GRAPH_ROWS + 1)
    ).all()
    dependency_rows = db.execute(
        select(
            Dependency.source_document_id, Dependency.source_symbol,
            Dependency.target, Dependency.relation_type,
        ).where(Dependency.project_id == project_id)
        .limit(MAX_GRAPH_ROWS + 1)
    ).all()
    graph_truncated = len(chunk_rows) > MAX_GRAPH_ROWS or len(dependency_rows) > MAX_GRAPH_ROWS
    chunk_rows = chunk_rows[:MAX_GRAPH_ROWS]
    dependency_rows = dependency_rows[:MAX_GRAPH_ROWS]

    doc_by_id = {document_id: path for document_id, path in documents}
    symbol_providers: dict[str, set[str]] = {}
    for document_id, symbol in chunk_rows:
        if document_id not in doc_by_id or not symbol:
            continue
        base_symbol = re.sub(r"\s+\[part \d+\]$", "", symbol, flags=re.IGNORECASE)
        symbol_providers.setdefault(base_symbol.casefold(), set()).add(document_id)

    roots: set[str] = set()
    for document_id, doc_path in documents:
        path = doc_path.replace("\\", "/").casefold()
        stem = PurePosixPath(path).stem
        if path == query or stem == query or path.rsplit("/", 1)[-1] == query:
            roots.add(document_id)
    for key, provider_ids in symbol_providers.items():
        if key == query or key.rsplit(".", 1)[-1] == query.rsplit(".", 1)[-1]:
            roots.update(provider_ids)
    if not roots:
        return None

    file_providers: dict[str, set[str]] = {}
    for document_id, doc_path in documents:
        posix_path = doc_path.replace("\\", "/")
        path = PurePosixPath(posix_path)
        keys = {path.stem.casefold(), path.as_posix().casefold()}
        if path.suffix:
            keys.add(path.with_suffix("").as_posix().casefold())
        for key in keys:
            if key:
                file_providers.setdefault(key, set()).add(document_id)

    # Build provider -> consumer edges. Only extracted imports/type references
    # contribute; arbitrary mentions in comments or strings do not.
    reverse_edges: dict[str, list[tuple[str, str]]] = {}
    for source_document_id, source_symbol, target, relation_type in dependency_rows:
        if source_document_id not in doc_by_id:
            continue
        candidates = _dependency_tokens(target)
        providers: set[str] = set()
        for candidate in candidates:
            providers.update(symbol_providers.get(candidate, set()))
            providers.update(file_providers.get(candidate, set()))
        for provider_id in providers - {source_document_id}:
            reason = f"{relation_type}: {target}"
            if source_symbol:
                reason = f"{source_symbol} — {reason}"
            reverse_edges.setdefault(provider_id, []).append((source_document_id, reason))

    root_paths = {doc_by_id[root] for root in roots}
    queue = deque((root, 0) for root in sorted(roots))
    visited_depth = {root: 0 for root in roots}
    affected: dict[str, dict] = {}
    truncated = False
    while queue:
        provider_id, depth = queue.popleft()
        for consumer_id, reason in reverse_edges.get(provider_id, []):
            if consumer_id in roots:
                continue
            consumer_path = doc_by_id[consumer_id]
            next_depth = depth + 1
            row = affected.setdefault(consumer_id, {"file": consumer_path, "depth": next_depth, "reasons": []})
            row["depth"] = min(row["depth"], next_depth)
            if reason not in row["reasons"]:
                row["reasons"].append(reason)
            if next_depth < visited_depth.get(consumer_id, MAX_IMPACT_FILES + 1):
                visited_depth[consumer_id] = next_depth
                queue.append((consumer_id, next_depth))
            if len(affected) >= limit:
                truncated = bool(queue)
                queue.clear()
                break

    results = sorted(affected.values(), key=lambda row: (row["depth"], row["file"]))
    return {"target": target.strip(), "root_files": sorted(root_paths), "affected_files": results, "truncated": truncated or graph_truncated}
