"""app/api/v1/permissions.py 실제 DB 테스트 — 역할 계층·restrict_to_members·상속 규칙을 쿼리까지 검증.

기존 test_permissions.py는 mock 기반이라 SQL 필터(프로젝트 교차 검증 등)를 확인하지 못한다.
"""
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.permissions import (
    accessible_collection_ids,
    accessible_project_ids,
    check_collection_access,
    check_document_access,
    check_project_access,
)
from app.db.models.collection_member import CollectionMember
from tests.unit.api_pg_helpers import (  # noqa: F401
    add_member,
    db_session,
    make_collection,
    make_document,
    make_project,
    make_user,
)


async def _status_of(coro) -> int | None:
    try:
        await coro
    except HTTPException as exc:
        return exc.status_code
    return None


@pytest.fixture
async def world(db_session):
    owner = await make_user(db_session, "editor", "owner")
    viewer = await make_user(db_session, "viewer", "viewer")
    editor = await make_user(db_session, "viewer", "editor")
    stranger = await make_user(db_session, "viewer", "stranger")
    project = await make_project(db_session, owner)
    await add_member(db_session, project, viewer, "viewer", owner)
    await add_member(db_session, project, editor, "editor", owner)
    return dict(db=db_session, owner=owner, viewer=viewer, editor=editor, stranger=stranger, project=project)


@pytest.mark.asyncio
async def test_check_project_access_role_hierarchy(world):
    db, pid = world["db"], world["project"].id
    owned = await check_project_access(db, pid, world["owner"], "editor")
    assert str(owned.id) == str(pid)
    assert await _status_of(check_project_access(db, pid, world["viewer"], "viewer")) is None
    assert await _status_of(check_project_access(db, pid, world["viewer"], "editor")) == 403
    assert await _status_of(check_project_access(db, pid, world["editor"], "editor")) is None
    assert await _status_of(check_project_access(db, pid, world["stranger"], "viewer")) == 403
    assert await _status_of(check_project_access(db, uuid4(), world["owner"], "viewer")) == 404


@pytest.mark.asyncio
async def test_accessible_project_ids_owned_plus_member(world):
    db = world["db"]
    other = await make_project(db, world["viewer"], "viewer-owned")

    ids = set(await accessible_project_ids(db, world["viewer"]))

    assert ids == {str(world["project"].id), str(other.id)}
    assert await accessible_project_ids(db, world["stranger"]) == []


@pytest.mark.asyncio
async def test_collection_access_inherits_project_role_unless_restricted(world):
    db = world["db"]
    open_col = await make_collection(db, world["owner"], world["project"], name="open")
    closed = await make_collection(db, world["owner"], world["project"], name="closed", restrict_to_members=True)

    assert await _status_of(check_collection_access(db, open_col.id, world["viewer"], "viewer")) is None
    assert await _status_of(check_collection_access(db, open_col.id, world["viewer"], "editor")) == 403
    assert await _status_of(check_collection_access(db, open_col.id, world["editor"], "editor")) is None
    assert await _status_of(check_collection_access(db, closed.id, world["editor"], "viewer")) == 403
    assert await _status_of(check_collection_access(db, open_col.id, world["stranger"], "viewer")) == 403
    assert await _status_of(check_collection_access(db, uuid4(), world["owner"], "viewer")) == 404


@pytest.mark.asyncio
async def test_collection_access_project_owner_gets_inherited_access_to_others_collection(world):
    db = world["db"]
    col = await make_collection(db, world["editor"], world["project"], name="by-editor")
    assert await _status_of(check_collection_access(db, col.id, world["owner"], "editor")) is None


@pytest.mark.asyncio
async def test_collection_access_explicit_member_role_on_restricted_collection(world):
    db = world["db"]
    closed = await make_collection(db, world["owner"], world["project"], name="closed", restrict_to_members=True)
    db.add(CollectionMember(collection_id=str(closed.id), user_id=str(world["viewer"].id),
                            role="viewer", invited_by=str(world["owner"].id)))
    await db.flush()

    assert await _status_of(check_collection_access(db, closed.id, world["viewer"], "viewer")) is None
    assert await _status_of(check_collection_access(db, closed.id, world["viewer"], "editor")) == 403


@pytest.mark.asyncio
async def test_check_document_access_owner_collection_and_orphan(world):
    db = world["db"]
    col = await make_collection(db, world["owner"], world["project"])
    shared_doc = await make_document(db, world["owner"], col)
    orphan = await make_document(db, world["owner"], None)

    assert await _status_of(check_document_access(db, shared_doc, world["viewer"])) is None
    assert await _status_of(check_document_access(db, shared_doc, world["stranger"])) == 403
    assert await _status_of(check_document_access(db, orphan, world["owner"])) is None
    assert await _status_of(check_document_access(db, orphan, world["viewer"])) == 403


@pytest.mark.asyncio
async def test_accessible_collection_ids_union_and_restriction(world):
    db = world["db"]
    open_col = await make_collection(db, world["owner"], world["project"], name="open")
    closed = await make_collection(db, world["owner"], world["project"], name="closed", restrict_to_members=True)
    own = await make_collection(db, world["viewer"], None, name="own")
    db.add(CollectionMember(collection_id=str(closed.id), user_id=str(world["stranger"].id),
                            role="viewer", invited_by=str(world["owner"].id)))
    await db.flush()

    viewer_ids = set(await accessible_collection_ids(db, world["viewer"]))
    stranger_ids = set(await accessible_collection_ids(db, world["stranger"]))

    assert viewer_ids == {str(open_col.id), str(own.id)}
    assert stranger_ids == {str(closed.id)}


@pytest.mark.asyncio
async def test_accessible_collection_ids_project_filter_is_defense_in_depth(world):
    db = world["db"]
    mine = await make_collection(db, world["owner"], world["project"], name="mine")
    foreign_project = await make_project(db, world["stranger"], "foreign")
    foreign_col = await make_collection(db, world["stranger"], foreign_project, name="foreign")

    scoped = set(await accessible_collection_ids(db, world["viewer"], world["project"].id))
    # 접근 권한이 없는 프로젝트를 지정해도 그 프로젝트의 컬렉션은 새지 않는다
    leaked = set(await accessible_collection_ids(db, world["viewer"], foreign_project.id))

    assert scoped == {str(mine.id)}
    assert leaked == set()
    assert str(foreign_col.id) not in scoped
