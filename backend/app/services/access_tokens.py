"""개인 접근 토큰 발급과 검증(v3 마일스톤 4).

토큰은 `dvp_` + 무작위 43자다. 발급할 때 한 번만 원문을 돌려주고 SHA-256만 저장한다.
검증은 해시로 찾은 뒤 회수, 만료, 계정 상태를 모두 확인한다. 실패 사유는 호출자에게 구분해 알리지 않는다.
"""
import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.access_token import PersonalAccessToken
from app.db.models.user import AUTH_SOURCE_SYSTEM, User

TOKEN_PREFIX = "dvp_"
_DISPLAY_PREFIX_LEN = 8
# 매 요청마다 last_used_at을 쓰지 않도록 이 간격보다 오래됐을 때만 갱신한다
_TOUCH_INTERVAL = timedelta(minutes=5)


class TokenRejected(Exception):
    """토큰을 쓸 수 없다. 사유는 로그에만 남기고 클라이언트에는 401 하나로 답한다."""


class TokenLimitReached(Exception):
    pass


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _new_raw_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


async def active_token_count(db: AsyncSession, user_id) -> int:
    now = datetime.utcnow()
    return await db.scalar(
        select(func.count()).select_from(PersonalAccessToken).where(
            PersonalAccessToken.user_id == str(user_id),
            PersonalAccessToken.revoked_at.is_(None),
            PersonalAccessToken.expires_at > now,
        )
    ) or 0


async def issue_token(db: AsyncSession, user: User, name: str, days: int) -> tuple[PersonalAccessToken, str]:
    """토큰을 만들고 (행, 원문)을 돌려준다. 커밋은 호출자가 한다."""
    if user.auth_source == AUTH_SOURCE_SYSTEM or not user.is_active:
        raise TokenRejected("account cannot hold tokens")
    if await active_token_count(db, user.id) >= settings.mcp_tokens_per_user:
        raise TokenLimitReached()
    raw = _new_raw_token()
    now = datetime.utcnow()
    token = PersonalAccessToken(
        user_id=user.id, name=name, token_prefix=raw[:_DISPLAY_PREFIX_LEN], token_hash=hash_token(raw),
        created_at=now, expires_at=now + timedelta(days=days),
    )
    db.add(token)
    await db.flush()
    return token, raw


async def authenticate_token(db: AsyncSession, raw: str | None) -> tuple[User, PersonalAccessToken]:
    """원문 토큰으로 (사용자, 토큰)을 찾는다. 쓸 수 없으면 TokenRejected."""
    if not raw or not raw.startswith(TOKEN_PREFIX) or len(raw) > 200:
        raise TokenRejected("malformed")
    token = await db.scalar(select(PersonalAccessToken).where(PersonalAccessToken.token_hash == hash_token(raw)))
    if token is None:
        raise TokenRejected("unknown")
    now = datetime.utcnow()
    if token.revoked_at is not None:
        raise TokenRejected("revoked")
    if _naive(token.expires_at) <= now:
        raise TokenRejected("expired")
    user = await db.get(User, token.user_id)
    if user is None or not user.is_active or user.auth_source == AUTH_SOURCE_SYSTEM:
        raise TokenRejected("account unavailable")
    if token.last_used_at is None or _naive(token.last_used_at) + _TOUCH_INTERVAL <= now:
        await db.execute(
            update(PersonalAccessToken).where(PersonalAccessToken.id == token.id).values(last_used_at=now)
        )
        await db.commit()
    return user, token
