"""알림 API(전체 점검 2-7): 자기 알림만 읽고, 읽음 처리하고, 지운다."""
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import notifications as api
from app.db.models.notification import KIND_DOCUMENT_FAILED, Notification
from tests.unit.api_pg_helpers import db_session, make_user  # noqa: F401


async def _user(db):
    return await make_user(db, role="editor")


async def _notification(db, user, title="t"):
    row = Notification(id=uuid4(), user_id=user.id, kind=KIND_DOCUMENT_FAILED, title=title)
    db.add(row)
    await db.flush()
    return row


@pytest.mark.asyncio
async def test_list_returns_only_my_notifications_with_unread_count(db_session):
    me, other = await _user(db_session), await _user(db_session)
    mine = await _notification(db_session, me, "내 알림")
    await _notification(db_session, other, "남의 알림")

    result = await api.list_notifications(unread_only=False, limit=30, db=db_session, current_user=me)

    assert [item.id for item in result.items] == [str(mine.id)] and result.unread_count == 1


@pytest.mark.asyncio
async def test_mark_read_then_unread_only_list_is_empty(db_session):
    me = await _user(db_session)
    row = await _notification(db_session, me)

    out = await api.mark_read(row.id, db=db_session, current_user=me)
    result = await api.list_notifications(unread_only=True, limit=30, db=db_session, current_user=me)

    assert out.read_at is not None and result.items == [] and result.unread_count == 0


@pytest.mark.asyncio
async def test_mark_all_read_touches_only_my_rows(db_session):
    me, other = await _user(db_session), await _user(db_session)
    await _notification(db_session, me)
    await _notification(db_session, me)
    await _notification(db_session, other)

    result = await api.mark_all_read(db=db_session, current_user=me)
    theirs = await api.list_notifications(unread_only=True, limit=30, db=db_session, current_user=other)

    assert result == {"updated": 2} and theirs.unread_count == 1


@pytest.mark.asyncio
async def test_other_users_notification_is_not_found_for_read_and_delete(db_session):
    me, other = await _user(db_session), await _user(db_session)
    row = await _notification(db_session, other)

    for call in (api.mark_read, api.delete_notification):
        with pytest.raises(HTTPException) as exc_info:
            await call(row.id, db=db_session, current_user=me)
        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_removes_my_notification(db_session):
    me = await _user(db_session)
    row = await _notification(db_session, me)

    await api.delete_notification(row.id, db=db_session, current_user=me)
    result = await api.list_notifications(unread_only=False, limit=30, db=db_session, current_user=me)

    assert result.items == []


@pytest.mark.asyncio
async def test_sync_failure_notifies_admins_with_connector_link(db_session):
    from app.services.notifications import notify_sync_failed

    admin, editor = await make_user(db_session, role="admin"), await _user(db_session)
    connector_id = uuid4()

    await notify_sync_failed(db_session, connector_id, "인사팀 공유 폴더", "서버에 연결하지 못했습니다")
    again = await notify_sync_failed(db_session, connector_id, "인사팀 공유 폴더", "서버에 연결하지 못했습니다")

    mine = await api.list_notifications(unread_only=False, limit=30, db=db_session, current_user=admin)
    theirs = await api.list_notifications(unread_only=False, limit=30, db=db_session, current_user=editor)
    assert [(item.kind, item.link) for item in mine.items] == [("sync_failed", "/connectors")]
    assert theirs.items == [] and again == 0
