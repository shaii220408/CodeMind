import pytest
from fastapi import HTTPException

from app.services.rate_limit import enforce_limit


class FakeRedis:
    def __init__(self):
        self.counts = {}

    def eval(self, _script, _key_count, key, _window):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def ttl(self, _key):
        return 60


def test_rate_limit_rejects_after_limit_and_returns_retry_after():
    redis=FakeRedis()
    enforce_limit(redis,"rate:test",1,60)

    with pytest.raises(HTTPException) as error:
        enforce_limit(redis,"rate:test",1,60)

    assert error.value.status_code==429
    assert error.value.headers["Retry-After"]=="60"
