"""Regression coverage for app.api.v1.deps.get_current_user — used as a
FastAPI dependency by nearly every authenticated endpoint. Covers the
is_active check added as part of the CRITICAL security fix (a deactivated
user's still-valid JWT must not keep working)."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.deps import get_current_user


def _credentials(token="fake-token"):
    return MagicMock(credentials=token)


@pytest.mark.asyncio
async def test_get_current_user_returns_active_user():
    user = MagicMock(is_active=True, token_version=0, must_change_password=False)
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=user))

    with patch("app.api.v1.deps.verify_token", return_value={"sub": str(uuid4())}):
        result = await get_current_user(_credentials(), db)

    assert result is user


@pytest.mark.asyncio
async def test_get_current_user_rejects_invalid_token():
    db = AsyncMock()

    with patch("app.api.v1.deps.verify_token", return_value=None):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(_credentials(), db)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_404s_when_user_missing():
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    with patch("app.api.v1.deps.verify_token", return_value={"sub": str(uuid4())}):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(_credentials(), db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_current_user_rejects_deactivated_user():
    """CRITICAL regression: a disabled account's still-valid JWT must stop
    working immediately, not just at next token expiry."""
    user = MagicMock(is_active=False)
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=user))

    with patch("app.api.v1.deps.verify_token", return_value={"sub": str(uuid4())}):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(_credentials(), db)

    assert exc_info.value.status_code == 401
