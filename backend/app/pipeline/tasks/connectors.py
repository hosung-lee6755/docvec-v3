"""문서 원천 커넥터 작업(v3 마일스톤 3).

- `dispatch_due_connectors`: beat가 1분마다 부른다. 주기가 된 커넥터의 동기화를 큐에 넣는다.
- `sync_connector`: 커넥터 하나를 동기화한다. 커넥터별 Redis 락으로 겹쳐 돌지 않게 한다.

동기화 엔진은 비동기 세션을 쓴다(문서 생성·삭제를 업로드·삭제 엔드포인트와 같은 코드로 하기 위해서다).
Celery 프로세스에서는 실행마다 새 이벤트 루프를 쓰므로, 풀 없는(NullPool) 엔진을 따로 만든다.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from app.core.config import settings
from app.pipeline.celery_app import celery_app
from app.services.sync_lock import connector_lock_key, held_lock

logger = logging.getLogger(__name__)


class _UnreachableSource:
    """원천에 연결하지 못했을 때 실행 기록을 실패로 남기기 위한 클라이언트."""

    def __init__(self, error: Exception):
        self._error = error

    def list_files(self):
        raise self._error

    def close(self):
        pass


async def _sync(connector_id: str, triggered_by: str | None) -> dict:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.db.models.source_connector import SourceConnector
    from app.services.audit import log_audit
    from app.services.connectors.registry import build_source_client
    from app.services.connectors.sync_engine import run_connector_sync

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    client = None
    try:
        async with maker() as db:
            connector = await db.get(SourceConnector, connector_id)
            if connector is None or not connector.enabled:
                return {"status": "skipped"}
            try:
                client = await asyncio.to_thread(build_source_client, connector)
            except Exception as exc:  # 연결·인증·복호화 실패
                logger.warning("커넥터 연결 실패: connector=%s err=%s", connector_id, type(exc).__name__)
                client = _UnreachableSource(exc)
            run = await run_connector_sync(db, connector, client, triggered_by=triggered_by)
            log_audit(db, triggered_by, "connector.sync", "connector", str(connector_id),
                      detail={"status": run.status, "counts": run.counts})
            await db.commit()
            return {"status": run.status, "counts": run.counts}
    finally:
        if client is not None:
            client.close()
        await engine.dispose()


@celery_app.task(name="tasks.sync_connector", queue="low")
def sync_connector_task(connector_id: str, triggered_by: str | None = None) -> dict:
    with held_lock(connector_lock_key(connector_id)) as acquired:
        if not acquired:
            return {"status": "already_running"}
        return asyncio.run(_sync(connector_id, triggered_by))


def due_connector_ids(db, now: datetime) -> list[str]:
    from sqlalchemy import select

    from app.db.models.source_connector import SourceConnector

    due = []
    for connector in db.scalars(select(SourceConnector).where(SourceConnector.enabled.is_(True))):
        interval = timedelta(minutes=max(5, connector.sync_interval_minutes or 30))
        last = connector.last_sync_at
        if last is not None and last.tzinfo is not None:
            last = last.replace(tzinfo=None)
        if last is None or last + interval <= now:
            due.append(str(connector.id))
    return due


@celery_app.task(name="tasks.dispatch_due_connectors", queue="low")
def dispatch_due_connectors() -> dict:
    from app.db.session import get_sync_db

    db = get_sync_db()
    try:
        ids = due_connector_ids(db, datetime.utcnow())
    finally:
        db.close()
    for connector_id in ids:
        sync_connector_task.delay(connector_id)
    return {"dispatched": ids}
