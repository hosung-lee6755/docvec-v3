"""사용자 그룹 관리 API — v3 권한 모델(문서 ACL의 그룹 주체).

그룹 목록은 로그인 사용자 누구나 볼 수 있다 — 문서 편집자가 허용 목록에 넣을 그룹을
고를 수 있어야 하기 때문이다(이름·설명·인원수만 노출). 생성·수정·삭제·멤버 관리와
멤버 명단 조회는 관리자 전용이다.

그룹을 삭제해도 문서 ACL의 그룹 항목은 지우지 않는다(fail-closed, DocumentAclEntry
docstring 참고). 멤버십 변경은 Qdrant 사본 동기화가 필요 없다 — 사본에는 그룹 id만 있고
누가 그 그룹인지는 요청마다 Postgres에서 다시 읽는다.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, require_admin
from app.db.models.user import User
from app.db.models.user_group import UserGroup, UserGroupMember
from app.db.session import get_db
from app.schemas.access import (
    GroupCreate,
    GroupDetailResponse,
    GroupMemberAdd,
    GroupMemberResponse,
    GroupResponse,
    GroupUpdate,
)
from app.services.audit import log_audit

router = APIRouter()

_DUPLICATE_NAME = "이미 같은 이름의 그룹이 있습니다"


async def _get_group(db: AsyncSession, group_id: UUID) -> UserGroup:
    group = await db.get(UserGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


async def _member_count(db: AsyncSession, group_id) -> int:
    stmt = (
        select(func.count())
        .select_from(UserGroupMember)
        .where(UserGroupMember.group_id == group_id)
    )
    return await db.scalar(stmt) or 0


async def _members(db: AsyncSession, group_id) -> list[GroupMemberResponse]:
    rows = await db.execute(
        select(User.id, User.email, User.username, UserGroupMember.created_at)
        .join(UserGroupMember, UserGroupMember.user_id == User.id)
        .where(UserGroupMember.group_id == group_id)
        .order_by(User.username)
    )
    return [
        GroupMemberResponse(user_id=uid, email=email, username=username, added_at=added_at)
        for uid, email, username, added_at in rows.all()
    ]


def _group_response(group: UserGroup, member_count: int) -> GroupResponse:
    return GroupResponse(
        id=group.id, name=group.name, description=group.description,
        member_count=member_count, created_at=group.created_at,
    )


async def _commit_or_409(db: AsyncSession) -> None:
    """그룹 이름 UNIQUE 위반을 409로 바꾼다."""
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=_DUPLICATE_NAME) from exc


@router.get("")
async def list_groups(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    counts = (
        select(UserGroupMember.group_id, func.count().label("n"))
        .group_by(UserGroupMember.group_id)
        .subquery()
    )
    rows = await db.execute(
        select(UserGroup, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.group_id == UserGroup.id)
        .order_by(UserGroup.name)
    )
    return {"items": [_group_response(g, n) for g, n in rows.all()]}


@router.post("", response_model=GroupResponse, status_code=201)
async def create_group(
    data: GroupCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    group = UserGroup(
        name=data.name.strip(), description=data.description, created_by=str(current_user.id)
    )
    db.add(group)
    try:
        await db.flush()  # id 확보 + 이름 중복을 감사 행 추가 전에 확인
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=_DUPLICATE_NAME) from exc
    log_audit(
        db, str(current_user.id), "group.create", "group", str(group.id),
        detail={"name": group.name},
    )
    await _commit_or_409(db)
    await db.refresh(group)
    return _group_response(group, 0)


@router.get("/{group_id}", response_model=GroupDetailResponse)
async def get_group(
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    group = await _get_group(db, group_id)
    members = await _members(db, group.id)
    return GroupDetailResponse(
        **_group_response(group, len(members)).model_dump(), members=members
    )


@router.patch("/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: UUID,
    data: GroupUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    group = await _get_group(db, group_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("name") is not None:
        changes["name"] = changes["name"].strip()
        group.name = changes["name"]
    else:
        changes.pop("name", None)  # 이름은 비울 수 없다 — null은 "변경 없음"으로 본다
    if "description" in changes:
        group.description = changes["description"]
    if changes:
        log_audit(
            db, str(current_user.id), "group.update", "group", str(group.id), detail=changes
        )
    await _commit_or_409(db)
    await db.refresh(group)
    return _group_response(group, await _member_count(db, group.id))


@router.delete("/{group_id}", status_code=204)
async def delete_group(
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    group = await _get_group(db, group_id)
    log_audit(
        db, str(current_user.id), "group.delete", "group", str(group.id),
        detail={"name": group.name},
    )
    # 멤버 행은 FK ON DELETE CASCADE로 함께 지워진다. 문서 ACL의 그룹 항목은 남긴다.
    await db.delete(group)
    await db.commit()
    return Response(status_code=204)


@router.get("/{group_id}/members")
async def list_group_members(
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    group = await _get_group(db, group_id)
    return {"items": await _members(db, group.id)}


@router.post("/{group_id}/members", response_model=GroupMemberResponse, status_code=201)
async def add_group_member(
    group_id: UUID,
    data: GroupMemberAdd,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    group = await _get_group(db, group_id)
    user = await db.get(User, data.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if await db.get(UserGroupMember, (group.id, user.id)) is not None:
        raise HTTPException(status_code=409, detail="이미 그룹 멤버입니다")
    member = UserGroupMember(group_id=group.id, user_id=user.id, added_by=str(current_user.id))
    db.add(member)
    log_audit(
        db, str(current_user.id), "group.member_add", "group", str(group.id),
        detail={"user_id": str(user.id)},
    )
    try:
        await db.commit()
    except IntegrityError as exc:  # 동시에 같은 사용자를 추가한 경우
        await db.rollback()
        raise HTTPException(status_code=409, detail="이미 그룹 멤버입니다") from exc
    await db.refresh(member)
    return GroupMemberResponse(
        user_id=user.id, email=user.email, username=user.username, added_at=member.created_at
    )


@router.delete("/{group_id}/members/{user_id}", status_code=204)
async def remove_group_member(
    group_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    group = await _get_group(db, group_id)
    member = await db.get(UserGroupMember, (group.id, user_id))
    if member is None:
        raise HTTPException(status_code=404, detail="Group member not found")
    await db.delete(member)
    log_audit(
        db, str(current_user.id), "group.member_remove", "group", str(group.id),
        detail={"user_id": str(user_id)},
    )
    await db.commit()
    return Response(status_code=204)
