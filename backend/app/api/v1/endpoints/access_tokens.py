"""개인 접근 토큰 관리 API(v3 마일스톤 4).

- 직원: 내 토큰 발급·목록·회수. 원문은 발급 응답에서 한 번만 돌려준다.
- 관리자: 전체 토큰 목록과 회수.
MCP가 꺼져 있으면(`MCP_ENABLED=false`) 발급을 막는다. 목록과 회수는 꺼져 있어도 된다.
"""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, require_admin
from app.core.config import settings
from app.core.rate_limit import enforce_user_rate_limit
from app.db.models.access_token import PersonalAccessToken
from app.db.models.user import User
from app.db.session import get_db
from app.services.access_tokens import TokenLimitReached, TokenRejected, issue_token
from app.services.audit import log_audit

router = APIRouter()

MCP_PATH = "/api/v1/mcp"


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    expires_in_days: int = Field(default_factory=lambda: settings.mcp_token_default_days, ge=1)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("이름을 입력하세요")
        return v

    @field_validator("expires_in_days")
    @classmethod
    def _days(cls, v: int) -> int:
        if v > settings.mcp_token_max_days:
            raise ValueError(f"만료 기간은 최대 {settings.mcp_token_max_days}일입니다")
        return v


def _token_out(t: PersonalAccessToken, user: User | None = None) -> dict:
    now = datetime.utcnow()
    expires = t.expires_at.replace(tzinfo=None) if t.expires_at.tzinfo else t.expires_at
    status = "revoked" if t.revoked_at else ("expired" if expires <= now else "active")
    out = {
        "id": str(t.id), "name": t.name, "token_prefix": t.token_prefix, "created_at": t.created_at,
        "expires_at": t.expires_at, "last_used_at": t.last_used_at, "revoked_at": t.revoked_at, "status": status,
    }
    if user is not None:
        out.update(user_id=str(user.id), username=user.username, email=user.email)
    return out


@router.get("/users/me/access-tokens")
async def list_my_tokens(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = (await db.scalars(
        select(PersonalAccessToken).where(PersonalAccessToken.user_id == str(current_user.id))
        .order_by(PersonalAccessToken.created_at.desc())
    )).all()
    return {
        "mcp_enabled": settings.mcp_enabled, "mcp_path": MCP_PATH,
        "default_days": settings.mcp_token_default_days, "max_days": settings.mcp_token_max_days,
        "items": [_token_out(t) for t in rows],
    }


@router.post("/users/me/access-tokens", status_code=201)
async def create_my_token(
    data: TokenCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
):
    if not settings.mcp_enabled:
        raise HTTPException(status_code=403, detail="외부 에이전트 연결(MCP)이 꺼져 있습니다. 관리자에게 문의하세요.")
    enforce_user_rate_limit(str(current_user.id), "access_token_write", limit=10, window_seconds=60)
    try:
        token, raw = await issue_token(db, current_user, data.name, data.expires_in_days)
    except TokenLimitReached:
        raise HTTPException(
            status_code=409, detail=f"사용 중인 토큰이 {settings.mcp_tokens_per_user}개입니다. 쓰지 않는 토큰을 먼저 회수하세요."
        ) from None
    except TokenRejected:
        raise HTTPException(status_code=403, detail="이 계정은 토큰을 발급할 수 없습니다.") from None
    log_audit(db, str(current_user.id), "access_token.create", "access_token", str(token.id),
              detail={"name": token.name, "expires_at": token.expires_at.isoformat()})
    await db.commit()
    # 원문은 이 응답에만 담는다. 저장하지 않으므로 다시 볼 수 없다.
    return {**_token_out(token), "token": raw}


async def _revoke(db: AsyncSession, token: PersonalAccessToken, actor: User) -> None:
    if token.revoked_at is None:
        token.revoked_at = datetime.utcnow()
        token.revoked_by = actor.id
        log_audit(db, str(actor.id), "access_token.revoke", "access_token", str(token.id),
                  detail={"owner_id": str(token.user_id), "name": token.name})
        await db.commit()


@router.delete("/users/me/access-tokens/{token_id}", status_code=204)
async def revoke_my_token(
    token_id: UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
):
    token = await db.get(PersonalAccessToken, token_id)
    if token is None or str(token.user_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="토큰을 찾을 수 없습니다.")
    await _revoke(db, token, current_user)


@router.get("/admin/access-tokens")
async def list_all_tokens(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    rows = (await db.execute(
        select(PersonalAccessToken, User).join(User, User.id == PersonalAccessToken.user_id)
        .order_by(PersonalAccessToken.created_at.desc()).limit(1000)
    )).all()
    return {"mcp_enabled": settings.mcp_enabled, "items": [_token_out(t, u) for t, u in rows]}


@router.delete("/admin/access-tokens/{token_id}", status_code=204)
async def revoke_any_token(
    token_id: UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
):
    require_admin(current_user)
    token = await db.get(PersonalAccessToken, token_id)
    if token is None:
        raise HTTPException(status_code=404, detail="토큰을 찾을 수 없습니다.")
    await _revoke(db, token, current_user)
