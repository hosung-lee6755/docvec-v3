"""Unit coverage for app.services.audit.log_audit -- the write-path behind
the new audit-log sales-readiness feature. Ensures a logging failure never
propagates and blocks the action it's auditing."""

from unittest.mock import MagicMock

from app.db.models.audit_log import AuditLog
from app.services.audit import log_audit


def test_log_audit_queues_an_audit_log_row():
    db = MagicMock()

    log_audit(
        db, "user-1", "document.delete", "document", "doc-1",
        detail={"filename": "a.pdf"}, ip_address="127.0.0.1",
    )

    db.add.assert_called_once()
    added = db.add.call_args[0][0]
    assert isinstance(added, AuditLog)
    assert added.user_id == "user-1"
    assert added.action == "document.delete"
    assert added.resource_type == "document"
    assert added.resource_id == "doc-1"
    assert added.detail == {"filename": "a.pdf"}
    assert added.ip_address == "127.0.0.1"


def test_log_audit_never_raises_when_db_add_fails():
    db = MagicMock()
    db.add.side_effect = RuntimeError("db is down")

    log_audit(db, "user-1", "auth.login")  # must not raise
