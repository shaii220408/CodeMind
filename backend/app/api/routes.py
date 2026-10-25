import os
import posixpath
import re
import shutil
import uuid
from pathlib import PurePosixPath

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.models import ChatMessage, Chunk, Dependency, Document, GraphEdge, GraphNode, IndexJob, Project, User
from app.schemas.schemas import *
from app.services.llm import (
    GeminiAPIError,
    GeminiConnectionError,
    GeminiTimeoutError,
    MIN_RELEVANCE_SCORE,
    answer,
)
from app.services.audit import audit_event
from app.retrieval.hybrid import retrieve
from app.tasks.celery_app import index_project, sync_github_project
from app.services.github import GitHubImportError, normalize_public_github_url, validate_branch

router = APIRouter(prefix="/api")


def llm_provider_http_error(exc: Exception) -> HTTPException:
    import httpx

    if isinstance(exc, (GeminiTimeoutError, httpx.TimeoutException)):
        return HTTPException(504, "Gemini timed out. Retry the request or check provider availability.")
    if isinstance(exc, (GeminiConnectionError, httpx.RequestError)):
        return HTTPException(503, "Gemini could not be reached. Check network access to generativelanguage.googleapis.com.")
    if isinstance(exc, GeminiAPIError):
        if exc.status_code in {401, 403}:
            return HTTPException(502, "Gemini rejected the credentials. Verify backend GEMINI_API_KEY configuration and key restrictions.")
        if exc.status_code == 429:
            return HTTPException(503, "Gemini rate limited this request. Check provider quota and retry shortly.")
        if exc.status_code in {408, 504}:
            return HTTPException(504, "Gemini did not finish before the request deadline. Retry later or check provider availability.")
        if exc.status_code >= 500:
            return HTTPException(503, "Gemini returned a server error. Retry shortly.")
        return HTTPException(502, "Gemini rejected the request. Verify GEMINI_MODEL and Gemini API access.")
    raise TypeError("Unsupported Gemini provider exception")


def owned_project(db: Session, user: User, project_id: str) -> Project:
    project = db.scalar(
        select(Project).where(Project.id == project_id, Project.owner_id == user.id)
    )
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


def map_index_task_state(state: str) -> str:
    """Normalize Celery states to the status vocabulary used by the UI."""
    return {
        "PENDING": "QUEUED",
        "STARTED": "PROCESSING",
        "RETRY": "PROCESSING",
        "SUCCESS": "COMPLETED",
        "FAILURE": "FAILED",
        "REVOKED": "FAILED",
    }.get(state, state)


