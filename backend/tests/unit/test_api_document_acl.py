"""문서 ACL API와 권한 변경 경로(문서 등급·컬렉션 기본 등급·사용자 열람등급)의
감사 로그·Qdrant 사본 동기화 — v3 권한 모델 Task 5·6."""
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.endpoints import collections as collections_api
from app.api.v1.endpoints import users as users_api
from app.api.v1.endpoints.documents import acl as acl_api
from app.api.v1.endpoints.documents import metadata as metadata_api
from app.api.v1.permissions import check_document_access
from app.db.models.audit_log import AuditLog
from app.db.models.user_group import UserGroup, UserGroupMember
from app.schemas.access import AclEntryIn, DocumentAclUpdate
from app.schemas.document import DocumentMetadataUpdateRequest
from tests.unit.api_pg_helpers import (  # noqa: F401
    add_member,
    db_session,
    make_collection,
    make_document,
    make_project,
    make_user,
)

pytestmark = pytest.mark.asyncio

SYNC = "app.api.v1.access_sync.sync_document_access"


async def _expect(awaitable, status: int) -> None:
    with pytest.raises(HTTPException) as exc:
        await awaitable
    assert exc.value.status_code == status


async def _audit(db, action: str) -> list[AuditLog]:
    return list((await db.scalars(select(AuditLog).where(AuditLog.action == action))).all())


def _acl(*entries: tuple[str, object]) -> DocumentAclUpdate:
    return DocumentAclUpdate(
        entries=[AclEntryIn(principal_type=t, principal_id=i) for t, i in entries]
    )


@pytest.fixture
async def world(db_session):  # noqa: F811
    db = db_session
    owner = await make_user(db, "editor")
    viewer = await make_user(db, "viewer")
    teammate = await make_user(db, "viewer")
    project = await make_project(db, owner)
    await add_member(db, project, viewer, "viewer", owner)
    await add_member(db, project, teammate, "viewer", owner)
    col = await make_collection(db, owner, project)
    doc = await make_document(db, owner, col)
    group = UserGroup(id=str(uuid4()), name=f"team-{uuid4().hex[:6]}")
    db.add(group)
    await db.flush()
    db.add(UserGroupMember(group_id=str(group.id), user_id=str(teammate.id)))
    await db.flush()
    return dict(db=db, owner=owner, viewer=viewer, teammate=teammate, col=col, doc=doc, group=group)


async def test_acl_requires_document_editor(world):
    db, doc, viewer = world["db"], world["doc"], world["viewer"]
    await _expect(acl_api.get_document_acl(doc.id, db, viewer), 403)
    await _expect(acl_api.replace_document_acl(doc.id, _acl(), db, viewer), 403)
    await _expect(acl_api.get_document_acl(uuid4(), db, world["owner"]), 404)


async def test_replace_acl_restricts_audits_and_syncs(world):
    db, doc, owner, group = world["db"], world["doc"], world["owner"], world["group"]

    with patch(SYNC, new=AsyncMock(return_value=[])) as sync:
        result = await acl_api.replace_document_acl(doc.id, _acl(("group", group.id)), db, owner)

    sync.assert_awaited_once()
    assert sync.await_args.args[1] == [str(doc.id)]
    assert result.restricted is True
    assert [(e.principal_type, e.display_name) for e in result.entries] == [("group", group.name)]
    assert result.effective_security_level == "Public"
    [row] = await _audit(db, "document.acl_update")
    assert row.detail["added"] == [f"group:{group.id}"] and row.detail["removed"] == []

    # 제한 후: 그룹 멤버는 보고, 같은 프로젝트의 다른 사용자는 못 본다.
    await check_document_access(db, doc, world["teammate"])
    await _expect(check_document_access(db, doc, world["viewer"]), 403)


async def test_same_acl_is_noop(world):
    db, doc, owner = world["db"], world["doc"], world["owner"]
    with patch(SYNC, new=AsyncMock(return_value=[])) as sync:
        await acl_api.replace_document_acl(doc.id, _acl(), db, owner)
    sync.assert_not_awaited()
    assert await _audit(db, "document.acl_update") == []


async def test_clearing_acl_unrestricts(world):
    db, doc, owner, viewer = world["db"], world["doc"], world["owner"], world["viewer"]
    with patch(SYNC, new=AsyncMock(return_value=[])):
        await acl_api.replace_document_acl(doc.id, _acl(("user", owner.id)), db, owner)
        await _expect(check_document_access(db, doc, viewer), 403)
        result = await acl_api.replace_document_acl(doc.id, _acl(), db, owner)
    assert result.restricted is False
    await check_document_access(db, doc, viewer)


