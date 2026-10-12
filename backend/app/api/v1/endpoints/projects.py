from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.api.v1.permissions import check_project_access
from app.core.crypto import encrypt_secret
from app.db.models.chat_conversation import ChatConversation
from app.db.models.chat_message import ChatMessage
from app.db.models.collection import Collection
from app.db.models.project import Project
from app.db.models.project_api_key import ProjectApiKey
from app.db.models.project_member import ProjectMember
from app.db.models.user import User
from app.db.models.workflow import WorkflowBlockInstance, WorkflowDefinition, WorkflowEdge, WorkflowVersion
from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep
from app.db.session import get_db
from app.services.audit import log_audit

router = APIRouter()

_API_KEY_PROVIDERS = ("openai", "anthropic")


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)


class ProjectMemberInvite(BaseModel):
    email: str
    role: Literal["viewer", "editor"] = "viewer"


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    system_prompt: str | None
    created_at: datetime
    updated_at: datetime
    collection_count: int
    member_count: int
    is_owner: bool
    role: str | None

    class Config:
        from_attributes = True


class ProjectSystemPromptUpdate(BaseModel):
    system_prompt: str | None = Field(None, max_length=5000)


class ProjectApiKeyUpdate(BaseModel):
    api_key: str = Field(..., min_length=1, max_length=2000)


async def _build_project_response(db: AsyncSession, project: Project, current_user: User) -> dict:
    # Mirrors list_projects' per-item computation so single-project fetches (used by
    # the workspace header/settings modal for owner-gated UI, e.g. AI 관리 editing)
    # see the same is_owner/role instead of silently defaulting to false.
    collection_count = await db.scalar(
        select(func.count(Collection.id)).where(Collection.project_id == project.id)
    ) or 0
    member_count = await db.scalar(
        select(func.count(ProjectMember.user_id)).where(ProjectMember.project_id == project.id)
    ) or 0
    is_owner = str(project.created_by) == str(current_user.id)
    role = "owner"
    if not is_owner:
        membership = await db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == str(current_user.id),
            )
        )
        role = membership.role if membership else None
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "system_prompt": project.system_prompt,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "collection_count": collection_count,
        "member_count": member_count + 1,
        "is_owner": is_owner,
        "role": role,
    }


