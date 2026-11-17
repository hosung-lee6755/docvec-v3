"""관리자 문의 API: 작성자와 관리자의 권한, 상태 전이, 삭제 규칙, 문서 접근 확인, 알림."""
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.api.v1.endpoints import inquiries as api
from app.db.models.inquiry import Inquiry
from app.db.models.notification import (
    KIND_INQUIRY_CREATED,
    KIND_INQUIRY_FOLLOWUP,
    KIND_INQUIRY_REPLIED,
    Notification,
)
from app.schemas.inquiry import InquiryCreate, InquiryUpdate, MessageCreate
from tests.unit.api_pg_helpers import db_session, make_collection, make_document, make_user  # noqa: F401


@pytest.fixture(autouse=True)
def _no_redis_rate_limit(monkeypatch):
    monkeypatch.setattr(api, "enforce_user_rate_limit", lambda *args, **kwargs: None)


async def _create(db, author, **overrides):
    fields = {"title": "PDF 처리가 계속 실패합니다", "body": "세 번이나 같은 오류가 납니다", "category": "error"}
    fields.update(overrides)
    return await api.create_inquiry(InquiryCreate(**fields), db=db, current_user=author)


async def _notifications(db, *, kind: str | None = None, resource_id: str | None = None):
    stmt = select(Notification)
    if kind is not None:
        stmt = stmt.where(Notification.kind == kind)
    if resource_id is not None:
        stmt = stmt.where(Notification.resource_id == resource_id)
    return (await db.scalars(stmt)).all()


async def _recipients(db, kind: str, resource_id: str) -> set[str]:
    return {str(row.user_id) for row in await _notifications(db, kind=kind, resource_id=resource_id)}


# --- 작성과 문서 연결 ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_stores_document_error_snapshot_and_notifies_only_admins(db_session):
    admin, author, bystander = (
        await make_user(db_session, role="admin"),
        await make_user(db_session, role="editor"),
        await make_user(db_session, role="viewer"),
    )
    doc = await make_document(db_session, author, status="FAILED", error_message="파서가 표를 읽지 못했습니다")

    detail = await _create(db_session, author, document_id=str(doc.id))

    assert detail.error_snapshot == "파서가 표를 읽지 못했습니다"
    assert detail.status == "open" and detail.document.id == str(doc.id)
    recipients = await _recipients(db_session, KIND_INQUIRY_CREATED, detail.id)
    assert str(admin.id) in recipients
    assert str(bystander.id) not in recipients and str(author.id) not in recipients
    link = (await _notifications(db_session, kind=KIND_INQUIRY_CREATED, resource_id=detail.id))[0].link
    assert link == f"/inquiries/{detail.id}"


@pytest.mark.asyncio
async def test_create_refuses_document_the_user_cannot_view(db_session):
    owner = await make_user(db_session, role="editor")
    outsider = await make_user(db_session, role="viewer")
    collection = await make_collection(db_session, owner)
    doc = await make_document(db_session, owner, collection, status="FAILED", error_message="오류")

    with pytest.raises(HTTPException) as exc_info:
        await _create(db_session, outsider, document_id=str(doc.id))

    assert exc_info.value.status_code == 403
    assert (await db_session.scalars(select(Inquiry).where(Inquiry.author_id == outsider.id))).all() == []


@pytest.mark.asyncio
async def test_create_without_document_has_no_snapshot(db_session):
    author = await make_user(db_session, role="viewer")

    detail = await _create(db_session, author, category="question")

    assert detail.document is None and detail.error_snapshot is None and detail.category == "question"


def test_create_schema_has_no_client_supplied_snapshot():
    assert "error_snapshot" not in InquiryCreate.model_fields


# --- 목록 ------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_users_see_only_their_inquiries_and_admins_see_all(db_session):
    admin, alice, bob = (
        await make_user(db_session, role="admin"),
        await make_user(db_session, role="viewer"),
        await make_user(db_session, role="viewer"),
    )
    mine = await _create(db_session, alice, title="앨리스 문의")
    await _create(db_session, bob, title="밥 문의")

    own = await api.list_inquiries(status=None, limit=20, offset=0, db=db_session, current_user=alice)
    everything = await api.list_inquiries(status=None, limit=20, offset=0, db=db_session, current_user=admin)

    assert [item.id for item in own.items] == [mine.id] and own.total == 1
    assert everything.total == 2


