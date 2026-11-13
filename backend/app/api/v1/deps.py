from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_token
from app.db.models.user import User
from app.db.session import get_db

_bearer = HTTPBearer()

# 임시 비밀번호로 로그인한 사용자도 부를 수 있는 경로. 자기 정보를 보고 비밀번호를 바꾸고 로그아웃하는 데 필요한 것만 둔다.
_PASSWORD_CHANGE_PATHS = ("/users/me", "/users/me/password")


def ensure_session_current(payload: dict, user: User) -> None:
    """토큰의 세션 버전(tv)이 사용자의 현재 버전과 다르면 거절한다. 비밀번호를 초기화하면 버전이 올라가
    그 전에 발급한 토큰이 모두 끊긴다. tv가 없는 토큰(이 기능 전에 발급)은 0으로 본다."""
    if int(payload.get("tv") or 0) != int(user.token_version or 0):
        raise HTTPException(status_code=401, detail="로그인이 만료되었습니다. 다시 로그인하세요.")


def _is_password_change_path(path: str) -> bool:
    return path.endswith(_PASSWORD_CHANGE_PATHS) or "/auth/" in path


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> User:
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
    ensure_session_current(payload, user)
    if user.must_change_password and request is not None and not _is_password_change_path(request.url.path):
        raise HTTPException(
            status_code=403,
            detail="임시 비밀번호를 먼저 바꿔야 합니다. 새 비밀번호를 정한 뒤 다시 시도하세요.",
        )
    return user


def require_admin(current_user: User) -> None:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
