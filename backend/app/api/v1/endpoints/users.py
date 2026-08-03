from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, require_admin
from app.core.crypto import encrypt_secret
from app.core.security import get_password_hash, verify_password
from app.db.models.chat_conversation import ChatConversation
from app.db.models.chat_message import ChatMessage
from app.db.models.collection import Collection
from app.db.models.collection_member import CollectionMember
from app.db.models.document_revision import DocumentTextRevision
from app.db.models.project import Project
from app.db.models.project_member import ProjectMember
from app.db.models.user import User
from app.db.models.user_api_key import UserApiKey
from app.db.session import get_db
from app.services.audit import log_audit

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


@router.get("")
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    result = await db.execute(select(User))
    users = result.scalars().all()
    return {"items": [UserResponse.model_validate(u) for u in users]}


class ProfileUpdate(BaseModel):
    username: str = Field(min_length=1, max_length=255)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


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
    require_admin(current_user)
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
    log_audit(
        db, str(current_user.id), "user.update", "user", str(user.id),
        detail={"role": data.role, "is_active": data.is_active},
    )
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    if str(user_id) == SYSTEM_USER_ID:
        raise HTTPException(status_code=403, detail="System user cannot be deleted")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 계정이 소유한 프로젝트/컬렉션/문서는 users.id를 참조하는 FK에
    # ON DELETE CASCADE가 하나도 없어 그냥 db.delete(user)만 하면 항상
    # IntegrityError로 실패한다(실제로 프로젝트/컬렉션을 소유한 계정 3개가
    # 삭제 안 되는 문제로 확인됨, 2026-07-29) — project/collection 삭제와
    # 동일한 cascade 헬퍼를 재사용해 소유 리소스를 먼저 정리한다.
    from app.api.v1.endpoints.collections import cascade_delete_collection
    from app.api.v1.endpoints.projects import cascade_delete_project

    uid = str(user_id)
    owned_projects = (await db.scalars(select(Project).where(Project.created_by == uid))).all()
    for project in owned_projects:
        await cascade_delete_project(db, project)

    # 위에서 이미 삭제된 프로젝트 소속 컬렉션은 다시 조회되지 않으므로, 남는
    # 건 프로젝트 없이 독립적이거나 다른 사람 프로젝트 아래 있던 컬렉션뿐.
    owned_collections = (
        await db.scalars(select(Collection).where(Collection.created_by == uid))
    ).all()
    for collection in owned_collections:
        await cascade_delete_collection(db, collection)

    # 이 계정이 "멤버"로 참여 중인 남의 프로젝트/컬렉션 — invited_by는 항상
    # 초대한 쪽(소유자) 자신이라(invite 엔드포인트가 소유자만 허용) 위에서
    # 소유 프로젝트/컬렉션을 지울 때 이미 함께 삭제됐다. 남은 건 이 계정이
    # user_id(멤버 본인)인 행뿐이다.
    await db.execute(delete(ProjectMember).where(ProjectMember.user_id == uid))
    await db.execute(delete(CollectionMember).where(CollectionMember.user_id == uid))

    conv_ids_subq = select(ChatConversation.id).where(ChatConversation.user_id == uid)
    await db.execute(delete(ChatMessage).where(ChatMessage.conversation_id.in_(conv_ids_subq)))
    await db.execute(delete(ChatConversation).where(ChatConversation.user_id == uid))

    await db.execute(delete(UserApiKey).where(UserApiKey.user_id == uid))

    # nullable — 리비전 이력 자체는 보존하고 작성자만 비운다.
    await db.execute(
        update(DocumentTextRevision)
        .where(DocumentTextRevision.created_by == uid)
        .values(created_by=None)
    )

    log_audit(db, str(current_user.id), "user.delete", "user", str(user.id))
    await db.delete(user)
    try:
        await db.commit()
    except IntegrityError:
        # 위 cascade가 다루지 않는 공유 리소스(예: 사전 항목처럼 소유자만
        # 있고 프로젝트/컬렉션에 속하지 않는 not-null 참조)가 남아있는 경우
        # — 원인 불명 500 대신 무엇이 막고 있는지 알 수 있게 명확히 실패시킨다.
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="이 계정이 소유한 다른 데이터가 남아 있어 삭제할 수 없습니다. "
            "관리자에게 문의하세요.",
        )


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
    log_audit(db, str(current_user.id), "api_key.set", "user_api_key", provider)
    await db.commit()
    return {"message": "저장되었습니다", "provider": provider}


@router.delete("/me/api-keys/{provider}")
async def delete_my_api_key(
    provider: Literal["openai", "anthropic"],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    log_audit(db, str(current_user.id), "api_key.delete", "user_api_key", provider)
    await db.execute(
        delete(UserApiKey).where(
            UserApiKey.user_id == str(current_user.id),
            UserApiKey.provider == provider,
        )
    )
    await db.commit()
    return {"message": "삭제되었습니다"}
