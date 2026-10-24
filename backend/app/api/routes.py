import os, shutil, uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select
from sqlalchemy.orm import Session
from celery.result import AsyncResult
from app.db.session import SessionLocal
from app.models.models import Project, Document, Chunk, Dependency, IndexJob
from app.schemas.schemas import *
from app.tasks.celery_app import index_project
from app.retrieval.hybrid import retrieve
from app.services.llm import answer
from app.core.config import settings

router=APIRouter(prefix="/api")
def db_dep():
    db=SessionLocal()
    try: yield db
    finally: db.close()

@router.post("/projects",response_model=ProjectOut)
def create_project(payload:ProjectCreate,db:Session=Depends(db_dep)):
    p=Project(name=payload.name,repository_url=payload.repository_url); db.add(p); db.commit(); db.refresh(p); return p

@router.get("/projects",response_model=list[ProjectOut])
def projects(db:Session=Depends(db_dep)): return db.scalars(select(Project).order_by(Project.created_at.desc())).all()

@router.post("/projects/{project_id}/upload")
def upload(project_id:str,file:UploadFile=File(...),db:Session=Depends(db_dep)):
    p=db.get(Project,project_id)
    if not p: raise HTTPException(404,"Project not found")
    if not file.filename or not file.filename.lower().endswith(".zip"): raise HTTPException(400,"Only ZIP repositories are supported")
    os.makedirs(settings.upload_dir,exist_ok=True)
    path=os.path.join(settings.upload_dir,f"{uuid.uuid4()}.zip")
    size=0
    with open(path,"wb") as out:
        while chunk:=file.file.read(1024*1024):
            size+=len(chunk)
            if size>settings.max_upload_mb*1024*1024: os.unlink(path); raise HTTPException(413,"Upload too large")
            out.write(chunk)
    task=index_project.delay(project_id,path)
    job=IndexJob(project_id=project_id,celery_task_id=task.id,status="QUEUED"); db.add(job); db.commit()
    return {"job_id":job.id,"task_id":task.id,"status":"QUEUED"}

@router.post("/projects/{project_id}/index")
def index_without_upload(project_id:str,db:Session=Depends(db_dep)):
    raise HTTPException(400,"Upload a repository ZIP first using /upload")

@router.get("/projects/{project_id}/status",response_model=StatusOut)
def status(project_id:str,db:Session=Depends(db_dep)):
    job=db.scalars(select(IndexJob).where(IndexJob.project_id==project_id).order_by(IndexJob.created_at.desc())).first()
    if not job: return StatusOut(project_id=project_id,status="NOT_STARTED")
    result=AsyncResult(job.celery_task_id)
    state=result.state
    mapped={"PENDING":"QUEUED","STARTED":"PROCESSING","SUCCESS":"COMPLETED","FAILURE":"FAILED"}
    job.status=mapped.get(state,state); job.error=str(result.result) if state=="FAILURE" else None; db.commit()
    return StatusOut(project_id=project_id,status=job.status,error=job.error)

@router.post("/ask",response_model=AskResponse)
def ask(payload:AskRequest,db:Session=Depends(db_dep)):
    if not db.get(Project,payload.project_id): raise HTTPException(404,"Project not found")
    sources=retrieve(db,payload.project_id,payload.question,payload.top_k)
    text=answer(payload.question,sources)
    citations=[Citation(file=s["file"],start_line=s["start_line"],end_line=s["end_line"],symbol=s["symbol"]) for s in sources]
    return AskResponse(answer=text,citations=citations,retrieved_sources=sources)

@router.get("/projects/{project_id}/files")
def files(project_id:str,db:Session=Depends(db_dep)):
    docs=db.scalars(select(Document).where(Document.project_id==project_id).order_by(Document.path)).all()
    return [{"id":d.id,"path":d.path,"language":d.language,"content_hash":d.content_hash} for d in docs]

@router.get("/projects/{project_id}/dependencies")
def dependencies(project_id:str,db:Session=Depends(db_dep)):
    rows=db.scalars(select(Dependency).where(Dependency.project_id==project_id)).all()
    return [{"source_document_id":r.source_document_id,"source_symbol":r.source_symbol,"target":r.target,"relation_type":r.relation_type} for r in rows]

@router.get("/projects/{project_id}/overview")
def overview(project_id:str,db:Session=Depends(db_dep)):
    docs=db.scalars(select(Document).where(Document.project_id==project_id)).all()
    chunks=db.scalar(select(__import__('sqlalchemy').func.count(Chunk.id)).where(Chunk.project_id==project_id)) or 0
    langs={}
    for d in docs: langs[d.language]=langs.get(d.language,0)+1
    return {"project_id":project_id,"file_count":len(docs),"chunk_count":chunks,"languages":langs}
