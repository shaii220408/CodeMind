import os, uuid, zipfile
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.models import Project, Document, Chunk, Dependency, IndexJob
from app.schemas.schemas import (
    AskRequest, AskResponse, Citation, DependencyOut, FileDetailOut, FileOut, ImpactOut,
    IndexAccepted, OverviewOut, ProjectCreate, ProjectOut, StatusOut,
)
from app.tasks.celery_app import index_project
from app.retrieval.hybrid import retrieve
from app.services.llm import answer
from app.services.rate_limit import limit_ask_requests, limit_upload_requests, limit_dependency_requests
from app.services.dependencies import analyze_impact, search_dependencies
from app.core.config import settings

router=APIRouter(prefix="/api")

def ensure_project_idle(db:Session,project_id:str):
    active=db.scalars(select(IndexJob).where(
        IndexJob.project_id==project_id,
        IndexJob.status.in_(["QUEUED","PROCESSING"]),
    ).limit(1)).first()
    if active:
        raise HTTPException(409,"An indexing job is already active for this project")

def db_dep():
    db=SessionLocal()
    try: yield db
    finally: db.close()

@router.post("/projects",response_model=ProjectOut)
def create_project(payload:ProjectCreate,db:Session=Depends(db_dep)):
    p=Project(name=payload.name,repository_url=payload.repository_url); db.add(p); db.commit(); db.refresh(p); return p

@router.get("/projects",response_model=list[ProjectOut])
def projects(db:Session=Depends(db_dep)): return db.scalars(select(Project).order_by(Project.created_at.desc())).all()

@router.post("/projects/{project_id}/upload",response_model=IndexAccepted,dependencies=[Depends(limit_upload_requests)])
def upload(project_id:str,file:UploadFile=File(...),db:Session=Depends(db_dep)):
    p=db.get(Project,project_id)
    if not p: raise HTTPException(404,"Project not found")
    ensure_project_idle(db,project_id)
    if not file.filename or not file.filename.lower().endswith(".zip"): raise HTTPException(400,"Only ZIP repositories are supported")
    os.makedirs(settings.upload_dir,exist_ok=True)
    path=os.path.join(settings.upload_dir,f"{uuid.uuid4()}.zip")
    size=0
    try:
        with open(path,"wb") as out:
            while chunk:=file.file.read(1024*1024):
                size+=len(chunk)
                if size>settings.max_upload_mb*1024*1024:
                    raise HTTPException(413,"Upload too large")
                out.write(chunk)
        if not zipfile.is_zipfile(path):
            raise HTTPException(400,"Uploaded file is not a valid ZIP archive")
        task_id=str(uuid.uuid4())
        job=IndexJob(project_id=project_id,celery_task_id=task_id,status="QUEUED")
        db.add(job)
        db.commit()
        try:
            index_project.apply_async(args=[project_id,path],task_id=task_id)
        except Exception as exc:
            job.status="FAILED"
            job.error="Indexing queue is unavailable. Please retry the upload."
            db.commit()
            raise HTTPException(503,"Indexing service is temporarily unavailable") from exc
    except HTTPException:
        db.rollback()
        if os.path.exists(path): os.unlink(path)
        raise
    except Exception:
        db.rollback()
        if os.path.exists(path): os.unlink(path)
        raise
    return {"job_id":job.id,"task_id":task_id,"status":"QUEUED"}

@router.post("/projects/{project_id}/index",response_model=IndexAccepted,dependencies=[Depends(limit_upload_requests)])
def index_without_upload(project_id:str,db:Session=Depends(db_dep)):
    project=db.get(Project,project_id)
    if not project: raise HTTPException(404,"Project not found")
    ensure_project_idle(db,project_id)
    has_documents=db.scalar(select(Document.id).where(Document.project_id==project_id).limit(1))
    if not has_documents and not project.repository_url:
        raise HTTPException(409,"Add a supported repository URL or upload a ZIP before indexing")
    task_id=str(uuid.uuid4())
    job=IndexJob(project_id=project_id,celery_task_id=task_id,status="QUEUED")
    db.add(job)
    db.commit()
    try:
        source_url=project.repository_url if project.repository_url else None
        index_project.apply_async(args=[project_id,None,source_url],task_id=task_id)
    except Exception as exc:
        job.status="FAILED"
        job.error="Indexing queue is unavailable. Please retry."
        db.commit()
        raise HTTPException(503,"Indexing service is temporarily unavailable") from exc
    return {"job_id":job.id,"task_id":task_id,"status":"QUEUED"}

