import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


def log_audit(
    db: AsyncSession,
    user_id: str | None,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    detail: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Queue a compliance-relevant audit entry on the current session.

    Rides along with the caller's existing db.commit() rather than committing
    itself, so a single request that both mutates state and logs it does so
    atomically. Never raises -- a logging failure must not block the action
    it's auditing.
    """
    try:
        db.add(
            AuditLog(
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                detail=detail,
                ip_address=ip_address,
            )
        )
    except Exception:
        logger.exception("failed to queue audit log entry", extra={"action": action})
