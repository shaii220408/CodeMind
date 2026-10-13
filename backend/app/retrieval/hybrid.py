from sqlalchemy import text, select
from app.models.models import Chunk, Document
from app.services.embedding import embed_many

def rrf(rank_lists, k=60):
    scores={}
    for items in rank_lists:
        for rank,item in enumerate(items,1): scores[item.id]=scores.get(item.id,0)+1/(k+rank)
    return sorted(scores, key=scores.get, reverse=True)

def retrieve(db, project_id, question, top_k=8):
    q=embed_many([question])[0]
    semantic=db.scalars(select(Chunk).where(Chunk.project_id==project_id, Chunk.embedding.is_not(None)).order_by(Chunk.embedding.cosine_distance(q)).limit(top_k)).all()
    lexical=db.execute(text("""
      SELECT c.id FROM chunks c JOIN documents d ON d.id=c.document_id
      WHERE c.project_id=:pid AND (
        to_tsvector('simple', c.symbol || ' ' || c.content) @@ plainto_tsquery('simple', :q)
        OR to_tsvector('simple', d.path || ' ' || d.content) @@ plainto_tsquery('simple', :q)
      )
      ORDER BY GREATEST(
        ts_rank(to_tsvector('simple', c.symbol || ' ' || c.content), plainto_tsquery('simple', :q)),
        ts_rank(to_tsvector('simple', d.path || ' ' || d.content), plainto_tsquery('simple', :q))
      ) DESC LIMIT :lim
    """),{"pid":project_id,"q":question,"lim":top_k}).all()
    lexical_ids=[row[0] for row in lexical]
    lex_chunks=db.scalars(select(Chunk).where(Chunk.id.in_(lexical_ids))).all() if lexical_ids else []
    order={x.id:i for i,x in enumerate(lex_chunks)}; lex_chunks.sort(key=lambda x:order[x.id])
    ranked_lists = [("semantic", semantic), ("lexical", lex_chunks)]
    scores = {}
    sources = {}
    for source, items in ranked_lists:
        for rank, item in enumerate(items, 1):
            scores[item.id] = scores.get(item.id, 0.0) + 1.0 / (60 + rank)
            sources.setdefault(item.id, set()).add(source)
    ids=rrf([semantic,lex_chunks])[:top_k]
    chunks=db.scalars(select(Chunk).where(Chunk.id.in_(ids))).all()
    by={c.id:c for c in chunks}
    docs={d.id:d.path for d in db.scalars(select(Document).where(Document.id.in_([c.document_id for c in chunks]))).all()}
    return [{"id":i,"document_id":by[i].document_id,"file":docs[by[i].document_id],"symbol":by[i].symbol,"start_line":by[i].start_line,"end_line":by[i].end_line,"content":by[i].content,"retrieval_score":scores[i],"retrieval_source":"+".join(sorted(sources[i]))} for i in ids if i in by]
