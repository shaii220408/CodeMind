from fastapi import HTTPException, Request
from redis import Redis

from app.core.config import settings

_INCREMENT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return count
"""


def enforce_limit(redis_client, key: str, limit: int, window_seconds: int):
    count = int(redis_client.eval(_INCREMENT_SCRIPT, 1, key, window_seconds))
    if count > limit:
        ttl = max(int(redis_client.ttl(key)), 1)
        raise HTTPException(
            status_code=429,
            detail="Request limit reached. Try again after the current rate-limit window.",
            headers={"Retry-After": str(ttl)},
        )


def _check(request: Request, action: str, limit: int, window_seconds: int):
    client_host = request.client.host if request.client else "unknown"
    key = f"coderag:rate:{action}:{client_host}"
    try:
        with Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
        ) as redis_client:
            enforce_limit(redis_client, key, limit, window_seconds)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Rate-limit service is unavailable") from exc


def limit_ask_requests(request: Request):
    _check(request, "ask", settings.rate_limit_ask_per_minute, 60)


def limit_upload_requests(request: Request):
    _check(request, "upload", settings.rate_limit_uploads_per_hour, 3600)


def limit_dependency_requests(request: Request):
    _check(request, "dependency", settings.rate_limit_dependency_per_minute, 60)
