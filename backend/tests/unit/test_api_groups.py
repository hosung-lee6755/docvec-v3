"""그룹 관리 API(v3 권한 모델) — 관리자 전용 변경, 감사 로그, 멤버 관리, ACL 항목 보존."""
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.endpoints import groups as g
from app.db.models.audit_log import AuditLog
from app.db.models.document_acl import DocumentAclEntry
from app.db.models.user_group import UserGroupMember
from app.schemas.access import GroupCreate, GroupMemberAdd, GroupUpdate
from tests.unit.api_pg_helpers import db_session, make_document, make_user  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _audit_actions(db, resource_id) -> list[str]:
    rows = await db.scalars(
        select(AuditLog.action)
        .where(AuditLog.resource_id == str(resource_id))
        .order_by(AuditLog.created_at)
    )
    return list(rows.all())


async def _expect(awaitable, status: int) -> None:
    with pytest.raises(HTTPException) as exc:
        await awaitable
    assert exc.value.status_code == status


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:6]}"


async def test_non_admin_cannot_mutate_groups(db_session):  # noqa: F811
    admin = await make_user(db_session, "admin")
    editor = await make_user(db_session, "editor")
    group = await g.create_group(GroupCreate(name=_name("t")), db_session, admin)
    add = GroupMemberAdd(user_id=editor.id)

    await _expect(g.create_group(GroupCreate(name="x"), db_session, editor), 403)
    await _expect(g.update_group(group.id, GroupUpdate(name="y"), db_session, editor), 403)
    await _expect(g.delete_group(group.id, db_session, editor), 403)
    await _expect(g.get_group(group.id, db_session, editor), 403)
    await _expect(g.list_group_members(group.id, db_session, editor), 403)
    await _expect(g.add_group_member(group.id, add, db_session, editor), 403)
    await _expect(g.remove_group_member(group.id, editor.id, db_session, editor), 403)


async def test_create_list_update_delete_with_audit(db_session):  # noqa: F811
    admin = await make_user(db_session, "admin")
    viewer = await make_user(db_session, "viewer")
    name = _name("품질팀")

    created = await g.create_group(GroupCreate(name=f"  {name} ", description="d"), db_session, admin)
    assert created.name == name and created.member_count == 0

    # 목록은 일반 사용자도 본다(문서 ACL에 넣을 그룹 선택용)
    listed = await g.list_groups(db_session, viewer)
    assert name in [item.name for item in listed["items"]]

    updated = await g.update_group(created.id, GroupUpdate(description="new"), db_session, admin)
    assert updated.name == name and updated.description == "new"

    await g.delete_group(created.id, db_session, admin)
    await _expect(g.get_group(created.id, db_session, admin), 404)
    assert await _audit_actions(db_session, created.id) == [
        "group.create", "group.update", "group.delete",
    ]


async def test_duplicate_name_is_409(db_session):  # noqa: F811
    # 409 뒤에는 세션이 롤백되어 객체가 만료된다 — 실제 요청은 여기서 끝나므로 마지막에 둔다.
    admin = await make_user(db_session, "admin")
    name = _name("dup")
    await g.create_group(GroupCreate(name=name), db_session, admin)
    await _expect(g.create_group(GroupCreate(name=name), db_session, admin), 409)


async def test_rename_to_existing_name_is_409(db_session):  # noqa: F811
    admin = await make_user(db_session, "admin")
    a = await g.create_group(GroupCreate(name=_name("a")), db_session, admin)
    b = await g.create_group(GroupCreate(name=_name("b")), db_session, admin)
    await _expect(g.update_group(b.id, GroupUpdate(name=a.name), db_session, admin), 409)


async def test_member_add_list_remove(db_session):  # noqa: F811
    admin = await make_user(db_session, "admin")
    alice = await make_user(db_session, "viewer", _name("alice"))
    group = await g.create_group(GroupCreate(name=_name("m")), db_session, admin)
    add_alice = GroupMemberAdd(user_id=alice.id)

    added = await g.add_group_member(group.id, add_alice, db_session, admin)
    assert str(added.user_id) == str(alice.id)
    await _expect(g.add_group_member(group.id, add_alice, db_session, admin), 409)
    await _expect(
        g.add_group_member(group.id, GroupMemberAdd(user_id=uuid4()), db_session, admin), 404
    )

    detail = await g.get_group(group.id, db_session, admin)
    assert detail.member_count == 1
    assert [m.username for m in detail.members] == [alice.username]

    await g.remove_group_member(group.id, alice.id, db_session, admin)
    await _expect(g.remove_group_member(group.id, alice.id, db_session, admin), 404)
    assert (await g.list_group_members(group.id, db_session, admin))["items"] == []
    assert await _audit_actions(db_session, group.id) == [
        "group.create", "group.member_add", "group.member_remove",
    ]


async def test_delete_group_keeps_acl_entries_fail_closed(db_session):  # noqa: F811
    """그룹을 지워도 문서 ACL의 그룹 항목은 남는다 — 지우면 목록이 비어 문서가 '제한 없음'이 된다."""
    admin = await make_user(db_session, "admin")
    member = await make_user(db_session, "viewer")
    group = await g.create_group(GroupCreate(name=_name("d")), db_session, admin)
    await g.add_group_member(group.id, GroupMemberAdd(user_id=member.id), db_session, admin)
    doc = await make_document(db_session, admin)
    db_session.add(DocumentAclEntry(
        document_id=str(doc.id), principal_type="group", principal_id=str(group.id)
    ))
    await db_session.flush()

    await g.delete_group(group.id, db_session, admin)

    remaining = (await db_session.scalars(
        select(DocumentAclEntry).where(DocumentAclEntry.document_id == doc.id)
    )).all()
    assert [(e.principal_type, str(e.principal_id)) for e in remaining] == [
        ("group", str(group.id)),
    ]
    members = (await db_session.scalars(
        select(UserGroupMember).where(UserGroupMember.group_id == group.id)
    )).all()
    assert members == []