@pytest.mark.asyncio
async def test_admin_list_filters_by_status_and_paginates(db_session):
    admin, author = await make_user(db_session, role="admin"), await make_user(db_session, role="viewer")
    first = await _create(db_session, author, title="첫 문의")
    second = await _create(db_session, author, title="둘째 문의")
    await api.add_message(second.id, MessageCreate(body="확인했습니다"), db=db_session, current_user=admin)

    open_only = await api.list_inquiries(status="open", limit=20, offset=0, db=db_session, current_user=admin)
    in_progress = await api.list_inquiries(status="in_progress", limit=20, offset=0, db=db_session, current_user=admin)
    page = await api.list_inquiries(status=None, limit=1, offset=1, db=db_session, current_user=admin)

    assert [item.id for item in open_only.items] == [first.id] and open_only.total == 1
    assert [item.id for item in in_progress.items] == [second.id]
    assert page.total == 2 and len(page.items) == 1


# --- 상세 조회 ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detail_is_visible_to_author_and_admin_but_not_to_others(db_session):
    admin, author, other = (
        await make_user(db_session, role="admin"),
        await make_user(db_session, role="viewer"),
        await make_user(db_session, role="viewer"),
    )
    created = await _create(db_session, author)

    as_author = await api.get_inquiry(created.id, db=db_session, current_user=author)
    as_admin = await api.get_inquiry(created.id, db=db_session, current_user=admin)

    assert as_author.is_author is True and as_admin.is_author is False
    assert [m.body for m in as_admin.messages] == ["세 번이나 같은 오류가 납니다"]
    with pytest.raises(HTTPException) as exc_info:
        await api.get_inquiry(created.id, db=db_session, current_user=other)
    assert exc_info.value.status_code == 404


# --- 메시지 -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_reply_moves_open_to_in_progress_and_notifies_author(db_session):
    admin, author = await make_user(db_session, role="admin"), await make_user(db_session, role="viewer")
    created = await _create(db_session, author)

    reply = await api.add_message(created.id, MessageCreate(body="재처리 설정을 바꿔 보세요"),
                                  db=db_session, current_user=admin)

    detail = await api.get_inquiry(created.id, db=db_session, current_user=author)
    assert reply.is_admin is True and reply.author_id == str(admin.id)
    assert detail.status == "in_progress"
    assert await _recipients(db_session, KIND_INQUIRY_REPLIED, created.id) == {str(author.id)}


@pytest.mark.asyncio
async def test_author_follow_up_notifies_admins_with_followup_kind(db_session):
    admin, author = await make_user(db_session, role="admin"), await make_user(db_session, role="viewer")
    created = await _create(db_session, author)

    follow_up = await api.add_message(created.id, MessageCreate(body="여전히 같은 오류입니다"),
                                      db=db_session, current_user=author)

    assert follow_up.is_admin is False
    assert str(admin.id) in await _recipients(db_session, KIND_INQUIRY_FOLLOWUP, created.id)


@pytest.mark.asyncio
async def test_author_follow_up_reopens_a_resolved_inquiry(db_session):
    admin, author = await make_user(db_session, role="admin"), await make_user(db_session, role="viewer")
    created = await _create(db_session, author)
    await api.add_message(created.id, MessageCreate(body="답변"), db=db_session, current_user=admin)
    await api.update_inquiry(created.id, InquiryUpdate(status="resolved"), db=db_session, current_user=admin)

    await api.add_message(created.id, MessageCreate(body="아직 안 됩니다"), db=db_session, current_user=author)

    assert (await api.get_inquiry(created.id, db=db_session, current_user=author)).status == "open"


@pytest.mark.asyncio
async def test_message_on_closed_inquiry_is_rejected(db_session):
    author = await make_user(db_session, role="viewer")
    created = await _create(db_session, author)
    await api.update_inquiry(created.id, InquiryUpdate(status="closed"), db=db_session, current_user=author)

    with pytest.raises(HTTPException) as exc_info:
        await api.add_message(created.id, MessageCreate(body="끝났는데요"), db=db_session, current_user=author)

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_other_user_cannot_post_a_message(db_session):
    author, other = await make_user(db_session, role="viewer"), await make_user(db_session, role="viewer")
    created = await _create(db_session, author)

    with pytest.raises(HTTPException) as exc_info:
        await api.add_message(created.id, MessageCreate(body="끼어듭니다"), db=db_session, current_user=other)

    assert exc_info.value.status_code == 404


