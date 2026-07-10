from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.core.crypto import encrypt_secret
from app.core.security import get_password_hash, verify_password
from app.db.models.user import User
from app.db.models.user_api_key import UserApiKey
from app.db.session import get_db

SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000001"

router = APIRouter()


class UserResponse(BaseModel):
    id: UUID
    email: str
    username: str
    role: str
    is_active: bool
    system_prompt: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    role: Literal["viewer", "editor", "admin"] | None = None
    is_active: bool | None = None


def _require_admin(current_user: User) -> None:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


@router.get("")
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    result = await db.execute(select(User))
    users = result.scalars().all()
    return {"items": [UserResponse.model_validate(u) for u in users]}


class ProfileUpdate(BaseModel):
    username: str = Field(min_length=1, max_length=255)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


# Registered before PATCH "/{user_id}" below — Starlette matches routes in
# registration order, and "/{user_id}" would otherwise try (and fail) to parse
# the literal "me" as a UUID before this handler is ever reached.
@router.get("/me", response_model=UserResponse)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
):
    return UserResponse.model_validate(current_user)


@router.patch("/me", response_model=UserResponse)
async def update_my_profile(
    data: ProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current_user.username = data.username.strip()
    await db.commit()
    await db.refresh(current_user)
    return UserResponse.model_validate(current_user)


@router.post("/me/password")
async def change_my_password(
    data: PasswordChange,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=403, detail="현재 비밀번호가 일치하지 않습니다")
    current_user.hashed_password = get_password_hash(data.new_password)
    await db.commit()
    return {"message": "비밀번호가 변경되었습니다"}


class SystemPromptUpdate(BaseModel):
    system_prompt: str | None = None


@router.put("/me/system-prompt", response_model=UserResponse)
async def set_my_system_prompt(
    data: SystemPromptUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current_user.system_prompt = (data.system_prompt or "").strip() or None
    await db.commit()
    await db.refresh(current_user)
    return UserResponse.model_validate(current_user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    if str(user_id) == SYSTEM_USER_ID:
        raise HTTPException(status_code=403, detail="System user cannot be modified")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if data.role is not None:
        user.role = data.role
    if data.is_active is not None:
        user.is_active = data.is_active
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    if str(user_id) == SYSTEM_USER_ID:
        raise HTTPException(status_code=403, detail="System user cannot be deleted")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(user)
    await db.commit()


_API_KEY_PROVIDERS = ("openai", "anthropic")


class ApiKeyUpdate(BaseModel):
    api_key: str


@router.get("/me/api-keys")
async def list_my_api_keys(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(UserApiKey).where(UserApiKey.user_id == str(current_user.id))
    )
    # Never return the encrypted_key/plaintext — only whether a provider is
    # registered, so the settings UI can show "등록됨" without ever handling the
    # secret again after the initial PUT.
    rows = {row.provider: row for row in result.scalars().all()}
    return {
        "items": [
            {
                "provider": provider,
                "registered": provider in rows,
                "updated_at": rows[provider].updated_at if provider in rows else None,
            }
            for provider in _API_KEY_PROVIDERS
        ]
    }


@router.put("/me/api-keys/{provider}")
async def set_my_api_key(
    provider: Literal["openai", "anthropic"],
    data: ApiKeyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    api_key = data.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=422, detail="api_key is required")

    encrypted = encrypt_secret(api_key)
    existing = await db.scalar(
        select(UserApiKey).where(
            UserApiKey.user_id == str(current_user.id),
            UserApiKey.provider == provider,
        )
    )
    if existing:
        existing.encrypted_key = encrypted
        existing.updated_at = datetime.utcnow()
    else:
        db.add(
            UserApiKey(
                user_id=str(current_user.id),
                provider=provider,
                encrypted_key=encrypted,
            )
        )
    await db.commit()
    return {"message": "저장되었습니다", "provider": provider}


@router.delete("/me/api-keys/{provider}")
async def delete_my_api_key(
    provider: Literal["openai", "anthropic"],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await db.execute(
        delete(UserApiKey).where(
            UserApiKey.user_id == str(current_user.id),
            UserApiKey.provider == provider,
        )
    )
    await db.commit()
    return {"message": "삭제되었습니다"}
