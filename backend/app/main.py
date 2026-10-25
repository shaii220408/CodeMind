import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from redis import Redis

from app.api.auth_routes import router as auth_router
from app.api.analysis_routes import router as analysis_router
from app.api.routes import router
from app.core.config import settings


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        standard = set(logging.makeLogRecord({}).__dict__)
        for key, value in record.__dict__.items():
            if key not in standard and key not in {"message", "asctime"}:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


root_logger = logging.getLogger()
if not any(getattr(handler, "_coderag_json", False) for handler in root_logger.handlers):
    handler = logging.StreamHandler()
    handler._coderag_json = True
    handler.setFormatter(JsonFormatter())
    root_logger.addHandler(handler)
root_logger.setLevel(logging.INFO)

logger = logging.getLogger("coderag.rate_limit")
redis_client = Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
INCREMENT_WINDOW = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return count
"""
REQUEST_COUNT = Counter("coderag_http_requests_total", "HTTP requests received", ["method", "route", "status"])
REQUEST_LATENCY = Histogram("coderag_http_request_duration_seconds", "HTTP request duration", ["method", "route"])

app = FastAPI(
    title="CodeMind — AI-Powered Codebase Intelligence Platform",
    version="1.0.0",
    description="Explore source repositories with hybrid retrieval and evidence-grounded answers.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Chromium sends this preflight when a localhost UI accesses its local API.
    # Keep the origin allowlist explicit; do not permit arbitrary websites.
    allow_private_network=True,
)
app.include_router(auth_router)
app.include_router(router)
app.include_router(analysis_router)


@app.middleware("http")
async def redis_rate_limit(request: Request, call_next):
    started = time.perf_counter()
    path = request.url.path
    response = None
    if path not in {"/health", "/ready", "/docs", "/openapi.json", "/metrics"}:
        if path.startswith("/api/auth/"):
            limit, window, bucket = 10, 60, "auth"
        elif path.endswith("/upload"):
            limit, window, bucket = 5, 60, "upload"
        elif path == "/api/ask":
            limit, window, bucket = 30, 60, "ask"
        else:
            limit, window, bucket = 120, 60, "api"
        client_ip = request.client.host if request.client else "unknown"
        key = f"coderag:rate:{bucket}:{client_ip}:{int(time.time()) // window}"
        try:
            count = await asyncio.to_thread(redis_client.eval, INCREMENT_WINDOW, 1, key, window)
        except Exception:
            logger.exception("Redis rate limiter unavailable")
            response = JSONResponse(status_code=503, content={"detail": "Rate limiter temporarily unavailable"})
        else:
            if count > limit:
                response = JSONResponse(status_code=429, content={"detail": "Too many requests"}, headers={"Retry-After": str(window)})
    if response is None:
        response = await call_next(request)
    route = request.scope.get("route")
    route_name = getattr(route, "path", path)
    REQUEST_COUNT.labels(request.method, route_name, str(response.status_code)).inc()
    REQUEST_LATENCY.labels(request.method, route_name).observe(time.perf_counter() - started)
    return response


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    from app.db.session import engine
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        redis_client.ping()
        return {"status": "ready"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready"})
