"""v3 마일스톤 7 — 골든 평가 실행과 문서 만료 점검(services/golden_eval.py, services/document_lifecycle.py)."""
from __future__ import annotations

import logging
from collections import defaultdict

from app.pipeline.celery_app import celery_app

logger = logging.getLogger(__name__)


# 재순위 모델과 채팅 검색이 도는 worker(high 큐)에서 실행한다. GPU 임베딩 워커(embed)는 쓰지 않는다.
@celery_app.task(name="tasks.run_golden_eval", queue="high")
def run_golden_eval(run_id: str) -> dict:
    from app.db.session import get_sync_db
    from app.services.golden_eval import evaluate_run_sync

    db = get_sync_db()
    try:
        run = evaluate_run_sync(db, run_id)
        return {"run_id": run_id, "status": run.status if run else "MISSING"}
    finally:
        db.close()


@celery_app.task(name="tasks.expire_documents", queue="low")
def expire_documents() -> dict:
    """만료일이 지난 현재 버전을 보관하고 Qdrant 페이로드를 맞춘다. 그 사이에도 검색은
    Postgres 재확인(access_policy.is_lifecycle_active)이 만료일을 직접 봐서 막는다.
    같은 주기로 오래 멈춘 골든 평가 실행도 실패로 정리한다(워커가 죽었거나 메시지를 잃은 경우)."""
    from app.db.session import get_sync_db
    from app.services.document_lifecycle import after_transition_sync, expire_due_documents_sync
    from app.services.golden_eval import fail_stale_runs_sync

    db = get_sync_db()
    try:
        fail_stale_runs_sync(db)
        expired = expire_due_documents_sync(db)
        by_collection: dict = defaultdict(list)
        for doc in expired:
            by_collection[doc.collection_id].append(str(doc.id))
        for collection_id, ids in by_collection.items():
            after_transition_sync(db, ids, collection_id, "lifecycle")
        if expired:
            logger.info("expired documents archived: %d", len(expired))
        return {"archived": [str(d.id) for d in expired]}
    finally:
        db.close()


# 페이로드 다시 맞추기는 몇 번까지 시도한다. 그 뒤에는 backfill 스크립트로 맞춘다
_RESYNC_MAX_RETRIES = 5


@celery_app.task(name="tasks.resync_document_access", queue="low", bind=True, max_retries=_RESYNC_MAX_RETRIES)
def resync_document_access(self, document_ids: list[str]) -> dict:
    """수명주기 전환 뒤 Qdrant 사본 동기화가 실패한 문서를 다시 맞춘다(v3 마일스톤 7)."""
    from app.db.session import get_sync_db
    from app.services.access_payload import sync_document_access_sync

    db = get_sync_db()
    try:
        failed = sync_document_access_sync(db, document_ids)
    finally:
        db.close()
    if failed:
        raise self.retry(args=[failed], countdown=60 * (self.request.retries + 1))
    return {"synced": document_ids}
