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
    if str(doc.created_by) == str(user.id):
        return
    if doc.collection_id:
        await check_collection_access(db, doc.collection_id, user, min_role=min_role)
        return
    raise HTTPException(status_code=403, detail="Access denied")


async def accessible_collection_ids(
    db: AsyncSession, user: User, project_id: UUID | str | None = None
) -> list[str]:
    owned_q = select(Collection.id).where(Collection.created_by == str(user.id))
    member_q = select(CollectionMember.collection_id).where(
        CollectionMember.user_id == str(user.id)
    )

    # project_id narrows the result to a single project's collections. The
    # project_ids intersection below is deliberate defense-in-depth: even if a
    # caller passes a project_id without having already verified the user's
    # access to it (via check_project_access), this still can't leak collections
    # from a project the user isn't actually a member of.
    user_project_ids = await accessible_project_ids(db, user)
    if project_id is not None:
        pid = str(project_id)
        owned_q = owned_q.where(Collection.project_id == pid)
        member_q = member_q.join(Collection, Collection.id == CollectionMember.collection_id).where(
            Collection.project_id == pid
        )
        project_ids = [pid] if pid in user_project_ids else []
    else:
        project_ids = user_project_ids

    owned = await db.scalars(owned_q)
    member_of = await db.scalars(member_q)
    via_project: list = []
    if project_ids:
        via_project = (
            await db.scalars(
                select(Collection.id).where(
                    Collection.project_id.in_(project_ids),
                    Collection.restrict_to_members.is_(False),
                )
            )
        ).all()
    return list({str(cid) for cid in [*owned.all(), *member_of.all(), *via_project]})
