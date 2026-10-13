import hashlib, os, zipfile, shutil, stat
from pathlib import Path
from sqlalchemy import select, delete
from app.models.models import Document, Chunk, Dependency
from app.parsers.code_parser import EXT, parse_code
from app.services.embedding import embed_many

IGNORE={".git","node_modules","target","build","dist",".venv","__pycache__"}

def _chunk_key(chunk):
    return (chunk.symbol,chunk.symbol_type,chunk.content)

def safe_extract(zip_path: str, dest: str, max_bytes: int, max_files: int = 20_000):
    """Extract supported source files while rejecting unsafe or oversized ZIPs."""
    destination = Path(dest).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    total = 0
    count = 0
    try:
        archive = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError("Uploaded file is not a valid ZIP archive") from exc

    with archive as z:
        for info in z.infolist():
            count += 1
            total += info.file_size
            if count > max_files:
                raise ValueError("Archive contains too many entries")
            if total > max_bytes:
                raise ValueError("Archive exceeds configured size limit")
            raw_name = info.filename
            # ZIP uses '/', but malicious archives often use Windows separators/drives.
            normalized = raw_name.replace("\\", "/")
            parts = normalized.split("/")
            mode = info.external_attr >> 16
            if (normalized.startswith("/") or any(":" in part for part in parts)
                    or any(part in ("..", "") for part in parts[:-1])
                    or stat.S_ISLNK(mode)):
                raise ValueError("Unsafe ZIP path or entry type")
            if info.is_dir():
                continue
            if any(part in IGNORE for part in parts):
                continue
            if Path(parts[-1]).suffix.lower() not in EXT:
                continue
            if info.flag_bits & 0x1:
                raise ValueError("Encrypted ZIP entries are not supported")
            target = (destination.joinpath(*parts)).resolve()
            if destination not in target.parents:
                raise ValueError("Unsafe ZIP path")
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)

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
            previous_chunks=db.scalars(select(Chunk).where(Chunk.document_id==doc.id)).all()
            previous_embeddings={
                (chunk.symbol,chunk.symbol_type,chunk.content):chunk.embedding
                for chunk in previous_chunks if chunk.embedding is not None
            }
            db.execute(delete(Dependency).where(Dependency.source_document_id==doc.id))
            doc.language=language; doc.content_hash=digest; doc.content=content
        else:
            previous_chunks=[]
            previous_embeddings={}
            doc=Document(project_id=project_id,path=rel,language=language,content_hash=digest,content=content); db.add(doc); db.flush()
        chunks=parse_code(content,language)
        missing=[i for i,chunk in enumerate(chunks) if _chunk_key(chunk) not in previous_embeddings]
        generated=embed_many([f"{rel}\n{chunks[i].symbol}\n{chunks[i].content}" for i in missing])
        vectors=[previous_embeddings.get(_chunk_key(chunk)) for chunk in chunks]
        for index,vector in zip(missing,generated): vectors[index]=vector
        if previous_chunks:
            db.execute(delete(Chunk).where(Chunk.document_id==doc.id))
        for c,v in zip(chunks,vectors):
            db.add(Chunk(project_id=project_id,document_id=doc.id,symbol=c.symbol,symbol_type=c.symbol_type,start_line=c.start_line,end_line=c.end_line,content=c.content,embedding=v,metadata={"language":language}))
        edges = {
            (chunk.symbol, target, relation_type)
            for chunk in chunks
            for relation_type, targets in (("import", chunk.imports), ("class_reference", chunk.references))
            for target in targets
        }
        for source_symbol, target, relation_type in sorted(edges):
            db.add(Dependency(
                project_id=project_id, source_document_id=doc.id,
                source_symbol=source_symbol, target=target, relation_type=relation_type,
            ))
    for rel,doc in old.items():
        if rel not in seen:
            db.delete(doc)
    db.commit()

def reindex_saved_documents(db, project_id: str):
    """Rebuild chunks, embeddings, and imports from source already stored in PostgreSQL."""
    documents = db.scalars(select(Document).where(Document.project_id == project_id)).all()
    if not documents:
        raise ValueError("No indexed files exist yet; upload a repository ZIP first")
    for doc in documents:
        db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
        db.execute(delete(Dependency).where(Dependency.source_document_id == doc.id))
        chunks = parse_code(doc.content, doc.language)
        vectors = embed_many([f"{doc.path}\n{c.symbol}\n{c.content}" for c in chunks])
        for chunk, vector in zip(chunks, vectors):
            db.add(Chunk(
                project_id=project_id, document_id=doc.id, symbol=chunk.symbol,
                symbol_type=chunk.symbol_type, start_line=chunk.start_line,
                end_line=chunk.end_line, content=chunk.content, embedding=vector,
                metadata={"language": doc.language},
            ))
        edges = {
            (chunk.symbol, target, relation_type)
            for chunk in chunks
            for relation_type, targets in (("import", chunk.imports), ("class_reference", chunk.references))
            for target in targets
        }
        for source_symbol, target, relation_type in sorted(edges):
            db.add(Dependency(
                project_id=project_id, source_document_id=doc.id,
                source_symbol=source_symbol, target=target, relation_type=relation_type,
            ))
    db.commit()
