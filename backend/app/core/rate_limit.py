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
_redis_outage_logged = False  # Track whether we've already logged this outage


def _get_client():
    global _client
    if _client is None:
        import redis

        _client = redis.from_url(settings.redis_url)
    return _client


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request, respecting X-Forwarded-For from trusted proxies.

    Uvicorn with --proxy-headers and --forwarded-allow-ips already rewrites
    request.client.host when the connection comes from a trusted proxy. This
    function trusts that preprocessing and extracts the IP safely.
    """
    if request.client:
        return request.client.host
    return "unknown"


def enforce_rate_limit(
    request: Request,
    bucket: str,
    limit: int,
    window_seconds: int,
    email: str | None = None,
) -> None:
    """Rate limit by IP and optionally by email (for login/register).

    Args:
        request: FastAPI request object
        bucket: Rate limit bucket name (e.g., "login", "register")
        limit: Max requests allowed per window
        window_seconds: Time window in seconds
        email: Optional email address for per-account throttling (prevents one attacker
               behind a proxy from locking out all users who share that proxy IP).
    """
    client_ip = _get_client_ip(request)

    # For login/register, also rate-limit by email to prevent per-account lockout
    # when one attacker floods from behind a proxy (shared IP scenario).
    email_key = None
    if email:
        email_key = f"ratelimit:{bucket}:email:{email}"

    ip_key = f"ratelimit:{bucket}:{client_ip}"
    keys_to_check = [ip_key]
    if email_key:
        keys_to_check.append(email_key)

    _check_keys(keys_to_check, bucket, limit, window_seconds, client_ip)


def enforce_user_rate_limit(user_id: str, bucket: str, limit: int, window_seconds: int) -> None:
    """로그인한 사용자 단위 제한 — LLM/검색/평가처럼 비용이 큰 인증 엔드포인트용.

    IP가 아니라 계정 기준이라 같은 프록시 뒤의 다른 사용자에게 영향을 주지 않는다."""
    _check_keys([f"ratelimit:{bucket}:user:{user_id}"], bucket, limit, window_seconds, f"user:{user_id}")


def _check_keys(keys_to_check: list[str], bucket: str, limit: int, window_seconds: int, who: str) -> None:
    global _redis_outage_logged

    try:
        client = _get_client()
        _redis_outage_logged = False  # Reset on successful connection

        # Check all rate limit buckets (IP + email)
        for key in keys_to_check:
            count = client.incr(key)
            if count == 1:
                client.expire(key, window_seconds)

            if count > limit:
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests. Please try again later.",
                )
    except HTTPException:
        # Re-raise rate limit exceeded (not a Redis error)
        raise
    except Exception:
        # Redis is down or unreachable — fail open but log once per outage
        if not _redis_outage_logged:
            logger.exception(
                "rate limit check failed; failing open (Redis outage)",
                extra={"bucket": bucket, "who": who},
            )
            _redis_outage_logged = True
        return
