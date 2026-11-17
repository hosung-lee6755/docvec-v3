"""운영 정리 작업(전체 점검 2-8, 2026-11-16)."""
import logging
from datetime import datetime, timedelta

from app.core.config import settings
from app.pipeline.celery_app import celery_app

logger = logging.getLogger(__name__)

# 한 번에 지우는 행 수. 오래 쌓인 기록을 한 트랜잭션으로 지우면 테이블을 오래 잠근다
PURGE_BATCH_SIZE = 5000


def purge_answer_traces(db, retention_days: int, now: datetime | None = None) -> int:
    """보관 기간이 지난 답변 추적 기록을 지운다. 근거 목록(answer_trace_sources)은 FK로 함께 지워진다.
    보관 기간이 0 이하면 지우지 않는다."""
    from app.db.models.answer_trace import AnswerTrace

    if retention_days <= 0:
        return 0
    cutoff = (now or datetime.utcnow()) - timedelta(days=retention_days)
    deleted = 0
    while True:
        ids = [
            row[0] for row in
            db.query(AnswerTrace.id).filter(AnswerTrace.created_at < cutoff).limit(PURGE_BATCH_SIZE).all()
        ]
        if not ids:
            return deleted
        db.query(AnswerTrace).filter(AnswerTrace.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
        deleted += len(ids)


@celery_app.task(name="tasks.purge_answer_traces", queue="low")
def purge_answer_traces_task() -> dict:
    """ANSWER_TRACE_RETENTION_DAYS가 지난 답변 추적 기록을 지운다(0이면 계속 보관)."""
    from app.db.session import get_sync_db

    db = get_sync_db()
    try:
        deleted = purge_answer_traces(db, settings.answer_trace_retention_days)
        if deleted:
            logger.info("answer traces purged: %d (retention_days=%d)", deleted, settings.answer_trace_retention_days)
        return {"deleted": deleted}
    finally:
        db.close()
