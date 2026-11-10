from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.collection import Collection
from app.db.models.collection_member import CollectionMember
from app.db.models.document import Document
from app.db.models.project import Project
from app.db.models.project_member import ProjectMember
from app.db.models.user import User

_ROLE_RANK = {"viewer": 0, "editor": 1}


async def check_project_access(
    db: AsyncSession,
    project_id: UUID | str,
    user: User,
    min_role: str = "viewer",
) -> Project:
    project = await db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if str(project.created_by) == str(user.id):
        return project

    membership = await db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == str(user.id),
        )
    )
    if not membership or _ROLE_RANK[membership.role] < _ROLE_RANK[min_role]:
        raise HTTPException(status_code=403, detail="Access denied")
    return project


async def accessible_project_ids(db: AsyncSession, user: User) -> list[str]:
    owned = await db.scalars(select(Project.id).where(Project.created_by == str(user.id)))
    member_of = await db.scalars(
        select(ProjectMember.project_id).where(ProjectMember.user_id == str(user.id))
    )
    return list({str(pid) for pid in [*owned.all(), *member_of.all()]})


async def check_collection_access(
    db: AsyncSession,
    collection_id: UUID | str,
    user: User,
    min_role: str = "viewer",
) -> Collection:
    collection = await db.scalar(select(Collection).where(Collection.id == collection_id))
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    if str(collection.created_by) == str(user.id):
        return collection

    # A project-scoped, non-restricted collection is auto-accessible to every
    # project member — that's the whole point of grouping collections under a
    # project instead of inviting people collection-by-collection. restrict_to_members
    # opts a specific collection out of that inheritance so a subset of the project
    # can be excluded, in which case only explicit CollectionMember rows count.
    if collection.project_id and not collection.restrict_to_members:
        project = await db.scalar(select(Project).where(Project.id == collection.project_id))
        if project and str(project.created_by) == str(user.id):
            return collection
        project_membership = await db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == collection.project_id,
                ProjectMember.user_id == str(user.id),
            )
        )
        if project_membership and _ROLE_RANK[project_membership.role] >= _ROLE_RANK[min_role]:
            return collection

    membership = await db.scalar(
        select(CollectionMember).where(
            CollectionMember.collection_id == collection_id,
            CollectionMember.user_id == str(user.id),
        )
    )
    if not membership or _ROLE_RANK[membership.role] < _ROLE_RANK[min_role]:
        raise HTTPException(status_code=403, detail="Access denied")
    return collection


async def check_document_access(
    db: AsyncSession,
    doc: Document,
    user: User,
    min_role: str = "viewer",
) -> None:
    """문서 열람(min_role=viewer)·수정(editor) 권한 확인. 실패 시 403.

    업로더 본인은 항상 통과. 그 외에는 컬렉션 역할 확인 후 v3 문서 단위 규칙
    (보안등급 대 열람등급, 문서 ACL)을 app/services/access_policy.py로 판정한다 —
    볼 수 없는 문서는 수정도 할 수 없다.
    """
    if str(doc.created_by) == str(user.id):
        return
    if not doc.collection_id:
        raise HTTPException(status_code=403, detail="Access denied")
    await check_collection_access(db, doc.collection_id, user, min_role=min_role)

    from app.services.access_policy import (
        AccessContext,
        can_view,
        group_ids_stmt,
        load_document_facts,
    )

    facts = (await load_document_facts(db, [str(doc.id)])).get(str(doc.id))
    group_ids = (await db.scalars(group_ids_stmt(str(user.id)))).all()
    # 컬렉션 접근은 바로 위에서 확인했으므로 이 문서의 컬렉션만 넣어 판정한다.
    ctx = AccessContext.create(user.id, [str(doc.collection_id)], user.clearance_level, group_ids)
    if facts is None or not can_view(ctx, facts):
        raise HTTPException(status_code=403, detail="Access denied")


async def accessible_collection_ids(
    db: AsyncSession, user: User, project_id: UUID | str | None = None
) -> list[str]:
    """사용자가 컬렉션 단위로 접근할 수 있는 컬렉션 id 목록.

    규칙은 access_policy.accessible_collection_ids_stmt 한 곳에만 있다(채팅 워커의
    sync 경로도 같은 문을 실행한다). project_id가 있으면 그 프로젝트로 좁히고,
    그 프로젝트에 속하지 않은 사용자는 프로젝트 상속분을 얻지 못한다(방어적 교차 검증).
    문서 단위 규칙(등급·ACL)은 여기서 판정하지 않는다 — 문서 목록은
    access_policy.document_visibility_clause, 검색은 qdrant_access_filter를 쓴다.
    """
    from app.services.access_policy import accessible_collection_ids_stmt

    stmt = accessible_collection_ids_stmt(
        str(user.id), str(project_id) if project_id is not None else None
    )
    return list({str(cid) for cid in (await db.scalars(stmt)).all()})