@router.post("/projects", response_model=ProjectOut)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    repository_url = payload.repository_url
    if repository_url:
        try:
            repository_url = normalize_public_github_url(repository_url)
        except GitHubImportError as exc:
            raise HTTPException(exc.status_code, str(exc)) from None
    project = Project(
        owner_id=user.id,
        name=payload.name.strip(),
        repository_url=repository_url,
        sync_status="READY" if repository_url else "NOT_CONFIGURED",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    audit_event("project.created", user.id, project.id)
    return project


@router.get("/projects", response_model=list[ProjectOut])
def projects(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return db.scalars(
        select(Project)
        .where(Project.owner_id == user.id)
        .order_by(Project.created_at.desc())
    ).all()


@router.delete("/projects/{project_id}")
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project = owned_project(db, user, project_id)
    jobs = db.scalars(select(IndexJob).where(IndexJob.project_id == project_id)).all()
    for job in jobs:
        result = index_project.AsyncResult(job.celery_task_id)
        if result.state in {"PENDING", "STARTED", "RETRY"}:
            result.revoke(terminate=True)

    db.delete(project)
    db.commit()
    shutil.rmtree(os.path.join(settings.upload_dir, project_id), ignore_errors=True)
    audit_event("project.deleted", user.id, project_id)
    return {"deleted": True, "project_id": project_id}


@router.post("/projects/{project_id}/upload")
def upload(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(db, user, project_id)
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "Only ZIP repositories are supported")
    project_upload_dir = os.path.join(settings.upload_dir, project_id)
    os.makedirs(project_upload_dir, exist_ok=True)
    path = os.path.join(project_upload_dir, f"{uuid.uuid4()}.zip")
    size = 0
    with open(path, "wb") as out:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_upload_mb * 1024 * 1024:
                os.unlink(path)
                raise HTTPException(413, "Upload too large")
            out.write(chunk)
    project = db.scalar(select(Project).where(
        Project.id == project_id,
        Project.owner_id == user.id,
    ).with_for_update())
    if project is None:
        os.unlink(path)
        raise HTTPException(404, "Project not found")
    project.index_generation += 1
    if project.repository_url:
        project.sync_status = "OUT_OF_SYNC"
    generation = project.index_generation
    # Commit the snapshot generation before dispatch so the worker can reject an
    # older queued upload even if it races with a newer request.
    db.commit()
    try:
        task = index_project.delay(project_id, path, generation)
    except Exception as exc:
        # A broker outage must not leave an orphaned upload that looks queued.
        try:
            os.unlink(path)
            os.rmdir(project_upload_dir)
        except OSError:
            pass
        raise HTTPException(503, "Indexing queue is unavailable. Check Redis and retry the upload.") from exc
    job = IndexJob(project_id=project_id, celery_task_id=task.id, status="QUEUED")
    db.add(job)
    db.commit()
    audit_event("project.index_queued", user.id, project_id, job_id=job.id)
    return {"job_id": job.id, "task_id": task.id, "status": "QUEUED"}


@router.post("/projects/{project_id}/sync")
def sync_repository(
    project_id: str,
    branch: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project = owned_project(db, user, project_id)
    if not project.repository_url:
        raise HTTPException(400, "Add a public GitHub repository URL to this project before syncing.")
    try:
        repository_url = normalize_public_github_url(project.repository_url)
        selected_branch = validate_branch(branch or project.repository_branch)
    except GitHubImportError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    project.repository_url = repository_url
    project.repository_branch = selected_branch
    project.sync_status = "SYNCING"
    project.index_generation += 1
    generation = project.index_generation
    db.commit()
    try:
        task = sync_github_project.delay(project_id, selected_branch, generation)
    except Exception as exc:
        project.sync_status = "SYNC_FAILED"
        db.commit()
        raise HTTPException(503, "Repository sync could not be queued. Check Redis and retry.") from exc
    job = IndexJob(project_id=project_id, celery_task_id=task.id, status="QUEUED")
    db.add(job)
    db.commit()
    audit_event("repository.sync_queued", user.id, project_id, job_id=job.id, branch=selected_branch)
    return {"job_id": job.id, "task_id": task.id, "status": "QUEUED", "branch": selected_branch}


@router.post("/projects/{project_id}/index")
def index_without_upload(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(db, user, project_id)
    raise HTTPException(400, "Upload a repository ZIP first using /upload")


@router.get("/projects/{project_id}/status", response_model=StatusOut)
def status(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(db, user, project_id)
    job = db.scalars(
        select(IndexJob)
        .where(IndexJob.project_id == project_id)
        .order_by(IndexJob.created_at.desc())
    ).first()
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not job:
        return StatusOut(project_id=project_id, status="NOT_STARTED", sync_status=project.sync_status,
                         repository_branch=project.repository_branch, repository_commit_sha=project.repository_commit_sha,
                         index_revision=project.index_revision)
    result = index_project.AsyncResult(job.celery_task_id)
    state = result.state
    job.status = map_index_task_state(state)
    job.error = "Indexing failed; inspect service logs." if state == "FAILURE" else None
    db.commit()
    return StatusOut(project_id=project_id, status=job.status, error=job.error, sync_status=project.sync_status,
                     repository_branch=project.repository_branch, repository_commit_sha=project.repository_commit_sha,
                     index_revision=project.index_revision)


@router.post("/ask", response_model=AskResponse)
def ask(
    payload: AskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(db, user, payload.project_id)
    recent = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.project_id == payload.project_id, ChatMessage.user_id == user.id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(6)
    ).all()
    conversation = [
        {"question": item.question, "answer": item.answer}
        for item in reversed(recent)
    ]
    retrieval_question = payload.question
    if recent and len(payload.question.split()) <= 8:
        # Short follow-ups often rely on the previous topic to retrieve the right code.
        retrieval_question = f"{recent[0].question}\n{payload.question}"
    sources = retrieve(db, payload.project_id, retrieval_question, payload.top_k)
    try:
        result = answer(payload.question, sources, conversation)
    except Exception as exc:
        # Provider failures stay explicit and never become successful fallbacks.
        import httpx
        if isinstance(exc, (GeminiTimeoutError, GeminiConnectionError, GeminiAPIError, httpx.TimeoutException, httpx.RequestError)):
            raise llm_provider_http_error(exc) from exc
        raise
    text = result.answer
    audit_event("repository.question_asked", user.id, payload.project_id, result_count=len(sources), answer_mode=result.mode)
    citations = []
    if result.evidence_sufficient:
        seen = set()
        for source in sources:
            key = (source["file"], source["start_line"], source["end_line"], source["symbol"])
            if key not in seen and source.get("retrieval_score", 1) >= MIN_RELEVANCE_SCORE:
                seen.add(key)
                citations.append(Citation(file=key[0], start_line=key[1], end_line=key[2], symbol=key[3]))
    citation_keys = {(citation.file, citation.start_line, citation.end_line) for citation in citations}
    citation_sources = [
        {key: source[key] for key in ("id", "file", "symbol", "start_line", "end_line", "content", "confidence") if key in source}
        for source in sources
        if (source["file"], source["start_line"], source["end_line"]) in citation_keys
    ] if result.evidence_sufficient else []
    message = ChatMessage(
        project_id=payload.project_id,
        user_id=user.id,
        question=payload.question,
        answer=text,
        answer_mode=result.mode,
        citations=[citation.model_dump() for citation in citations],
        retrieved_sources=citation_sources,
    )
    db.add(message)
    db.commit()
    return AskResponse(answer=text, answer_mode=result.mode, evidence_sufficient=result.evidence_sufficient, citations=citations, retrieved_sources=sources if result.evidence_sufficient else [])


@router.get("/projects/{project_id}/files")
def files(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(db, user, project_id)
    docs = db.scalars(
        select(Document).where(Document.project_id == project_id).order_by(Document.path)
    ).all()
    return [
        {"id": doc.id, "path": doc.path, "language": doc.language, "content_hash": doc.content_hash}
        for doc in docs
    ]


@router.get("/projects/{project_id}/source")
def source_code(
    project_id: str,
    path: str,
    start_line: int = Query(1, ge=1),
    end_line: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(db, user, project_id)
    normalized_path = path.replace("\\", "/").strip("/")
    document = db.scalar(select(Document).where(
        Document.project_id == project_id,
        Document.path == normalized_path,
    ))
    if document is None:
        raise HTTPException(404, "Indexed source file not found")
    if end_line < start_line or end_line - start_line > 499:
        raise HTTPException(422, "Source range must be ordered and no wider than 500 lines")
    lines = document.content.splitlines()
    if start_line > max(1, len(lines)):
        raise HTTPException(404, "Source line is outside the indexed file")
    actual_end = min(end_line, max(1, len(lines)))
    return {
        "path": document.path,
        "start_line": start_line,
        "end_line": actual_end,
        "content": "\n".join(lines[start_line - 1:actual_end]),
    }


@router.get("/projects/{project_id}/dependencies")
def dependencies(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(db, user, project_id)
    rows = db.scalars(select(Dependency).where(Dependency.project_id == project_id)).all()
    return [
        {
            "source_document_id": row.source_document_id,
            "source_symbol": row.source_symbol,
            "target": row.target,
            "relation_type": row.relation_type,
        }
        for row in rows
    ]


@router.get("/projects/{project_id}/overview")
def overview(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(db, user, project_id)
    docs = db.scalars(select(Document).where(Document.project_id == project_id)).all()
    chunks = db.scalar(
        select(func.count(Chunk.id)).where(Chunk.project_id == project_id)
    ) or 0
    languages = {}
    for doc in docs:
        languages[doc.language] = languages.get(doc.language, 0) + 1
    return {
        "project_id": project_id,
        "file_count": len(docs),
        "chunk_count": chunks,
        "languages": languages,
    }

@router.get("/projects/{project_id}/dependencies/search")
def search_dependencies(
    project_id: str,
    q: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(db, user, project_id)
    needle = q.strip().lower()
    if not needle:
        raise HTTPException(422, "Search query cannot be empty")
    rows = db.scalars(select(Dependency).where(Dependency.project_id == project_id)).all()
    docs = {
        doc.id: doc.path
        for doc in db.scalars(select(Document).where(Document.project_id == project_id)).all()
    }
    matches = [
        {
            "source_file": docs.get(row.source_document_id),
            "source_symbol": row.source_symbol,
            "target": row.target,
            "relation_type": row.relation_type,
        }
        for row in rows
        if needle in row.target.lower()
        or needle in (row.source_symbol or "").lower()
        or needle in docs.get(row.source_document_id, "").lower()
    ]
    return {"query": q, "matches": matches}


@router.get("/projects/{project_id}/impact")
def dependency_impact(
    project_id: str,
    path: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(db, user, project_id)
    target_path = path.replace("\\", "/").strip("/")
    docs = db.scalars(select(Document).where(Document.project_id == project_id)).all()
    by_id = {doc.id: doc.path for doc in docs}
    documents_by_path = {doc.path: doc for doc in docs}
    target_doc = next((doc for doc in docs if doc.path == target_path), None)
    if target_doc is None:
        raise HTTPException(404, "Indexed file not found")

    # Import edges point from the importing file to its raw import string. Resolve
    # those strings against indexed paths, then walk reverse edges to find callers.
    rows = db.scalars(select(Dependency).where(Dependency.project_id == project_id)).all()
    reverse: dict[str, set[str]] = {doc.path: set() for doc in docs}

    def locally_imported_paths(source_path: str, statement: str) -> set[str]:
        """Resolve a stored import statement only when it identifies one local file."""
        value = statement.strip().rstrip(";")
        modules: list[tuple[str, bool]] = []
        python_from = re.match(r"^from\s+([.\w]+)\s+import\s+", value)
        java_import = re.match(r"^import\s+(?:static\s+)?([\w.]+);$", statement.strip())
        js_import = re.search(r"\bfrom\s+['\"]([^'\"]+)['\"]", value) or re.match(r"^import\s*['\"]([^'\"]+)['\"]", value)
        if python_from:
            module = python_from.group(1)
            if module.startswith("."):
                parts = list(PurePosixPath(source_path).with_suffix("").parts)
                package = parts if parts[-1:] == ["__init__"] else parts[:-1]
                dots = len(module) - len(module.lstrip("."))
                base = package[:max(0, len(package) - dots + 1)]
                suffix = [part for part in module.lstrip(".").split(".") if part]
                modules.append(("/".join(base + suffix), True))
            else:
                modules.append((module.replace(".", "/"), False))
        elif java_import:
            modules.append((java_import.group(1).replace(".", "/"), False))
        elif js_import:
            if js_import.group(1).startswith("."):
                joined = posixpath.normpath(posixpath.join(PurePosixPath(source_path).parent.as_posix(), js_import.group(1)))
                if PurePosixPath(joined).suffix.lower() in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
                    joined = PurePosixPath(joined).with_suffix("").as_posix()
                modules.append((joined, True))
        elif value.startswith("import "):
            module = value.removeprefix("import ").split(",", 1)[0].split(" as ", 1)[0].strip()
            if module:
                modules.append((module.replace(".", "/"), False))

        resolved: set[str] = set()
        for module_path, exact in modules:
            matches = set()
            for candidate in documents_by_path:
                stem = candidate.rsplit(".", 1)[0] if "." in candidate else candidate
                variants = {stem}
                if not exact:
                    variants |= {stem.removeprefix("./")}
                if module_path in variants:
                    matches.add(candidate)
                elif not exact and stem.endswith("/" + module_path):
                    matches.add(candidate)
                elif module_path and exact and stem == module_path + "/index":
                    matches.add(candidate)
            # A short module name can match nested files. Do not infer if it is
            # ambiguous; an exact indexed path remains usable even in that case.
            exact_matches = {candidate for candidate in matches if (candidate.rsplit(".", 1)[0] if "." in candidate else candidate) == module_path}
            if exact_matches:
                resolved.update(exact_matches)
            elif len(matches) == 1:
                resolved.update(matches)
        return resolved

    for row in rows:
        source = by_id.get(row.source_document_id)
        if not source:
            continue
        for candidate_path in locally_imported_paths(source, row.target):
            reverse.setdefault(candidate_path, set()).add(source)

    depths: dict[str, int] = {}
    frontier = [(target_doc.path, 0)]
    visited = {target_doc.path}
    while frontier:
        current, depth = frontier.pop(0)
        for caller in reverse.get(current, ()):
            if caller not in visited:
                visited.add(caller)
                depths[caller] = depth + 1
                frontier.append((caller, depth + 1))
    return {
        "target": target_doc.path,
        "impacted_files": [
            {"path": impacted, "depth": depth}
            for impacted, depth in sorted(depths.items(), key=lambda item: (item[1], item[0]))
        ],
    }


@router.get("/projects/{project_id}/graph")
def knowledge_graph(
    project_id: str,
    search: str | None = None,
    limit: int = Query(500, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(db, user, project_id)
    query = select(GraphNode).where(GraphNode.project_id == project_id)
    if search and search.strip():
        needle = f"%{search.strip()}%"
        query = query.where(
            GraphNode.name.ilike(needle)
            | GraphNode.qualified_name.ilike(needle)
            | GraphNode.source_path.ilike(needle)
        )
    nodes = db.scalars(query.order_by(GraphNode.source_path, GraphNode.start_line).limit(limit)).all()
    node_ids = [node.id for node in nodes]
    edges = []
    if node_ids:
        edges = db.scalars(
            select(GraphEdge)
            .where(GraphEdge.project_id == project_id, GraphEdge.source_node_id.in_(node_ids))
            .order_by(GraphEdge.source_path, GraphEdge.start_line)
            .limit(limit * 4)
        ).all()
    graph_languages = db.scalars(
        select(Document.language)
        .join(GraphNode, GraphNode.document_id == Document.id)
        .where(GraphNode.project_id == project_id)
        .distinct()
        .order_by(Document.language)
    ).all()
    return {
        "nodes": [{
            "id": node.id, "kind": node.kind, "name": node.name,
            "qualified_name": node.qualified_name, "path": node.source_path,
            "start_line": node.start_line, "end_line": node.end_line,
        } for node in nodes],
        "edges": [{
            "id": edge.id, "source_node_id": edge.source_node_id,
            "target_node_id": edge.target_node_id, "relation": edge.relation,
            "target_name": edge.target_name, "resolution": edge.resolution,
            "path": edge.source_path, "start_line": edge.start_line,
            "end_line": edge.end_line,
        } for edge in edges],
        "truncated": len(nodes) == limit or len(edges) == limit * 4,
        "supported_languages": graph_languages,
    }


@router.get("/projects/{project_id}/graph/impact")
def graph_impact(
    project_id: str,
    node_id: str | None = None,
    path: str | None = None,
    max_depth: int = Query(1, ge=1, le=5),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(db, user, project_id)
    if bool(node_id) == bool(path):
        raise HTTPException(422, "Provide exactly one of node_id or path")
    if node_id:
        selected = db.scalar(select(GraphNode).where(
            GraphNode.project_id == project_id,
            GraphNode.id == node_id,
        ))
        if selected is None:
            raise HTTPException(404, "Graph node not found")
        if selected.kind == "file":
            target_ids = [selected.id, *db.scalars(select(GraphNode.id).where(
                GraphNode.project_id == project_id,
                GraphNode.source_path == selected.source_path,
                GraphNode.kind.in_(["module", "function", "method"]),
            )).all()]
        elif selected.kind in {"module", "class"}:
            target_ids = [selected.id, *db.scalars(select(GraphNode.id).where(
                GraphNode.project_id == project_id,
                GraphNode.source_path == selected.source_path,
                GraphNode.kind.in_(["function", "method"]),
                GraphNode.qualified_name.startswith(selected.qualified_name + "."),
            )).all()]
        else:
            target_ids = [selected.id]
    else:
        selected = db.scalar(select(GraphNode).where(
            GraphNode.project_id == project_id,
            GraphNode.source_path == path.replace("\\", "/"),
            GraphNode.kind == "file",
        ))
        if selected is None:
            raise HTTPException(404, "Graph file not found")
        target_ids = [selected.id, *db.scalars(select(GraphNode.id).where(
            GraphNode.project_id == project_id,
            GraphNode.source_path == selected.source_path,
            GraphNode.kind.in_(["module", "function", "method"]),
        )).all()]

    # Follow reverse call/import links one bounded layer at a time. Only graph
    # edges with resolved target IDs participate; inferred links remain marked
    # as such in the response, and unresolved edges are excluded.
    relationships = []
    frontier = set(target_ids)
    seen = set(target_ids)
    for depth in range(1, max_depth + 1):
        if not frontier:
            break
        edges = db.scalars(select(GraphEdge).where(
            GraphEdge.project_id == project_id,
            GraphEdge.relation.in_(["calls", "import"]),
            GraphEdge.target_node_id.in_(frontier),
        ).order_by(GraphEdge.source_path, GraphEdge.start_line)).all()
        new_sources = {edge.source_node_id for edge in edges if edge.source_node_id not in seen}
        if depth == 1:
            # Preserve all direct edges, including a direct self-reference.
            relationships.extend((edge, depth) for edge in edges)
        else:
            relationships.extend(
                (edge, depth) for edge in edges
                if edge.source_node_id not in seen
            )
        seen.update(new_sources)
        frontier = new_sources

    direct_relationships = [edge for edge, depth in relationships if depth == 1]
    callers = [edge for edge in direct_relationships if edge.relation == "calls"]
    source_ids = {edge.source_node_id for edge, _depth in relationships}
    sources = db.scalars(select(GraphNode).where(
        GraphNode.project_id == project_id,
        GraphNode.id.in_(source_ids),
    )).all() if source_ids else []
    by_id = {node.id: node for node in sources}
    def describe(edge, depth=None):
        source_node = by_id.get(edge.source_node_id)
        result = {
            "id": source_node.id,
            "kind": source_node.kind,
            "qualified_name": source_node.qualified_name,
            "path": edge.source_path,
            "start_line": edge.start_line,
            "end_line": edge.end_line,
            "relation": edge.relation,
            "resolution": edge.resolution,
            "target_name": edge.target_name,
        }
        if depth is not None:
            result["depth"] = depth
        return result

    return {
        "target": {
            "id": selected.id, "kind": selected.kind,
            "qualified_name": selected.qualified_name,
            "path": selected.source_path,
            "start_line": selected.start_line, "end_line": selected.end_line,
        },
        "scope": "direct_callers" if max_depth == 1 else "bounded_transitive_callers",
        "max_depth": max_depth,
        "completeness": "partial",
        "note": "Only uniquely resolved static calls and imports in the indexed graph are followed. Inferred links are not runtime-verified; unresolved calls, dynamic dispatch, reflection, and external dependencies are omitted.",
        "direct_dependents": [describe(edge) for edge in direct_relationships if edge.source_node_id in by_id],
        "callers": [describe(edge) for edge in callers if edge.source_node_id in by_id],
        "transitive_dependents": [
            describe(edge, depth)
            for edge, depth in relationships
            if depth > 1 and edge.source_node_id in by_id
        ],
    }





@router.get("/projects/{project_id}/history")
def chat_history(
    project_id: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(db, user, project_id)
    limit = max(1, min(limit, 100))
    messages = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.project_id == project_id, ChatMessage.user_id == user.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": message.id,
            "question": message.question,
            "answer": message.answer,
            "answer_mode": message.answer_mode,
            "citations": message.citations,
            "retrieved_sources": message.retrieved_sources,
            "created_at": message.created_at,
        }
        for message in reversed(messages)
    ]
