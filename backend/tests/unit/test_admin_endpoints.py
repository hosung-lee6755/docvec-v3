"""Access-control regression coverage for the new admin-only audit-log and
usage endpoints -- a non-admin must never see other users' audit trail or
BYOK cost data."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.admin import get_usage_summary, list_audit_logs


@pytest.mark.asyncio
async def test_list_audit_logs_rejects_non_admin():
    db = AsyncMock()
    non_admin = MagicMock(role="editor")

    with pytest.raises(HTTPException) as exc_info:
        await list_audit_logs(current_user=non_admin, db=db)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_get_usage_summary_rejects_non_admin():
    db = AsyncMock()
    non_admin = MagicMock(role="viewer")

    with pytest.raises(HTTPException) as exc_info:
        await get_usage_summary(current_user=non_admin, db=db)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_list_audit_logs_allows_admin():
    db = AsyncMock()
    db.scalar.return_value = 0
    db.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
    admin = MagicMock(role="admin")

    result = await list_audit_logs(limit=50, offset=0, current_user=admin, db=db)

    assert result == {"total": 0, "items": []}
