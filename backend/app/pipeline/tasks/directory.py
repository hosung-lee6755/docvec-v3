"""AD 주기 동기화 작업(v3 마일스톤 3).

beat가 `LDAP_SYNC_INTERVAL_MINUTES`마다 부른다. LDAP 로그인이 꺼져 있으면 아무것도 하지 않는다.
같은 작업이 겹쳐 돌지 않도록 Redis 락을 잡는다. AD에 연결하지 못하면 아무것도 바꾸지 않는다.
"""
import logging

from app.core.config import settings
from app.pipeline.celery_app import celery_app
from app.services.sync_lock import DIRECTORY_LOCK_KEY, held_lock

logger = logging.getLogger(__name__)


def run_directory_sync(db, client) -> dict:
    """한 번 동기화하고 감사 로그를 남긴다. 커밋과 롤백은 이 함수가 맡는다."""
    from app.services.audit import log_audit
    from app.services.directory.ldap_client import DirectoryUnavailable
    from app.services.directory.provisioning import sync_directory

    try:
        result = sync_directory(
            db, client, settings.ldap_admin_group_dn, preprovision=settings.ldap_preprovision_users,
        )
    except DirectoryUnavailable as exc:
        db.rollback()
        logger.warning("디렉터리 동기화 건너뜀(AD 연결 불가): %s", exc)
        log_audit(db, None, "directory.sync_failed", "directory", None, detail={"reason": str(exc)[:200]})
        db.commit()
        return {"status": "directory_unavailable"}
    except Exception:
        db.rollback()
        logger.exception("디렉터리 동기화 실패")
        raise
    log_audit(db, None, "directory.sync", "directory", None, detail=result)
    db.commit()
    return {"status": "ok", **result}


@celery_app.task(name="tasks.sync_directory", queue="low")
def sync_directory_task() -> dict:
    from app.db.session import get_sync_db
    from app.services.directory import get_directory_client

    client = get_directory_client()
    if client is None:
        return {"status": "disabled"}
    with held_lock(DIRECTORY_LOCK_KEY) as acquired:
        if not acquired:
            return {"status": "already_running"}
        db = get_sync_db()
        try:
            return run_directory_sync(db, client)
        finally:
            db.close()