async def test_unknown_principal_is_rejected(world):
    db, doc, owner = world["db"], world["doc"], world["owner"]
    with patch(SYNC, new=AsyncMock(return_value=[])) as sync:
        await _expect(acl_api.replace_document_acl(doc.id, _acl(("user", uuid4())), db, owner), 400)
    sync.assert_not_awaited()


async def test_sync_failure_on_indexed_document_is_502_but_saved(world):
    db, doc, owner, group = world["db"], world["doc"], world["owner"], world["group"]
    with patch(SYNC, new=AsyncMock(return_value=[str(doc.id)])):
        await _expect(
            acl_api.replace_document_acl(doc.id, _acl(("group", group.id)), db, owner), 502
        )
    # Postgres(정본)에는 저장됐다 — 재시도는 같은 결과(멱등)
    assert (await acl_api.get_document_acl(doc.id, db, owner)).restricted is True


async def test_sync_failure_before_indexing_is_tolerated(world):
    db, owner, col, group = world["db"], world["owner"], world["col"], world["group"]
    pending = await make_document(db, owner, col, status="PARSING")
    with patch(SYNC, new=AsyncMock(return_value=[str(pending.id)])):
        result = await acl_api.replace_document_acl(
            pending.id, _acl(("group", group.id)), db, owner
        )
    assert result.restricted is True


async def test_document_security_level_change_audits_and_syncs(world):
    db, doc, owner = world["db"], world["doc"], world["owner"]
    with patch(SYNC, new=AsyncMock(return_value=[])) as sync:
        await metadata_api.update_document_metadata(
            doc.id, DocumentMetadataUpdateRequest(security_level="Confidential"), db, owner
        )
        # 같은 값 재저장·등급 외 필드 변경은 동기화하지 않는다
        await metadata_api.update_document_metadata(
            doc.id,
            DocumentMetadataUpdateRequest(security_level="Confidential", author="a"),
            db, owner,
        )
    sync.assert_awaited_once()
    [row] = await _audit(db, "document.security_level_update")
    assert row.detail == {"from": None, "to": "Confidential"}
    # Internal 열람등급(기본값)인 viewer는 더 이상 못 본다
    await _expect(check_document_access(db, doc, world["viewer"]), 403)


async def test_collection_default_level_syncs_only_inheriting_documents(world):
    db, owner, col, doc = world["db"], world["owner"], world["col"], world["doc"]
    explicit = await make_document(db, owner, col, security_level="Public")
    data = collections_api.CollectionUpdate(default_security_level="Confidential")

    with patch(SYNC, new=AsyncMock(return_value=[])) as sync:
        updated = await collections_api.update_collection(col.id, data, db, owner)
        # 필드를 보내지 않으면 기본 등급은 그대로다
        await collections_api.update_collection(
            col.id, collections_api.CollectionUpdate(description="x"), db, owner
        )

    assert updated.default_security_level == "Confidential"
    sync.assert_awaited_once()
    assert sync.await_args.args[1] == [str(doc.id)]  # 자체 등급이 있는 explicit은 제외
    [row] = await _audit(db, "collection.security_level_update")
    assert row.detail == {"from": None, "to": "Confidential"}
    await _expect(check_document_access(db, doc, world["viewer"]), 403)
    await check_document_access(db, explicit, world["viewer"])

    with patch(SYNC, new=AsyncMock(return_value=[])):
        cleared = await collections_api.update_collection(
            col.id, collections_api.CollectionUpdate(default_security_level=None), db, owner
        )
    assert cleared.default_security_level is None


async def test_collection_viewer_cannot_change_default_level(world):
    data = collections_api.CollectionUpdate(default_security_level="Public")
    await _expect(
        collections_api.update_collection(world["col"].id, data, world["db"], world["viewer"]), 403
    )


async def test_user_clearance_update_is_admin_only_and_audited(world):
    db, viewer = world["db"], world["viewer"]
    admin = await make_user(db, "admin")
    update = users_api.UserUpdate(clearance_level="Confidential")
    await _expect(users_api.update_user(viewer.id, update, db, world["owner"]), 403)

    result = await users_api.update_user(viewer.id, update, db, admin)

    assert result.clearance_level == "Confidential"
    [row] = await _audit(db, "user.clearance_update")
    assert row.detail == {"from": "Internal", "to": "Confidential"}