@router.post("", response_model=ProjectResponse)
async def create_project(
    data: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = Project(
        name=data.name,
        description=data.description,
        created_by=str(current_user.id),
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return await _build_project_response(db, project, current_user)


@router.get("")
async def list_projects(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    member_roles_result = await db.execute(
        select(ProjectMember.project_id, ProjectMember.role).where(
            ProjectMember.user_id == str(current_user.id)
        )
    )
    member_roles = dict(member_roles_result.all())

    filters = [Project.created_by == str(current_user.id)]
    if member_roles:
        filters.append(Project.id.in_(member_roles.keys()))
    result = await db.execute(select(Project).where(or_(*filters)).order_by(Project.created_at))
    projects = result.scalars().all()

    collection_counts = dict(
        (
            await db.execute(
                select(Collection.project_id, func.count(Collection.id))
                .where(Collection.project_id.in_([p.id for p in projects]))
                .group_by(Collection.project_id)
            )
        ).all()
    )
    member_counts = dict(
        (
            await db.execute(
                select(ProjectMember.project_id, func.count(ProjectMember.user_id))
                .where(ProjectMember.project_id.in_([p.id for p in projects]))
                .group_by(ProjectMember.project_id)
            )
        ).all()
    )

    items = [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "created_at": p.created_at,
            "updated_at": p.updated_at,
            "collection_count": collection_counts.get(p.id, 0),
            # +1 for the owner, who has no ProjectMember row of their own.
            "member_count": member_counts.get(p.id, 0) + 1,
            "is_owner": str(p.created_by) == str(current_user.id),
            "role": "owner" if str(p.created_by) == str(current_user.id) else member_roles.get(p.id),
        }
        for p in projects
    ]
    return {"items": items}


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await check_project_access(db, project_id, current_user, min_role="viewer")
    return await _build_project_response(db, project, current_user)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    data: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if str(project.created_by) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")
    if data.name is not None:
        project.name = data.name
    if data.description is not None:
        project.description = data.description
    project.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    await db.refresh(project)
    return await _build_project_response(db, project, current_user)


async def cascade_delete_project(db: AsyncSession, project: Project) -> None:
    """Delete a project and everything that FKs into it (no ON DELETE CASCADE
    exists at the DB level for any of these) — same contract as
    cascade_delete_collection: caller is responsible for the access check and
    commit. Extracted so delete_user (users.py) can reuse this instead of
    duplicating it when cascading a deleted account's own projects."""
    from app.api.v1.endpoints.collections import cascade_delete_collection

    collections = (
        await db.scalars(select(Collection).where(Collection.project_id == project.id))
    ).all()
    for collection in collections:
        await cascade_delete_collection(db, collection)

    # Everything below has no ON DELETE CASCADE from projects.id (same gap as
    # cascade_delete_collection above), so it must be cleared manually too.
    conv_ids_subq = select(ChatConversation.id).where(ChatConversation.project_id == project.id)
    await db.execute(delete(ChatMessage).where(ChatMessage.conversation_id.in_(conv_ids_subq)))
    await db.execute(delete(ChatConversation).where(ChatConversation.project_id == project.id))

    await db.execute(delete(ProjectApiKey).where(ProjectApiKey.project_id == project.id))

    workflow_ids_subq = select(WorkflowDefinition.id).where(WorkflowDefinition.project_id == project.id)
    version_ids_subq = select(WorkflowVersion.id).where(WorkflowVersion.workflow_id.in_(workflow_ids_subq))
    run_ids_subq = select(WorkflowRun.id).where(WorkflowRun.version_id.in_(version_ids_subq))
    await db.execute(delete(WorkflowRunStep).where(WorkflowRunStep.run_id.in_(run_ids_subq)))
    await db.execute(delete(WorkflowRun).where(WorkflowRun.version_id.in_(version_ids_subq)))
    await db.execute(delete(WorkflowEdge).where(WorkflowEdge.version_id.in_(version_ids_subq)))
    await db.execute(delete(WorkflowBlockInstance).where(WorkflowBlockInstance.version_id.in_(version_ids_subq)))
    await db.execute(delete(WorkflowVersion).where(WorkflowVersion.workflow_id.in_(workflow_ids_subq)))
    await db.execute(delete(WorkflowDefinition).where(WorkflowDefinition.project_id == project.id))

    await db.execute(delete(ProjectMember).where(ProjectMember.project_id == project.id))
    await db.flush()
    await db.delete(project)


@router.delete("/{project_id}")
async def delete_project(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    # 관리자는 소유자가 아니어도 삭제 가능 — 계정 정리 시 관리자가 남의
    # 프로젝트를 대신 정리해야 하는 상황이 실제로 있었다(2026-07-29).
    if str(project.created_by) != str(current_user.id) and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    await cascade_delete_project(db, project)
    await db.commit()
    return {"message": "Project deleted"}


@router.post("/{project_id}/invite")
async def invite_project_member(
    project_id: UUID,
    data: ProjectMemberInvite,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if str(project.created_by) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    invitee = await db.scalar(select(User).where(User.email == data.email))
    if not invitee:
        raise HTTPException(status_code=404, detail="가입된 사용자만 초대할 수 있습니다")
    if str(invitee.id) == str(current_user.id):
        raise HTTPException(status_code=400, detail="자기 자신은 초대할 수 없습니다")

    membership = await db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == str(invitee.id),
        )
    )
    if membership:
        membership.role = data.role
    else:
        db.add(ProjectMember(
            project_id=str(project_id),
            user_id=str(invitee.id),
            role=data.role,
            invited_by=str(current_user.id),
        ))
    log_audit(
        db, str(current_user.id), "project.member_invite", "project", str(project_id),
        detail={"invitee_email": invitee.email, "role": data.role},
    )
    await db.commit()
    return {"message": "초대되었습니다", "email": invitee.email, "role": data.role}


@router.get("/{project_id}/members")
async def list_project_members(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await check_project_access(db, project_id, current_user, min_role="viewer")

    owner = await db.scalar(select(User).where(User.id == project.created_by))
    rows = (
        await db.execute(
            select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project_id)
        )
    ).all()

    members = []
    if owner:
        members.append({
            "user_id": owner.id, "email": owner.email, "username": owner.username,
            "role": "owner", "created_at": project.created_at,
        })
    for member, user in rows:
        members.append({
            "user_id": user.id, "email": user.email, "username": user.username,
            "role": member.role, "created_at": member.created_at,
        })
    return {"items": members}


@router.put("/{project_id}/system-prompt", response_model=ProjectResponse)
async def set_project_system_prompt(
    project_id: UUID,
    data: ProjectSystemPromptUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if str(project.created_by) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")
    project.system_prompt = (data.system_prompt or "").strip() or None
    project.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    await db.refresh(project)
    return await _build_project_response(db, project, current_user)


@router.get("/{project_id}/api-keys")
async def list_project_api_keys(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if str(project.created_by) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    result = await db.execute(
        select(ProjectApiKey).where(ProjectApiKey.project_id == project_id)
    )
    # Never return the encrypted_key/plaintext — only whether a provider is
    # registered, mirroring the personal /users/me/api-keys endpoint.
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


@router.put("/{project_id}/api-keys/{provider}")
async def set_project_api_key(
    project_id: UUID,
    provider: Literal["openai", "anthropic"],
    data: ProjectApiKeyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if str(project.created_by) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    from app.core.rate_limit import enforce_user_rate_limit

    enforce_user_rate_limit(str(current_user.id), "api_key_write", limit=10, window_seconds=60)
    api_key = data.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=422, detail="api_key is required")

    encrypted = encrypt_secret(api_key)
    existing = await db.scalar(
        select(ProjectApiKey).where(
            ProjectApiKey.project_id == project_id,
            ProjectApiKey.provider == provider,
        )
    )
    if existing:
        existing.encrypted_key = encrypted
        existing.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        db.add(
            ProjectApiKey(
                project_id=str(project_id),
                provider=provider,
                encrypted_key=encrypted,
            )
        )
    await db.commit()
    return {"message": "저장되었습니다", "provider": provider}


@router.delete("/{project_id}/api-keys/{provider}")
async def delete_project_api_key(
    project_id: UUID,
    provider: Literal["openai", "anthropic"],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if str(project.created_by) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    await db.execute(
        delete(ProjectApiKey).where(
            ProjectApiKey.project_id == project_id,
            ProjectApiKey.provider == provider,
        )
    )
    await db.commit()
    return {"message": "삭제되었습니다"}


@router.delete("/{project_id}/members/{user_id}")
async def remove_project_member(
    project_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if str(project.created_by) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")
    if str(user_id) == str(project.created_by):
        raise HTTPException(status_code=400, detail="소유자는 제거할 수 없습니다")

    await db.execute(
        delete(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == str(user_id),
        )
    )
    log_audit(
        db, str(current_user.id), "project.member_remove", "project", str(project_id),
        detail={"removed_user_id": str(user_id)},
    )
    await db.commit()
    return {"message": "멤버가 제거되었습니다"}
