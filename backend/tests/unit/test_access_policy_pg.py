"""access_policy의 SQL 문을 실제 Postgres로 검증.

- 컬렉션 접근 문이 기존 permissions.accessible_collection_ids와 같은 결과를 내는지(회귀 방지)
- async 빌더와 sync 빌더(채팅 워커용)가 같은 컨텍스트를 만드는지
- document_visibility_clause(SQL)가 can_view(파이썬)와 문서마다 같은 판정을 내리는지
"""
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.v1.permissions import accessible_collection_ids
from app.db.models.collection_member import CollectionMember
from app.db.models.document import Document
from app.db.models.document_acl import DocumentAclEntry
from app.db.models.user_group import UserGroup, UserGroupMember
from app.services.access_policy import (
    accessible_collection_ids_stmt,
    build_access_context,
    build_access_context_sync,
    can_view,
    document_visibility_clause,
    load_document_facts,
    load_document_facts_sync,
)
from tests.unit.api_pg_helpers import (  # noqa: F401
    add_member,
    db_session,
    make_collection,
    make_document,
    make_project,
    make_user,
)


async def _make_group(db, name: str, *members) -> UserGroup:
    group = UserGroup(id=str(uuid4()), name=f"{name}-{uuid4().hex[:6]}")
    db.add(group)
    await db.flush()
    for m in members:
        db.add(UserGroupMember(group_id=str(group.id), user_id=str(m.id)))
    await db.flush()
    return group


async def _acl(db, doc, principal_type: str, principal_id) -> None:
    db.add(DocumentAclEntry(
        document_id=str(doc.id), principal_type=principal_type, principal_id=str(principal_id)
    ))
    await db.flush()


@pytest.fixture
async def world(db_session):
    db = db_session
    owner = await make_user(db, "editor", "owner")
    member = await make_user(db, "viewer", "member")
    outsider = await make_user(db, "viewer", "outsider")
    project = await make_project(db, owner)
    other_project = await make_project(db, outsider, "other")
    await add_member(db, project, member, "viewer", owner)

    open_col = await make_collection(db, owner, project, "open")
    restricted_col = await make_collection(db, owner, project, "restricted", restrict_to_members=True)
    internal_default_col = await make_collection(
        db, owner, project, "internal-default", default_security_level="Confidential"
    )
    outsider_col = await make_collection(db, outsider, other_project, "outsider")
    db.add(CollectionMember(
        collection_id=str(restricted_col.id), user_id=str(member.id), role="viewer",
        invited_by=str(owner.id),
    ))
    await db.flush()
    group = await _make_group(db, "team-a", member)
    return dict(
        db=db, owner=owner, member=member, outsider=outsider, project=project,
        open_col=open_col, restricted_col=restricted_col,
        internal_default_col=internal_default_col, outsider_col=outsider_col, group=group,
    )


@pytest.mark.asyncio
async def test_collection_stmt_rule(world):
    """소유 ∪ 멤버 ∪ 프로젝트 상속(restrict_to_members=False)이며, 프로젝트 범위를 주면 그 안으로만."""
    db = world["db"]
    ids = lambda *cols: {str(c.id) for c in cols}  # noqa: E731
    pid = str(world["project"].id)

    async def run(user, project_id=None):
        stmt = accessible_collection_ids_stmt(str(user.id), project_id)
        return {str(c) for c in (await db.scalars(stmt)).all()}

    project_cols = ids(world["open_col"], world["restricted_col"], world["internal_default_col"])
    assert await run(world["owner"]) == project_cols
    assert await run(world["owner"], pid) == project_cols
    # 멤버: 상속(open, internal-default) + 명시 멤버(restricted)
    assert await run(world["member"]) == project_cols
    assert await run(world["outsider"]) == ids(world["outsider_col"])
    # 속하지 않은 프로젝트로 좁히면 아무것도 없다
    assert await run(world["outsider"], pid) == set()
    # 레거시 API 함수도 같은 문을 쓴다
    assert set(await accessible_collection_ids(db, world["member"])) == project_cols


@pytest.mark.asyncio
async def test_async_and_sync_builders_agree(world):
    db = world["db"]
    for user in (world["owner"], world["member"], world["outsider"]):
        a = await build_access_context(db, user)
        s = await db.run_sync(lambda sess, uid=str(user.id): build_access_context_sync(sess, uid))
        assert a == s
    member_ctx = await build_access_context(db, world["member"])
    assert member_ctx.group_ids == frozenset({str(world["group"].id)})
    assert member_ctx.clearance_rank == 1  # 기본 Internal


@pytest.mark.asyncio
async def test_sql_clause_matches_can_view(world):
    db, owner, member, outsider = world["db"], world["owner"], world["member"], world["outsider"]
    docs = [
        await make_document(db, owner, world["open_col"]),
        await make_document(db, owner, world["open_col"], security_level="Internal"),
        await make_document(db, owner, world["open_col"], security_level="Confidential"),
        await make_document(db, owner, world["internal_default_col"]),
        await make_document(db, owner, world["internal_default_col"], security_level="Public"),
        await make_document(db, owner, world["restricted_col"]),
        await make_document(db, outsider, world["outsider_col"]),
        await make_document(db, member, None),
    ]
    acl_user = await make_document(db, owner, world["open_col"])
    await _acl(db, acl_user, "user", outsider.id)
    acl_group = await make_document(db, owner, world["open_col"])
    await _acl(db, acl_group, "group", world["group"].id)
    docs += [acl_user, acl_group]
    ids = [str(d.id) for d in docs]

    for user in (owner, member, outsider):
        ctx = await build_access_context(db, user)
        sql_visible = {
            str(i) for i in (await db.scalars(
                select(Document.id).where(Document.id.in_(ids), document_visibility_clause(ctx))
            )).all()
        }
        facts = await load_document_facts(db, ids)
        py_visible = {d for d, f in facts.items() if can_view(ctx, f)}
        assert sql_visible == py_visible, user.username
        sync_facts = await db.run_sync(lambda sess: load_document_facts_sync(sess, ids))
        assert sync_facts == facts

    member_ctx = await build_access_context(db, member)
    facts = await load_document_facts(db, ids)
    visible = {d for d, f in facts.items() if can_view(member_ctx, f)}
    expected = {str(docs[i].id) for i in (0, 1, 4, 5, 7)} | {str(acl_group.id)}
    assert visible == expected
