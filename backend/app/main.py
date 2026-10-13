from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.db.init_db import init_db
from app.api.routes import router
from app.core.security import require_api_access

app=FastAPI(title="CodeRAG API",version="1.0.0",description="AI-powered codebase assistant using code-aware hybrid RAG")
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:5173"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
app.include_router(router, dependencies=[Depends(require_api_access)])

@app.on_event("startup")
def startup(): init_db()

@app.get("/health")
def health(): return {"status":"ok"}

@app.get("/ready")
def ready():
    from app.db.session import engine
    from app.core.config import settings
    from redis import Redis
    try:
        with engine.connect() as c: c.exec_driver_sql("SELECT 1")
        with Redis.from_url(settings.redis_url, socket_connect_timeout=2) as redis_client:
            redis_client.ping()
        return {"status":"ready"}
    except Exception:
        raise HTTPException(status_code=503,detail="A required service is unavailable")
