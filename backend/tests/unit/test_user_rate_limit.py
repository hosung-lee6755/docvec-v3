"""계정 단위 속도 제한(enforce_user_rate_limit)과 비용 큰 엔드포인트 적용."""
import pytest
from fastapi import HTTPException

from app.core import rate_limit


class FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.expiries: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key: str, seconds: int) -> None:
        self.expiries[key] = seconds


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(rate_limit, "_get_client", lambda: fake)
    return fake


def test_blocks_after_limit_per_user_and_sets_window_once(redis):
    for _ in range(3):
        rate_limit.enforce_user_rate_limit("u1", "chat_message", limit=3, window_seconds=60)

    with pytest.raises(HTTPException) as caught:
        rate_limit.enforce_user_rate_limit("u1", "chat_message", limit=3, window_seconds=60)

    assert caught.value.status_code == 429
    assert redis.expiries == {"ratelimit:chat_message:user:u1": 60}


def test_limits_are_independent_per_user_and_per_bucket(redis):
    for _ in range(3):
        rate_limit.enforce_user_rate_limit("u1", "search", limit=3, window_seconds=60)

    rate_limit.enforce_user_rate_limit("u2", "search", limit=3, window_seconds=60)
    rate_limit.enforce_user_rate_limit("u1", "golden_eval", limit=3, window_seconds=60)


def test_fails_open_when_redis_is_down(monkeypatch):
    def broken():
        raise ConnectionError("redis down")

    monkeypatch.setattr(rate_limit, "_get_client", broken)

    rate_limit.enforce_user_rate_limit("u1", "search", limit=1, window_seconds=60)
    rate_limit.enforce_user_rate_limit("u1", "search", limit=1, window_seconds=60)


@pytest.mark.asyncio
async def test_search_endpoint_returns_429_once_account_limit_is_exceeded(redis):
    from types import SimpleNamespace

    from app.api.v1.endpoints import search as search_api

    user = SimpleNamespace(id="u-search")
    redis.counts["ratelimit:search:user:u-search"] = 60  # 이미 분당 한도를 소진

    with pytest.raises(HTTPException) as caught:
        await search_api.search(request=SimpleNamespace(project_id=None, collection_id=None), db=None, current_user=user)

    assert caught.value.status_code == 429
