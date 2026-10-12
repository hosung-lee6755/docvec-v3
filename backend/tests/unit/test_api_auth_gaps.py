"""auth.py 엔드포인트의 관리자 가입 코드/토큰 거부 분기 보강 — DB·Redis 모킹."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import auth as auth_module
from app.schemas.auth import UserCreate

ADMIN_CODE = "test-only-admin-code"


def _http_request(cookies: dict | None = None):
    req = MagicMock()
    req.client.host = "127.0.0.1"
    req.cookies = cookies or {}
    return req


def _register_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    return db


async def _register(admin_code, configured_code):
    db = _register_db()
    limiter = MagicMock()
    with patch.object(auth_module, "enforce_rate_limit", limiter), patch.object(auth_module.settings, "admin_signup_code", configured_code):
        result = await auth_module.register(
            UserCreate(email="a@test.com", username="adm", password="password123", admin_code=admin_code),
            MagicMock(), _http_request(), db,
        )
    return result, limiter


async def test_register_with_correct_admin_code_grants_admin_with_stricter_rate_limit():
    result, limiter = await _register(ADMIN_CODE, ADMIN_CODE)

    assert result.user.role == "admin"
    buckets = [call.args[1] for call in limiter.call_args_list]
    assert buckets == ["register", "register:admin_code"]


async def test_register_with_wrong_admin_code_stays_viewer():
    result, _ = await _register("wrong-code", ADMIN_CODE)

    assert result.user.role == "viewer"


async def test_register_ignores_admin_code_when_none_is_configured():
    result, limiter = await _register("anything", "")

    assert result.user.role == "viewer"
    assert [call.args[1] for call in limiter.call_args_list] == ["register"]  # 코드 시도 제한도 걸지 않는다


# ----------------------------------------------------------------- refresh
async def test_refresh_rejects_invalid_or_wrong_type_token():
    db = AsyncMock()
    request = _http_request({"refresh_token": "tok"})

    with patch.object(auth_module, "enforce_rate_limit", MagicMock()):
        with patch.object(auth_module, "verify_token", return_value=None):
            with pytest.raises(HTTPException) as invalid:
                await auth_module.refresh(request, db)
        with patch.object(auth_module, "verify_token", return_value={"type": "access", "sub": "u"}):
            with pytest.raises(HTTPException) as wrong_type:
                await auth_module.refresh(request, db)

    assert invalid.value.status_code == wrong_type.value.status_code == 401
    db.scalar.assert_not_called()


async def test_refresh_rejects_token_of_unknown_user():
    db = AsyncMock()
    db.scalar.return_value = None

    with (
        patch.object(auth_module, "enforce_rate_limit", MagicMock()),
        patch.object(auth_module, "verify_token", return_value={"type": "refresh", "sub": str(uuid4())}),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await auth_module.refresh(_http_request({"refresh_token": "tok"}), db)

    assert exc_info.value.status_code == 401


async def test_logout_clears_refresh_cookie():
    response = MagicMock()

    result = await auth_module.logout(response)

    response.delete_cookie.assert_called_once_with("refresh_token")
    assert result == {"message": "Logged out successfully"}


# ----------------------------------------------------------- get_current_user
def _credentials(token: str = "tok"):
    return MagicMock(credentials=token)


def _db_with_user(user):
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=user))
    return db


async def test_me_rejects_invalid_token():
    with patch.object(auth_module, "verify_token", return_value=None):
        with pytest.raises(HTTPException) as exc_info:
            await auth_module.get_current_user(_credentials(), AsyncMock())

    assert (exc_info.value.status_code, exc_info.value.detail) == (401, "Invalid token")


async def test_me_rejects_refresh_token_used_as_bearer():
    db = AsyncMock()

    with patch.object(auth_module, "verify_token", return_value={"type": "refresh", "sub": "u"}):
        with pytest.raises(HTTPException) as exc_info:
            await auth_module.get_current_user(_credentials(), db)

    assert exc_info.value.status_code == 401
    db.execute.assert_not_called()


async def test_me_returns_404_for_deleted_user_and_accepts_legacy_untyped_token():
    with patch.object(auth_module, "verify_token", return_value={"sub": "u"}):  # type 없는 구 토큰
        with pytest.raises(HTTPException) as exc_info:
            await auth_module.get_current_user(_credentials(), _db_with_user(None))
        user = MagicMock(is_active=True)
        assert await auth_module.get_current_user(_credentials(), _db_with_user(user)) is user

    assert exc_info.value.status_code == 404