# --- 수정과 상태 변경 ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_author_edits_content_only_while_open(db_session):
    admin, author = await make_user(db_session, role="admin"), await make_user(db_session, role="viewer")
    created = await _create(db_session, author)

    edited = await api.update_inquiry(
        created.id, InquiryUpdate(title="제목 수정", body="본문 수정", category="request"),
        db=db_session, current_user=author,
    )

    assert edited.title == "제목 수정" and edited.category == "request"
    assert edited.messages[0].body == "본문 수정"

    await api.add_message(created.id, MessageCreate(body="확인합니다"), db=db_session, current_user=admin)
    with pytest.raises(HTTPException) as exc_info:
        await api.update_inquiry(created.id, InquiryUpdate(title="또 수정"), db=db_session, current_user=author)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_admin_cannot_edit_content_but_can_change_status_and_author_is_told(db_session):
    admin, author = await make_user(db_session, role="admin"), await make_user(db_session, role="viewer")
    created = await _create(db_session, author)

    with pytest.raises(HTTPException) as exc_info:
        await api.update_inquiry(created.id, InquiryUpdate(title="관리자 수정"), db=db_session, current_user=admin)
    assert exc_info.value.status_code == 403

    changed = await api.update_inquiry(created.id, InquiryUpdate(status="resolved"), db=db_session, current_user=admin)

    assert changed.status == "resolved"
    assert await _recipients(db_session, KIND_INQUIRY_REPLIED, created.id) == {str(author.id)}


@pytest.mark.asyncio
async def test_author_may_close_but_not_set_other_statuses(db_session):
    author = await make_user(db_session, role="viewer")
    created = await _create(db_session, author)

    with pytest.raises(HTTPException) as exc_info:
        await api.update_inquiry(created.id, InquiryUpdate(status="in_progress"), db=db_session, current_user=author)
    assert exc_info.value.status_code == 403

    closed = await api.update_inquiry(created.id, InquiryUpdate(status="closed"), db=db_session, current_user=author)
    assert closed.status == "closed"


@pytest.mark.asyncio
async def test_other_user_cannot_patch_inquiry(db_session):
    author, other = await make_user(db_session, role="viewer"), await make_user(db_session, role="viewer")
    created = await _create(db_session, author)

    with pytest.raises(HTTPException) as exc_info:
        await api.update_inquiry(created.id, InquiryUpdate(status="closed"), db=db_session, current_user=other)

    assert exc_info.value.status_code == 404


# --- 삭제 ------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_author_can_delete_only_before_an_admin_reply(db_session):
    admin, author = await make_user(db_session, role="admin"), await make_user(db_session, role="viewer")
    created = await _create(db_session, author)
    replied = await _create(db_session, author, title="답변될 문의")
    await api.add_message(replied.id, MessageCreate(body="확인"), db=db_session, current_user=admin)

    await api.delete_inquiry(created.id, db=db_session, current_user=author)

    assert (await db_session.scalars(select(Inquiry).where(Inquiry.id == created.id))).first() is None
    with pytest.raises(HTTPException) as exc_info:
        await api.delete_inquiry(replied.id, db=db_session, current_user=author)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_delete_any_inquiry_and_its_notifications_go_with_it(db_session):
    admin, author = await make_user(db_session, role="admin"), await make_user(db_session, role="viewer")
    created = await _create(db_session, author)
    await api.add_message(created.id, MessageCreate(body="답변"), db=db_session, current_user=admin)
    assert await _notifications(db_session, resource_id=created.id)

    await api.delete_inquiry(created.id, db=db_session, current_user=admin)

    assert await _notifications(db_session, resource_id=created.id) == []
    assert (await db_session.scalars(select(Inquiry).where(Inquiry.id == created.id))).first() is None


@pytest.mark.asyncio
async def test_other_user_cannot_delete(db_session):
    author, other = await make_user(db_session, role="viewer"), await make_user(db_session, role="viewer")
    created = await _create(db_session, author)

    with pytest.raises(HTTPException) as exc_info:
        await api.delete_inquiry(created.id, db=db_session, current_user=other)

    assert exc_info.value.status_code == 404


# --- 입력 길이와 속도 제한 ------------------------------------------------------------

def test_title_and_body_length_limits():
    assert InquiryCreate(title="가" * 200, body="나" * 5000, category="other").title == "가" * 200
    with pytest.raises(ValidationError):
        InquiryCreate(title="가" * 201, body="본문", category="other")
    with pytest.raises(ValidationError):
        InquiryCreate(title="제목", body="나" * 5001, category="other")
    with pytest.raises(ValidationError):
        MessageCreate(body="나" * 5001)
    with pytest.raises(ValidationError):
        InquiryUpdate(title="가" * 201)


def test_blank_title_and_unknown_category_are_rejected():
    with pytest.raises(ValidationError):
        InquiryCreate(title="   ", body="본문", category="error")
    with pytest.raises(ValidationError):
        InquiryCreate(title="제목", body="본문", category="gossip")


@pytest.mark.asyncio
async def test_writes_share_one_rate_limit_bucket(db_session, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(api, "enforce_user_rate_limit", lambda user_id, bucket, **kwargs: calls.append(bucket))
    author = await make_user(db_session, role="viewer")
    created = await _create(db_session, author)

    await api.add_message(created.id, MessageCreate(body="추가"), db=db_session, current_user=author)

    assert calls == ["inquiry_write", "inquiry_write"]
