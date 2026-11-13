"""AD가 없는 회사의 로그인: 회원가입 끄기, 임시 비밀번호 사용자 제한, 세션 버전으로 기존 로그인 끊기."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1 import deps
from app.api.v1.endpoints import auth as auth_module
from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, verify_token
from app.schemas.auth import UserCreate

_no_rate_limit = patch.object(auth_module, "enforce_rate_limit", MagicMock())
ADMIN_CODE = "bootstrap-code"


def _http_request(path: str = "/api/v1/documents"):
    return SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), url=SimpleNamespace(path=path), cookies={})


def _register_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    return db


async def _register(monkeypatch, *, signup: bool, admin_code: str | None):
    monkeypatch.setattr(settings, "self_signup_enabled", signup)
    monkeypatch.setattr(settings, "admin_signup_code", ADMIN_CODE)
    with _no_rate_limit:
        return await auth_module.register(
            UserCreate(email="new@example.com", username="새직원", password="password123", admin_code=admin_code),
            MagicMock(), _http_request(), _register_db(),
        )


# ------------------------------------------------------------ 회원가입
def test_self_signup_is_off_unless_configured():
    from app.core.config import Settings

    assert Settings.model_fields["self_signup_enabled"].default is False


async def test_register_is_refused_when_self_signup_is_off(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        await _register(monkeypatch, signup=False, admin_code=None)
    assert exc.value.status_code == 403
    assert "관리자에게 계정" in exc.value.detail


async def test_first_admin_can_still_sign_up_with_the_admin_code_when_signup_is_off(monkeypatch):
    result = await _register(monkeypatch, signup=False, admin_code=ADMIN_CODE)
    assert result.user.role == "admin"


async def test_a_wrong_admin_code_does_not_open_signup(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        await _register(monkeypatch, signup=False, admin_code="guess")
    assert exc.value.status_code == 403


async def test_open_signup_still_creates_viewers(monkeypatch):
    result = await _register(monkeypatch, signup=True, admin_code=None)
    assert result.user.role == "viewer"


async def test_login_screen_options_follow_the_settings(monkeypatch):
    monkeypatch.setattr(settings, "self_signup_enabled", False)
    monkeypatch.setattr(settings, "admin_signup_code", ADMIN_CODE)
    assert await auth_module.auth_options() == {
        "self_signup_enabled": False, "admin_code_signup": True, "directory_login": False,
    }

    monkeypatch.setattr(settings, "self_signup_enabled", True)
    monkeypatch.setattr(settings, "ldap_enabled", True)
    assert await auth_module.auth_options() == {
        "self_signup_enabled": False, "admin_code_signup": False, "directory_login": True,
    }


# ------------------------------------------------------------ 세션 버전과 임시 비밀번호
def _user(**fields):
    base = dict(id=str(uuid4()), email="u@example.com", is_active=True, token_version=0, must_change_password=False)
    base.update(fields)
    return SimpleNamespace(**base)


def _db_with(user):
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=user))
    return db


def _bearer(user, version: int | None = None):
    claims = {"sub": user.id}
    if version is not None:
        claims["tv"] = version
    return MagicMock(credentials=create_access_token(claims))


async def test_tokens_issued_before_a_password_reset_stop_working():
    user = _user(token_version=2)

    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user(_bearer(user, 1), _db_with(user), _http_request())
    assert exc.value.status_code == 401 and "다시 로그인" in exc.value.detail

    assert await deps.get_current_user(_bearer(user, 2), _db_with(user), _http_request()) is user


async def test_tokens_without_a_version_count_as_version_zero():
    user = _user()
    assert await deps.get_current_user(_bearer(user), _db_with(user), _http_request()) is user


@pytest.mark.parametrize("path", ["/api/v1/documents", "/api/v1/search", "/api/v1/users"])
async def test_a_temporary_password_user_must_change_it_before_anything_else(path):
    user = _user(must_change_password=True)

    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user(_bearer(user, 0), _db_with(user), _http_request(path))
    assert exc.value.status_code == 403 and "임시 비밀번호" in exc.value.detail


@pytest.mark.parametrize("path", ["/api/v1/users/me", "/api/v1/users/me/password", "/api/v1/auth/me"])
async def test_a_temporary_password_user_can_still_see_themself_and_change_it(path):
    user = _user(must_change_password=True)
    assert await deps.get_current_user(_bearer(user, 0), _db_with(user), _http_request(path)) is user


async def test_refresh_refuses_a_cookie_from_before_the_reset():
    user = _user(token_version=3)
    request = _http_request("/api/v1/auth/refresh")
    request.cookies = {auth_module._REFRESH_COOKIE: create_refresh_token({"sub": user.id, "tv": 2})}
    db = AsyncMock()
    db.scalar.return_value = user

    with _no_rate_limit, pytest.raises(HTTPException) as exc:
        await auth_module.refresh(request, db)
    assert exc.value.status_code == 401

    request.cookies = {auth_module._REFRESH_COOKIE: create_refresh_token({"sub": user.id, "tv": 3})}
    with _no_rate_limit:
        refreshed = await auth_module.refresh(request, db)
    assert verify_token(refreshed.access_token)["tv"] == 3


def test_session_tokens_carry_the_users_version():
    access, refresh = auth_module.session_tokens(_user(token_version=5, email="a@b.c"))
    assert verify_token(access)["tv"] == 5 and verify_token(refresh)["tv"] == 5
