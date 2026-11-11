import asyncio
import hmac
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rate_limit import enforce_rate_limit
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_password,
    verify_token,
)
from app.db.models.user import AUTH_SOURCE_LDAP, AUTH_SOURCE_LOCAL, User
from app.db.session import get_db
from app.schemas.auth import LoginRequest, LoginResponse, TokenResponse, UserCreate, UserResponse
from app.services.audit import log_audit
from app.services.directory import get_directory_client
from app.services.directory.ldap_client import DirectoryUnavailable
from app.services.directory.provisioning import DirectoryConflict, provision_login

router = APIRouter()
_bearer = HTTPBearer()

_REFRESH_COOKIE = "refresh_token"
_REFRESH_MAX_AGE = 60 * 60 * 24 * 7


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
        max_age=_REFRESH_MAX_AGE,
    )


@router.post("/register", response_model=LoginResponse, status_code=201)
async def register(
    request: UserCreate, response: Response, http_request: Request, db: AsyncSession = Depends(get_db)
):
    # Rate limit by IP and by email (per-account throttle prevents lockout when
    # one attacker floods from behind a shared proxy IP).
    enforce_rate_limit(http_request, "register", limit=5, window_seconds=60, email=request.email)
    if settings.ldap_enabled:
        # 사내 AD를 쓰면 자가 가입을 막는다. 열어 두면 아직 로그인하지 않은 직원의 이메일로 로컬 계정을
        # 먼저 만들어, 그 직원의 AD 로그인을 가로막거나 그 이름으로 행세할 수 있다.
        raise HTTPException(status_code=403, detail="사내 계정(AD)으로 로그인하세요. 별도 회원가입은 받지 않습니다.")

    result = await db.execute(select(User).where(User.email == request.email))
    if result.scalar_one_or_none():
        # Deliberately generic — a distinct "already registered" message lets
        # an attacker enumerate every registered email address.
        raise HTTPException(status_code=409, detail="Registration failed")

    # Use constant-time comparison for admin_code to prevent timing attacks.
    # Also rate-limit attempts that supply an admin_code more strictly.
    granted_admin = False
    if bool(settings.admin_signup_code) and request.admin_code is not None:
        # Stricter rate limit on admin code attempts (prevent brute-force)
        enforce_rate_limit(http_request, "register:admin_code", limit=3, window_seconds=300, email=request.email)
        granted_admin = hmac.compare_digest(
            request.admin_code,
            settings.admin_signup_code,
        )
    user = User(
        id=uuid4(),
        email=request.email,
        username=request.username,
        hashed_password=get_password_hash(request.password),
        role="admin" if granted_admin else "viewer",
        is_active=True,
        auth_source=AUTH_SOURCE_LOCAL,
    )
    db.add(user)
    await db.flush()
    log_audit(db, str(user.id), "auth.register", "user", str(user.id), ip_address=http_request.client.host)
    await db.commit()
    await db.refresh(user)

    access_token = create_access_token({"sub": str(user.id), "email": user.email})
    refresh_token = create_refresh_token({"sub": str(user.id)})
    _set_refresh_cookie(response, refresh_token)

    return LoginResponse(
        user=UserResponse.model_validate(user),
        access_token=access_token,
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest, response: Response, http_request: Request, db: AsyncSession = Depends(get_db)
):
    # Rate limit by IP and by email (per-account throttle prevents lockout when
    # one attacker floods from behind a shared proxy IP).
    login_id = request.email.strip()
    # 대소문자·공백만 바꿔 계정별 제한을 피하지 못하게 정규화한 값으로 센다(AD 잠금 정책 보호)
    enforce_rate_limit(http_request, "login", limit=5, window_seconds=60, email=login_id.lower())
    ip = http_request.client.host

    async def _fail(status: int, detail: str, reason: str | None = None, user_id: str | None = None):
        audit_detail = {"email": login_id} if user_id is None else {}
        if reason:
            audit_detail["reason"] = reason
        log_audit(db, user_id, "auth.login_failed", "user", user_id, detail=audit_detail, ip_address=ip)
        await db.commit()
        raise HTTPException(status_code=status, detail=detail)

    result = await db.execute(select(User).where(User.email == login_id.lower()))
    user = result.scalar_one_or_none() or await db.scalar(select(User).where(User.email == login_id))
    source = AUTH_SOURCE_LOCAL

    if user is not None and user.auth_source == AUTH_SOURCE_LOCAL:
        if not verify_password(request.password, user.hashed_password):
            await _fail(401, "Invalid credentials")
    elif user is None or user.auth_source == AUTH_SOURCE_LDAP:
        # 로컬 계정이 아니면 AD로 확인한다. 시스템 계정(커넥터)은 어떤 경로로도 로그인할 수 없다.
        user = await _directory_login(db, login_id, request.password, _fail)
        source = AUTH_SOURCE_LDAP
    else:
        await _fail(401, "Invalid credentials")
    if not user.is_active:
        log_audit(
            db, str(user.id), "auth.login_failed", "user", str(user.id),
            detail={"reason": "disabled"}, ip_address=http_request.client.host,
        )
        await db.commit()
        raise HTTPException(status_code=401, detail="User account is disabled")

    access_token = create_access_token({"sub": str(user.id), "email": user.email})
    refresh_token = create_refresh_token({"sub": str(user.id)})
    _set_refresh_cookie(response, refresh_token)

    log_audit(
        db, str(user.id), "auth.login", "user", str(user.id),
        detail={"source": source} if source != AUTH_SOURCE_LOCAL else None, ip_address=ip,
    )
    await db.commit()
    await db.refresh(user)

    return LoginResponse(
        user=UserResponse.model_validate(user),
        access_token=access_token,
    )


async def _directory_login(db: AsyncSession, login_id: str, password: str, fail) -> User:
    """AD로 자격 증명을 확인하고 계정을 만들거나 갱신한다. 실패는 fail()이 감사 후 예외로 바꾼다."""
    client = get_directory_client()
    if client is None:
        await fail(401, "Invalid credentials")
    try:
        duser = await asyncio.to_thread(client.authenticate, login_id, password)
        groups = await asyncio.to_thread(client.user_groups, duser.dn) if duser else []
    except DirectoryUnavailable:
        await fail(503, "사내 계정 서버에 연결할 수 없습니다. 잠시 후 다시 시도하세요.", reason="directory_unavailable")
    if duser is None:
        await fail(401, "Invalid credentials")
    try:
        return await db.run_sync(lambda s: provision_login(s, duser, groups, settings.ldap_admin_group_dn))
    except DirectoryConflict:
        await db.rollback()
        await fail(409, "같은 이메일을 쓰는 로컬 계정이 있습니다. 관리자에게 문의하세요.", reason="email_conflict")


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, db: AsyncSession = Depends(get_db)):
    enforce_rate_limit(request, "refresh", limit=30, window_seconds=60)

    token = request.cookies.get(_REFRESH_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")

    payload = verify_token(token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user = await db.scalar(select(User).where(User.id == payload.get("sub")))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    access_token = create_access_token({"sub": payload.get("sub")})
    return TokenResponse(access_token=access_token)


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(_REFRESH_COOKIE)
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
):
    payload = verify_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    # Reject refresh tokens used as bearer auth. Accept tokens without type
    # (legacy) for backward compatibility with already-issued tokens.
    if payload.get("type") == "refresh":
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == payload.get("sub")))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="User account is disabled")

    return user
