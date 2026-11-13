"""AD에서 다시 생긴 그룹이 예전 그룹의 문서 권한을 이어받는 기능.

예전 그룹 행은 동기화가 지우지만 문서 ACL 항목은 남는다(fail-closed). 관리자가 이어받기를 고르면
그 항목을 새 그룹으로 옮기고, 원천 연결 문서는 동기화가 다시 걸므로 건드리지 않는다.
"""
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.endpoints import groups as g
from app.db.models.audit_log import AuditLog
from app.db.models.document_acl import DocumentAclEntry
from app.db.models.source_connector import SourceConnector, SourceItem
from app.db.models.user import User
from app.db.models.user_group import UserGroup
from tests.unit.api_pg_helpers import db_session, make_collection, make_document, make_user  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _world(db):
    admin = await make_user(db, role="admin")
    col = await make_collection(db, admin)
    old_id = uuid4()
    group = UserGroup(id=uuid4(), name=f"sales-{uuid4().hex[:6]}", source="ldap",
                      external_id=f"S-1-5-21-7-{uuid4().int % 10_000}", previous_group_id=old_id)
    db.add(group)
    plain = await make_document(db, admin, col)
    granted = await make_document(db, admin, col)
    from_share = await make_document(db, admin, col)
    service = User(id=uuid4(), email=f"connector-{uuid4().hex[:6]}@system.invalid", username="커넥터",
                   hashed_password="!", role="viewer", auth_source="system", is_active=False)
    db.add(service)
    await db.flush()
    connector = SourceConnector(
        id=uuid4(), name="공유", host="fs", share="docs", username="svc", password_encrypted="x",
        collection_id=col.id, created_by=admin.id, service_user_id=service.id,
    )
    db.add(connector)
    await db.flush()
    db.add(SourceItem(id=uuid4(), connector_id=connector.id, path="a.pdf", document_id=from_share.id))
    for doc in (plain, granted, from_share):
        db.add(DocumentAclEntry(document_id=doc.id, principal_type="group", principal_id=old_id))
    # 이미 새 그룹에도 열려 있는 문서는 중복으로 넣지 않는다
    db.add(DocumentAclEntry(document_id=granted.id, principal_type="group", principal_id=group.id))
    await db.commit()
    return admin, group, old_id, plain, granted, from_share


async def _entries(db, principal_id) -> set[str]:
    rows = await db.scalars(select(DocumentAclEntry.document_id).where(
        DocumentAclEntry.principal_type == "group", DocumentAclEntry.principal_id == principal_id))
    return {str(d) for d in rows.all()}


async def test_preview_lists_movable_documents_and_counts_connector_ones(db_session):  # noqa: F811
    admin, group, old_id, plain, granted, _share = await _world(db_session)

    preview = await g.get_previous_permissions(group.id, db_session, admin)

    assert preview["previous_group_id"] == str(old_id)
    assert preview["document_count"] == 2
    assert preview["connector_document_count"] == 1
    assert {d["id"] for d in preview["documents"]} == {str(plain.id), str(granted.id)}


async def test_inherit_moves_entries_except_connector_documents(db_session):  # noqa: F811
    admin, group, old_id, plain, granted, share = await _world(db_session)
    sync = AsyncMock(return_value=[])

    with patch("app.services.group_carryover.sync_document_access", sync):
        result = await g.inherit_previous_permissions(group.id, db_session, admin)

    assert result == {"moved": 2, "already_granted": 1, "sync_failed": 0}
    assert await _entries(db_session, group.id) == {str(plain.id), str(granted.id)}
    # 원천 연결 문서의 예전 항목은 그대로 남는다(동기화가 SID로 다시 건다)
    assert await _entries(db_session, old_id) == {str(share.id)}
    assert set(sync.await_args.args[1]) == {str(plain.id), str(granted.id)}
    assert (await db_session.get(UserGroup, group.id)).previous_group_id is None
    actions = (await db_session.scalars(
        select(AuditLog.action).where(AuditLog.resource_id == str(group.id)))).all()
    assert "group.inherit_permissions" in actions


async def test_dismiss_keeps_old_entries_and_clears_the_notice(db_session):  # noqa: F811
    admin, group, old_id, plain, granted, share = await _world(db_session)

    await g.dismiss_previous_permissions(group.id, db_session, admin)

    assert await _entries(db_session, old_id) == {str(plain.id), str(granted.id), str(share.id)}
    assert (await db_session.get(UserGroup, group.id)).previous_group_id is None


async def test_only_admins_and_only_groups_with_a_predecessor(db_session):  # noqa: F811
    admin, group, *_ = await _world(db_session)
    viewer = await make_user(db_session)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await g.inherit_previous_permissions(group.id, db_session, viewer)
    assert exc.value.status_code == 403

    await g.dismiss_previous_permissions(group.id, db_session, admin)
    with pytest.raises(HTTPException) as exc:
        await g.inherit_previous_permissions(group.id, db_session, admin)
    assert exc.value.status_code == 409


async def test_group_response_flags_pending_carryover(db_session):  # noqa: F811
    _admin, group, *_ = await _world(db_session)
    assert g._group_response(group, 0).has_previous_permissions is True
