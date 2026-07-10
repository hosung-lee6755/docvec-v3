"""Regression coverage for the register/login/refresh flow in
app.api.v1.endpoints.auth — in particular the CRITICAL security fixes made
this session: deactivated users must be rejected at login/refresh/me, and a
duplicate-email registration must not reveal that the email already exists."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import auth as auth_module
from app.schemas.auth import LoginRequest, UserCreate

# Rate limiting is exercised live against real Redis elsewhere this session
# (curl smoke test); these are unit tests for the endpoint logic itself, so
# the limiter is neutralized to avoid depending on Redis state/ordering.
_no_rate_limit = patch.object(auth_module, "enforce_rate_limit", MagicMock())


def _http_request():
    req = MagicMock()
    req.client.host = "127.0.0.1"
    return req


@pytest.mark.asyncio
async def test_register_creates_user_and_returns_tokens():
    db = AsyncMock()
    db.add = MagicMock()  # AsyncSession.add() is sync; avoid an unawaited-coroutine warning
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    with _no_rate_limit:
        result = await auth_module.register(
            UserCreate(email="new@test.com", username="newuser", password="password123"),
            MagicMock(),
            _http_request(),
            db,
        )

    assert result.access_token
    assert result.user.email == "new@test.com"
    # register() also queues an audit log entry via log_audit(), so two add()
    # calls are expected: the new User, then the AuditLog.
    assert db.add.call_count == 2
    added_user = db.add.call_args_list[0][0][0]
    assert added_user.hashed_password != "password123"
    assert added_user.is_active is True


@pytest.mark.asyncio
async def test_register_duplicate_email_returns_generic_message():
    """HIGH regression: must not reveal that the email is already registered."""
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=MagicMock()))

    with _no_rate_limit:
        with pytest.raises(HTTPException) as exc_info:
            await auth_module.register(
                UserCreate(email="taken@test.com", username="taken", password="password123"),
                MagicMock(),
                _http_request(),
                db,
            )

    assert exc_info.value.status_code == 409
    assert "already" not in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_login_rejects_wrong_password():
    user = MagicMock(is_active=True, hashed_password="hash")
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=user))

    with _no_rate_limit, patch.object(auth_module, "verify_password", return_value=False):
        with pytest.raises(HTTPException) as exc_info:
            await auth_module.login(
                LoginRequest(email="user@test.com", password="wrongpass"),
                MagicMock(),
                _http_request(),
                db,
            )

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_login_rejects_deactivated_user():
    """CRITICAL regression: correct password but a disabled account must
    still be rejected."""
    user = MagicMock(is_active=False, hashed_password="hash", id=uuid4(), email="user@test.com")
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=user))

    with _no_rate_limit, patch.object(auth_module, "verify_password", return_value=True):
        with pytest.raises(HTTPException) as exc_info:
            await auth_module.login(
                LoginRequest(email="user@test.com", password="correctpass"),
                MagicMock(),
                _http_request(),
                db,
            )

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_login_succeeds_for_active_user():
    user = MagicMock(
        is_active=True,
        hashed_password="hash",
        id=uuid4(),
        email="user@test.com",
        username="user",
        role="viewer",
    )
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=user))

    with _no_rate_limit, patch.object(auth_module, "verify_password", return_value=True):
        result = await auth_module.login(
            LoginRequest(email="user@test.com", password="correctpass"),
            MagicMock(),
            _http_request(),
            db,
        )

    assert result.access_token


@pytest.mark.asyncio
async def test_refresh_rejects_missing_cookie():
    request = _http_request()
    request.cookies.get.return_value = None
    db = AsyncMock()

    with _no_rate_limit:
        with pytest.raises(HTTPException) as exc_info:
            await auth_module.refresh(request, db)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rejects_deactivated_user():
    """CRITICAL regression: a valid refresh token for a since-deactivated
    user must not mint a new access token."""
    request = _http_request()
    request.cookies.get.return_value = "some-refresh-token"
    db = AsyncMock()
    db.scalar.return_value = MagicMock(is_active=False)

    with _no_rate_limit, patch.object(
        auth_module, "verify_token", return_value={"sub": str(uuid4()), "type": "refresh"}
    ):
        with pytest.raises(HTTPException) as exc_info:
            await auth_module.refresh(request, db)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_refresh_issues_new_access_token_for_active_user():
    request = _http_request()
    request.cookies.get.return_value = "some-refresh-token"
    db = AsyncMock()
    db.scalar.return_value = MagicMock(is_active=True)

    with _no_rate_limit, patch.object(
        auth_module, "verify_token", return_value={"sub": str(uuid4()), "type": "refresh"}
    ):
        result = await auth_module.refresh(request, db)

    assert result.access_token


@pytest.mark.asyncio
async def test_me_rejects_deactivated_user():
    """CRITICAL regression for the /me route's own get_current_user, which
    duplicates deps.get_current_user's logic rather than importing it."""
    credentials = MagicMock(credentials="fake-token")
    db = AsyncMock()
    db.execute.return_value = MagicMock(
        scalar_one_or_none=MagicMock(return_value=MagicMock(is_active=False))
    )

    with patch.object(auth_module, "verify_token", return_value={"sub": str(uuid4())}):
        with pytest.raises(HTTPException) as exc_info:
            await auth_module.get_current_user(credentials, db)

    assert exc_info.value.status_code == 401
