"""Best-effort fixed-window rate limiting for unauthenticated auth endpoints
(register/login/refresh), backed by the same Redis instance already used for
Celery/caching. Fails open (allows the request but logs) if Redis is
unreachable — an outage of the rate limiter must not take down login for
every user."""

import logging

from fastapi import HTTPException, Request

from app.core.config import settings

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        import redis

        _client = redis.from_url(settings.redis_url)
    return _client


def enforce_rate_limit(request: Request, bucket: str, limit: int, window_seconds: int) -> None:
    client_ip = request.client.host if request.client else "unknown"
    key = f"ratelimit:{bucket}:{client_ip}"
    try:
        client = _get_client()
        count = client.incr(key)
        if count == 1:
            client.expire(key, window_seconds)
    except Exception:
        logger.exception("rate limit check failed; failing open", extra={"bucket": bucket})
        return

    if count > limit:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later.",
        )
