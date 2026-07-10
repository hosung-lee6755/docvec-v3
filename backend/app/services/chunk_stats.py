"""Tracks how often each chunk (Qdrant point) is actually returned by a
search/chat retrieval, so noisy or never-hit chunks can be surfaced in the
chunk browser. Uses plain Redis counters (fast, best-effort) rather than
writing to Qdrant payloads on every hit — retrieval latency must not depend
on this."""

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

_HIT_KEY_PREFIX = "chunk_hits:"
_client = None


def _get_client():
    global _client
    if _client is None:
        import redis

        _client = redis.from_url(settings.redis_url)
    return _client


def record_hits(point_ids: list[str]) -> None:
    """Best-effort increment — a stats-tracking failure must never break
    search or chat retrieval, so all errors are swallowed here."""
    if not point_ids:
        return
    try:
        client = _get_client()
        pipe = client.pipeline()
        for point_id in point_ids:
            pipe.incr(f"{_HIT_KEY_PREFIX}{point_id}")
        pipe.execute()
    except Exception:
        logger.exception("chunk hit-count recording failed; continuing without it")


def get_hit_counts(point_ids: list[str]) -> dict[str, int]:
    if not point_ids:
        return {}
    try:
        client = _get_client()
        values = client.mget([f"{_HIT_KEY_PREFIX}{pid}" for pid in point_ids])
        return {pid: int(v) if v else 0 for pid, v in zip(point_ids, values)}
    except Exception:
        logger.exception("chunk hit-count lookup failed; returning zeros")
        return {pid: 0 for pid in point_ids}