@router.get("/projects/{project_id}/status",response_model=StatusOut)
def status(project_id:str,db:Session=Depends(db_dep)):
    if not db.get(Project,project_id): raise HTTPException(404,"Project not found")
    job=db.scalars(select(IndexJob).where(IndexJob.project_id==project_id).order_by(IndexJob.created_at.desc())).first()
    if not job: return StatusOut(project_id=project_id,status="NOT_STARTED")
    return StatusOut(project_id=project_id,status=job.status,error=job.error)

@router.post("/ask",response_model=AskResponse,dependencies=[Depends(limit_ask_requests)])
def ask(payload:AskRequest,db:Session=Depends(db_dep)):
    if not db.get(Project,payload.project_id): raise HTTPException(404,"Project not found")
    sources=retrieve(db,payload.project_id,payload.question,payload.top_k)
    document_ids={s["document_id"] for s in sources}
    if document_ids:
        dependency_rows=db.scalars(select(Dependency).where(
            Dependency.project_id==payload.project_id,
            Dependency.source_document_id.in_(document_ids),
        )).all()
        by_document={}
        for dep in dependency_rows:
            outgoing=by_document.setdefault(dep.source_document_id,[])
            if len(outgoing)<20:
                outgoing.append({"target":dep.target,"relation_type":dep.relation_type})
        for source in sources:
            source["dependencies"]=by_document.get(source["document_id"],[])
        symbols={source["symbol"] for source in sources}
        if symbols:
            inbound=db.execute(
                select(Dependency.target,Document.path).join(
                    Document,Document.id==Dependency.source_document_id,
                ).where(
                    Dependency.project_id==payload.project_id,
                    Dependency.relation_type=="class_reference",
                    Dependency.target.in_(symbols),
                ).limit(100)
            ).all()
            for source in sources:
                source["dependencies"].extend(
                    {"target":symbol,"relation_type":"referenced_by","source_file":path}
                    for symbol,path in inbound if symbol==source["symbol"]
                )
    text=answer(payload.question,sources)
    citations=[Citation(file=s["file"],start_line=s["start_line"],end_line=s["end_line"],symbol=s["symbol"]) for s in sources]
    return AskResponse(answer=text,citations=citations,retrieved_sources=sources)

@router.get("/projects/{project_id}/files",response_model=list[FileOut])
def files(project_id:str,db:Session=Depends(db_dep)):
    if not db.get(Project,project_id): raise HTTPException(404,"Project not found")
    docs=db.scalars(select(Document).where(Document.project_id==project_id).order_by(Document.path)).all()
    return [{"id":d.id,"path":d.path,"language":d.language,"content_hash":d.content_hash} for d in docs]

@router.get("/projects/{project_id}/files/{document_id}",response_model=FileDetailOut)
def file_detail(project_id:str,document_id:str,db:Session=Depends(db_dep)):
    doc=db.scalars(select(Document).where(
        Document.id==document_id,Document.project_id==project_id,
    )).first()
    if not doc: raise HTTPException(404,"File not found in this project")
    chunks=db.scalars(select(Chunk).where(
        Chunk.document_id==doc.id,
    ).order_by(Chunk.start_line)).all()
    return {
        "id":doc.id,"path":doc.path,"language":doc.language,"content":doc.content,
        "chunks":[{"symbol":c.symbol,"symbol_type":c.symbol_type,
                   "start_line":c.start_line,"end_line":c.end_line} for c in chunks],
    }

@router.get("/projects/{project_id}/dependencies",response_model=list[DependencyOut],dependencies=[Depends(limit_dependency_requests)])
def dependencies(project_id:str,target:str|None=Query(default=None,max_length=300),limit:int=Query(default=200,ge=1,le=500),offset:int=Query(default=0,ge=0),db:Session=Depends(db_dep)):
    if not db.get(Project,project_id): raise HTTPException(404,"Project not found")
    return search_dependencies(db, project_id, target, limit, offset)

@router.get("/projects/{project_id}/impact",response_model=ImpactOut,dependencies=[Depends(limit_dependency_requests)])
def impact(project_id:str,target:str=Query(min_length=1,max_length=300),db:Session=Depends(db_dep)):
    if not db.get(Project,project_id): raise HTTPException(404,"Project not found")
    result=analyze_impact(db,project_id,target)
    if result is None: raise HTTPException(404,"No indexed file or symbol matches this target")
    return result

@router.get("/projects/{project_id}/overview",response_model=OverviewOut)
def overview(project_id:str,db:Session=Depends(db_dep)):
    if not db.get(Project,project_id): raise HTTPException(404,"Project not found")
    docs=db.scalars(select(Document).where(Document.project_id==project_id)).all()
    chunks=db.scalar(select(func.count(Chunk.id)).where(Chunk.project_id==project_id)) or 0
    langs={}
    for d in docs: langs[d.language]=langs.get(d.language,0)+1
    return {"project_id":project_id,"file_count":len(docs),"chunk_count":chunks,"languages":langs}
