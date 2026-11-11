"""동기화 작업이 겹쳐 돌지 않게 하는 Redis 락(v3 마일스톤 3).

락은 짧은 만료 시간으로 잡고, 작업이 도는 동안 별도 스레드가 주기적으로 만료를 늘린다.
그래서 작업이 아무리 길어도 락이 중간에 풀리지 않고, 워커가 죽으면 만료 시간 뒤에 저절로 풀린다.
놓을 때 이미 만료됐더라도(LockError) 작업 결과를 가리지 않도록 로그만 남긴다.
"""
import logging
import threading
from contextlib import contextmanager
from typing import Iterator

import redis
from redis.exceptions import LockError

from app.core.config import settings

logger = logging.getLogger(__name__)

LOCK_TTL_SECONDS = 10 * 60
_HEARTBEAT_SECONDS = LOCK_TTL_SECONDS // 3

DIRECTORY_LOCK_KEY = "lock:sync_directory"


def connector_lock_key(connector_id: str) -> str:
    return f"lock:sync_connector:{connector_id}"


@contextmanager
def held_lock(key: str) -> Iterator[bool]:
    """락을 잡으면 True, 이미 누가 잡고 있으면 False를 내준다. 잡은 동안 만료를 계속 늘린다."""
    lock = redis.from_url(settings.redis_url).lock(key, timeout=LOCK_TTL_SECONDS)
    if not lock.acquire(blocking=False):
        yield False
        return
    stop = threading.Event()

    def _heartbeat() -> None:
        while not stop.wait(_HEARTBEAT_SECONDS):
            try:
                lock.reacquire()
            except LockError:
                logger.warning("동기화 락을 잃었습니다: %s", key)
                return

    beat = threading.Thread(target=_heartbeat, name=f"lock-heartbeat:{key}", daemon=True)
    beat.start()
    try:
        yield True
    finally:
        stop.set()
        beat.join(timeout=5)
        try:
            lock.release()
        except LockError:
            logger.warning("동기화 락이 이미 풀려 있었습니다: %s", key)
