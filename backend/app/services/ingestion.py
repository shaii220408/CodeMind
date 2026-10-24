import hashlib, os, zipfile, tempfile, shutil
from pathlib import Path
from sqlalchemy import select, delete
from app.models.models import Document, Chunk, Dependency
from app.parsers.code_parser import EXT, parse_code
from app.services.embedding import embed_many

IGNORE={".git","node_modules","target","build","dist",".venv","__pycache__"}

def safe_extract(zip_path: str, dest: str, max_bytes: int):
    total=0
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name=Path(info.filename)
            if name.is_absolute() or ".." in name.parts: raise ValueError("Unsafe ZIP path")
            total += info.file_size
            if total > max_bytes: raise ValueError("Archive exceeds configured size limit")
            if any(part in IGNORE for part in name.parts): continue
            target=Path(dest,name)
            target.parent.mkdir(parents=True,exist_ok=True)
            if info.is_dir(): continue
            with z.open(info) as src, open(target,"wb") as dst: shutil.copyfileobj(src,dst)

def scan_files(root: str):
    for p in Path(root).rglob("*"):
        if not p.is_file() or any(part in IGNORE for part in p.parts): continue
        if p.suffix.lower() not in EXT: continue
        if p.stat().st_size > 2_000_000: continue
        try: yield p, EXT[p.suffix.lower()], p.read_text(encoding="utf-8")
        except (UnicodeDecodeError,OSError): continue

def index_repository(db, project_id: str, root: str):
    old={d.path:d for d in db.scalars(select(Document).where(Document.project_id==project_id)).all()}
    seen=set()
    for path,language,content in scan_files(root):
        rel=path.relative_to(root).as_posix(); seen.add(rel); digest=hashlib.sha256(content.encode()).hexdigest()
        doc=old.get(rel)
        if doc and doc.content_hash==digest: continue
        if doc:
            db.execute(delete(Chunk).where(Chunk.document_id==doc.id)); db.execute(delete(Dependency).where(Dependency.source_document_id==doc.id))
            doc.language=language; doc.content_hash=digest; doc.content=content
        else:
            doc=Document(project_id=project_id,path=rel,language=language,content_hash=digest,content=content); db.add(doc); db.flush()
        chunks=parse_code(content,language); vectors=embed_many([f"{rel}\n{c.symbol}\n{c.content}" for c in chunks])
        for c,v in zip(chunks,vectors):
            db.add(Chunk(project_id=project_id,document_id=doc.id,symbol=c.symbol,symbol_type=c.symbol_type,start_line=c.start_line,end_line=c.end_line,content=c.content,embedding=v,metadata={"language":language}))
            for imp in c.imports:
                db.add(Dependency(project_id=project_id,source_document_id=doc.id,source_symbol=c.symbol,target=imp,relation_type="import"))
    for rel,doc in old.items():
        if rel not in seen:
            db.delete(doc)
    db.commit()
