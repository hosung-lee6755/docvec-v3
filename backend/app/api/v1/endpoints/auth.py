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
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.auth import LoginRequest, LoginResponse, TokenResponse, UserCreate, UserResponse
from app.services.audit import log_audit

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
    enforce_rate_limit(http_request, "login", limit=5, window_seconds=60, email=request.email)

    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(request.password, user.hashed_password):
        log_audit(
            db, None, "auth.login_failed", "user", None,
            detail={"email": request.email}, ip_address=http_request.client.host,
        )
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")
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

    log_audit(db, str(user.id), "auth.login", "user", str(user.id), ip_address=http_request.client.host)
    await db.commit()
    await db.refresh(user)

    return LoginResponse(
        user=UserResponse.model_validate(user),
        access_token=access_token,
    )


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
