from datetime import datetime
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.db.session import get_db
from app.models.models import GeneratedDocument, Project, ProjectAnalysis, User
from app.services.llm import GeminiAPIError, GeminiConnectionError, GeminiTimeoutError, answer
from app.tasks.celery_app import analyze_project, generate_project_documentation

router = APIRouter(prefix="/api/projects/{project_id}")


def _owned(db: Session, user: User, project_id: str) -> Project:
    project = db.scalar(select(Project).where(Project.id == project_id, Project.owner_id == user.id))
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


def _analysis(db: Session, project: Project):
    return db.scalar(select(ProjectAnalysis).where(
        ProjectAnalysis.project_id == project.id,
        ProjectAnalysis.index_revision == project.index_revision,
    ))


def _analysis_payload(project: Project, row: ProjectAnalysis | None):
    return {
        "project_id": project.id,
        "index_revision": project.index_revision,
        "commit_sha": project.repository_commit_sha,
        "status": row.status if row else ("NOT_INDEXED" if project.index_revision == 0 else "NOT_RUN"),
        "error": row.error if row else None,
        "health": row.health if row and row.status == "COMPLETED" else None,
        "findings": row.findings if row and row.status == "COMPLETED" else [],
        "documentation_status": row.documentation_status if row else "NOT_STARTED",
    }


@router.get("/analysis")
def get_analysis(project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    project = _owned(db, user, project_id)
    return _analysis_payload(project, _analysis(db, project))


@router.post("/analysis/scan")
def request_analysis(project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    project = _owned(db, user, project_id)
    if project.index_revision == 0:
        raise HTTPException(409, "Index a repository before running code analysis.")
    row = _analysis(db, project)
    if row is None:
        row = ProjectAnalysis(project_id=project_id, index_revision=project.index_revision, status="QUEUED")
        db.add(row)
    elif row.status in {"QUEUED", "RUNNING"}:
        return _analysis_payload(project, row)
    else:
        row.status = "QUEUED"
        row.error = None
    row.updated_at = datetime.utcnow()
    db.commit()
    try:
        analyze_project.delay(project_id, project.index_revision)
    except Exception:
        row.status = "FAILED"
        row.error = "Analysis could not be queued. Check Redis and worker availability, then retry."
        db.commit()
        raise HTTPException(503, row.error) from None
    return _analysis_payload(project, row)


@router.post("/analysis/explain/{finding_id}")
def explain_finding(project_id: str, finding_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    project = _owned(db, user, project_id)
    row = _analysis(db, project)
    if not row or row.status != "COMPLETED":
        raise HTTPException(409, "Run analysis for the current index before requesting an explanation.")
    finding = next((item for item in row.findings if item.get("id") == finding_id), None)
    if finding is None:
        raise HTTPException(404, "Finding not found for the current index.")
    # Only the selected, redacted static-rule excerpt is sent, and only after an
    # explicit user request. Repository text is untrusted prompt data.
    evidence = [{
        "file": finding["path"],
        "start_line": finding["start_line"],
        "end_line": finding["end_line"],
        "symbol": finding["title"],
        "content": finding["evidence"][:1500],
        "retrieval_score": 1.0,
    }]
    question = (
        f"Explain this static rule match {finding['rule_id']} ({finding['title']}). "
        f"Explain what is directly visible and suggest cautious next steps. You may include a separate section "
        f"named 'Unconfirmed hypotheses', clearly labeling each item speculative and not a confirmed vulnerability. "
        f"Do not call it an exploitable vulnerability unless this exact excerpt proves that. "
        f"Static description: {finding['description']} Suggested remediation: {finding['remediation']}"
    )
    try:
        result = answer(question, evidence)
    except GeminiTimeoutError:
        raise HTTPException(504, "Gemini timed out while explaining the finding.") from None
    except GeminiConnectionError:
        raise HTTPException(503, "Gemini could not be reached while explaining the finding.") from None
    except GeminiAPIError as exc:
        status = 503 if exc.status_code == 429 or exc.status_code >= 500 else 502
        raise HTTPException(status, "Gemini rejected the explanation request. Check provider availability and configuration.") from None
    except Exception:
        raise HTTPException(503, "The explanation service failed. Check API and Gemini service logs, then retry.") from None
    citations = [{"file": finding["path"], "start_line": finding["start_line"], "end_line": finding["end_line"], "symbol": finding["title"]}] if result.evidence_sufficient else []
    return {"answer": result.answer, "answer_mode": result.mode, "citations": citations, "finding_origin": "static_rule", "hypotheses_are_unconfirmed": True}


@router.get("/docs/generated")
def list_generated_docs(project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    project = _owned(db, user, project_id)
    analysis = _analysis(db, project)
    docs = db.scalars(select(GeneratedDocument).where(
        GeneratedDocument.project_id == project_id,
        GeneratedDocument.index_revision == project.index_revision,
    ).order_by(GeneratedDocument.kind, GeneratedDocument.scope_key)).all()
    return {
        "project_id": project_id,
        "index_revision": project.index_revision,
        "status": analysis.documentation_status if analysis else "NOT_STARTED",
        "documents": [{"id": doc.id, "kind": doc.kind, "title": doc.title, "scope_key": doc.scope_key, "source_refs": doc.source_refs} for doc in docs],
    }


@router.post("/docs/generate")
def request_documentation(project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    project = _owned(db, user, project_id)
    if project.index_revision == 0:
        raise HTTPException(409, "Index a repository before generating documentation.")
    row = _analysis(db, project)
    if row is None:
        row = ProjectAnalysis(project_id=project_id, index_revision=project.index_revision, status="NOT_RUN")
        db.add(row)
        db.flush()
    if row.documentation_status in {"QUEUED", "RUNNING"}:
        return {"status": row.documentation_status, "index_revision": project.index_revision}
    row.documentation_status = "QUEUED"
    row.updated_at = datetime.utcnow()
    db.commit()
    try:
        generate_project_documentation.delay(project_id, project.index_revision)
    except Exception:
        row.documentation_status = "FAILED"
        db.commit()
        raise HTTPException(503, "Documentation generation could not be queued. Check Redis and worker availability.") from None
    return {"status": "QUEUED", "index_revision": project.index_revision}


@router.get("/docs/generated/{document_id}/export")
def export_documentation(project_id: str, document_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    project = _owned(db, user, project_id)
    doc = db.scalar(select(GeneratedDocument).where(GeneratedDocument.project_id == project_id, GeneratedDocument.id == document_id))
    if doc is None:
        raise HTTPException(404, "Generated document not found")
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{doc.kind}-{doc.scope_key.rsplit('/', 1)[-1] if doc.scope_key else 'project'}.md")
    return Response(doc.markdown, media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/docs/generated/{document_id}")
def get_generated_document(project_id: str, document_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _owned(db, user, project_id)
    doc = db.scalar(select(GeneratedDocument).where(GeneratedDocument.project_id == project_id, GeneratedDocument.id == document_id))
    if doc is None:
        raise HTTPException(404, "Generated document not found")
    return {"id": doc.id, "kind": doc.kind, "title": doc.title, "scope_key": doc.scope_key, "index_revision": doc.index_revision, "markdown": doc.markdown, "source_refs": doc.source_refs}
