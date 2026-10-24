from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db.init_db import init_db
from app.api.routes import router

app=FastAPI(title="CodeRAG API",version="1.0.0",description="AI-powered codebase assistant using code-aware hybrid RAG")
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:5173"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
app.include_router(router)

@app.on_event("startup")
def startup(): init_db()

@app.get("/health")
def health(): return {"status":"ok"}

@app.get("/ready")
def ready():
    from app.db.session import engine
    try:
        with engine.connect() as c: c.exec_driver_sql("SELECT 1")
        return {"status":"ready"}
    except Exception as e:
        return {"status":"not_ready","error":str(e)}
