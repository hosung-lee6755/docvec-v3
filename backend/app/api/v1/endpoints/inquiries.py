"""관리자 문의 API. 사용자가 오류나 질문을 관리자에게 남기고 메시지로 주고받는다.

- 작성: 로그인한 사람 누구나. 문서를 붙이면 그 문서를 볼 수 있어야 하고, 오류 문구는 서버가 문서에서 복사한다.
- 목록: 일반 사용자는 자기 문의만, 관리자는 전부(상태로 거를 수 있다).
- 상세와 메시지: 작성자와 관리자만. 그 밖의 사람에게는 있는지조차 알려 주지 않는다(404).
- 관리자가 답하면 열린 문의는 처리 중으로 바뀐다. 작성자가 해결된 문의에 다시 쓰면 열린 상태로 돌아간다.
- 수정: 작성자가 열린 문의의 제목·내용·분류를 고친다. 관리자는 상태만 바꾼다. 작성자는 종료만 할 수 있다.
- 삭제: 관리자는 언제나, 작성자는 관리자 답변이 없을 때만.
"""
from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.api.v1.permissions import check_document_access
from app.core.rate_limit import enforce_user_rate_limit
from app.db.models.document import Document
from app.db.models.inquiry import (
    STATUS_CLOSED,
    STATUS_IN_PROGRESS,
    STATUS_OPEN,
    STATUS_RESOLVED,
    Inquiry,
    InquiryMessage,
)
from app.db.models.notification import (
    KIND_INQUIRY_CREATED,
    KIND_INQUIRY_FOLLOWUP,
    KIND_INQUIRY_REPLIED,
    Notification,
)
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.inquiry import (
    DocumentRef,
    InquiryCreate,
    InquiryDetail,
    InquiryList,
    InquiryListItem,
    InquiryStatus,
    InquiryUpdate,
    MessageCreate,
    MessageOut,
)
from app.services.audit import log_audit
from app.services.notifications import notify_async

router = APIRouter()

INQUIRY_WRITE_BUCKET = "inquiry_write"
INQUIRY_WRITE_LIMIT = 20
INQUIRY_WRITE_WINDOW_SECONDS = 60
RESOURCE_TYPE = "inquiry"
STATUS_LABELS = {
    STATUS_OPEN: "접수",
    STATUS_IN_PROGRESS: "처리 중",
    STATUS_RESOLVED: "해결됨",
    STATUS_CLOSED: "종료",
}
TITLE_PREVIEW_LIMIT = 120


def _is_admin(user: User) -> bool:
    return user.role == "admin"


def _is_author(inquiry: Inquiry, user: User) -> bool:
    return str(inquiry.author_id) == str(user.id)


def _link(inquiry_id) -> str:
    return f"/inquiries/{inquiry_id}"


def _write_guard(user: User) -> None:
    enforce_user_rate_limit(
        str(user.id), INQUIRY_WRITE_BUCKET, limit=INQUIRY_WRITE_LIMIT, window_seconds=INQUIRY_WRITE_WINDOW_SECONDS,
    )


async def _load_visible(db: AsyncSession, inquiry_id, user: User) -> Inquiry:
    inquiry = await db.get(Inquiry, str(inquiry_id))
    if inquiry is None or not (_is_admin(user) or _is_author(inquiry, user)):
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다")
    return inquiry


async def _names(db: AsyncSession, user_ids) -> dict[str, str]:
    ids = {str(uid) for uid in user_ids if uid is not None}
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.username).where(User.id.in_(ids)))).all()
    return {str(row.id): row.username for row in rows}


async def _messages(db: AsyncSession, inquiry_id) -> list[InquiryMessage]:
    stmt = (
        select(InquiryMessage)
        .where(InquiryMessage.inquiry_id == str(inquiry_id))
        .order_by(InquiryMessage.created_at, InquiryMessage.id)
    )
    return list((await db.scalars(stmt)).all())


async def _opening_message(db: AsyncSession, inquiry_id) -> InquiryMessage | None:
    stmt = (
        select(InquiryMessage)
        .where(InquiryMessage.inquiry_id == str(inquiry_id))
        .order_by(InquiryMessage.created_at, InquiryMessage.id)
        .limit(1)
    )
    return (await db.scalars(stmt)).first()


async def _document_ref(db: AsyncSession, inquiry: Inquiry, viewer: User) -> DocumentRef | None:
    if inquiry.document_id is None:
        return None
    doc = await db.get(Document, str(inquiry.document_id))
    if doc is None:
        return None
    try:
        await check_document_access(db, doc, viewer, min_role="viewer")
    except HTTPException:
        # 볼 수 없는 문서의 이름은 보여 주지 않는다
        return None
    return DocumentRef(id=str(doc.id), original_filename=doc.original_filename, status=doc.status)


def _list_item(inquiry: Inquiry, names: dict[str, str]) -> InquiryListItem:
    return InquiryListItem(
        id=str(inquiry.id), title=inquiry.title, category=inquiry.category, status=inquiry.status,
        author_id=str(inquiry.author_id), author_name=names.get(str(inquiry.author_id), ""),
        document_id=str(inquiry.document_id) if inquiry.document_id else None,
        created_at=inquiry.created_at, updated_at=inquiry.updated_at,
    )


def _message_out(message: InquiryMessage, names: dict[str, str]) -> MessageOut:
    return MessageOut(
        id=str(message.id), author_id=str(message.author_id), author_name=names.get(str(message.author_id), ""),
        is_admin=message.is_admin, body=message.body, created_at=message.created_at,
    )


async def _detail(db: AsyncSession, inquiry: Inquiry, viewer: User) -> InquiryDetail:
    messages = await _messages(db, inquiry.id)
    names = await _names(db, [inquiry.author_id, *(m.author_id for m in messages)])
    is_author = _is_author(inquiry, viewer)
    has_admin_reply = any(m.is_admin for m in messages)
    base = _list_item(inquiry, names)
    return InquiryDetail(
        **base.model_dump(),
        error_snapshot=inquiry.error_snapshot,
        document=await _document_ref(db, inquiry, viewer),
        messages=[_message_out(m, names) for m in messages],
        is_author=is_author,
        has_admin_reply=has_admin_reply,
        can_edit=is_author and inquiry.status == STATUS_OPEN,
        can_reply=inquiry.status != STATUS_CLOSED,
        can_delete=_is_admin(viewer) or (is_author and not has_admin_reply),
    )


async def _notify_admins(db: AsyncSession, inquiry: Inquiry, kind: str, title: str, body: str) -> None:
    await notify_async(
        db, kind=kind, title=title, body=body, link=_link(inquiry.id), resource_type=RESOURCE_TYPE,
        resource_id=str(inquiry.id), user_ids=[], include_admins=True,
    )


async def _notify_author(db: AsyncSession, inquiry: Inquiry, kind: str, title: str, body: str) -> None:
    await notify_async(
        db, kind=kind, title=title, body=body, link=_link(inquiry.id), resource_type=RESOURCE_TYPE,
        resource_id=str(inquiry.id), user_ids=[str(inquiry.author_id)], include_admins=False,
    )


async def _document_for_create(db: AsyncSession, document_id, user: User) -> Document | None:
    if document_id is None:
        return None
    doc = await db.get(Document, str(document_id))
    if doc is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")
    await check_document_access(db, doc, user, min_role="viewer")
    return doc


@router.post("", status_code=201, response_model=InquiryDetail)
async def create_inquiry(
    data: InquiryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _write_guard(current_user)
    document = await _document_for_create(db, data.document_id, current_user)
    now = datetime.utcnow()
    inquiry = Inquiry(
        id=uuid4(), author_id=str(current_user.id), title=data.title, category=data.category,
        status=STATUS_OPEN, document_id=str(document.id) if document else None,
        error_snapshot=document.error_message if document else None, created_at=now, updated_at=now,
    )
    db.add(inquiry)
    # 첫 본문은 작성자가 쓴 글이므로 관리자 답변으로 세지 않는다
    db.add(InquiryMessage(
        id=uuid4(), inquiry_id=inquiry.id, author_id=str(current_user.id), body=data.body,
        is_admin=False, created_at=now,
    ))
    await db.flush()
    await _notify_admins(db, inquiry, KIND_INQUIRY_CREATED, f"새 관리자 문의: {data.title}", data.body)
    log_audit(db, str(current_user.id), "inquiry.create", "inquiry", str(inquiry.id),
              detail={"category": data.category, "document_id": str(inquiry.document_id) if inquiry.document_id else None})
    detail = await _detail(db, inquiry, current_user)
    await db.commit()
    return detail


@router.get("", response_model=InquiryList)
async def list_inquiries(
    status: Annotated[InquiryStatus | None, Query()] = None,
    limit: int = Query(20, gt=0, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Inquiry)
    if not _is_admin(current_user):
        stmt = stmt.where(Inquiry.author_id == str(current_user.id))
    if status is not None:
        stmt = stmt.where(Inquiry.status == status)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(
        stmt.order_by(Inquiry.updated_at.desc(), Inquiry.id).limit(limit).offset(offset)
    )).all()
    names = await _names(db, [row.author_id for row in rows])
    return InquiryList(total=total, items=[_list_item(row, names) for row in rows])


@router.get("/{inquiry_id}", response_model=InquiryDetail)
async def get_inquiry(
    inquiry_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inquiry = await _load_visible(db, inquiry_id, current_user)
    return await _detail(db, inquiry, current_user)


@router.post("/{inquiry_id}/messages", status_code=201, response_model=MessageOut)
async def add_message(
    inquiry_id: UUID,
    data: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _write_guard(current_user)
    inquiry = await _load_visible(db, inquiry_id, current_user)
    if inquiry.status == STATUS_CLOSED:
        raise HTTPException(status_code=409, detail="종료된 문의에는 메시지를 남길 수 없습니다")
    now = datetime.utcnow()
    as_admin = _is_admin(current_user) and not _is_author(inquiry, current_user)
    message = InquiryMessage(
        id=uuid4(), inquiry_id=inquiry.id, author_id=str(current_user.id), body=data.body,
        is_admin=as_admin, created_at=now,
    )
    db.add(message)
    inquiry.updated_at = now
    if as_admin:
        if inquiry.status == STATUS_OPEN:
            inquiry.status = STATUS_IN_PROGRESS
        await _notify_author(db, inquiry, KIND_INQUIRY_REPLIED, f"관리자가 문의에 답했습니다: {inquiry.title}", data.body)
    else:
        if inquiry.status == STATUS_RESOLVED:
            inquiry.status = STATUS_OPEN
        await _notify_admins(db, inquiry, KIND_INQUIRY_FOLLOWUP, f"문의에 추가 메시지가 왔습니다: {inquiry.title}", data.body)
    log_audit(db, str(current_user.id), "inquiry.message", "inquiry", str(inquiry.id), detail={"admin_reply": as_admin})
    out = MessageOut(
        id=str(message.id), author_id=str(current_user.id), author_name=current_user.username,
        is_admin=as_admin, body=data.body, created_at=now,
    )
    await db.commit()
    return out


def _ensure_content_editable(inquiry: Inquiry, is_author: bool) -> None:
    if not is_author:
        raise HTTPException(status_code=403, detail="문의 내용은 작성자만 고칠 수 있습니다")
    if inquiry.status != STATUS_OPEN:
        raise HTTPException(status_code=409, detail="관리자가 답변을 시작한 뒤에는 내용을 고칠 수 없습니다")


def _ensure_status_change_allowed(new_status: str, is_author: bool, user: User) -> None:
    if _is_admin(user):
        return
    if is_author and new_status == STATUS_CLOSED:
        return
    raise HTTPException(status_code=403, detail="작성자는 문의를 종료만 할 수 있습니다")


@router.patch("/{inquiry_id}", response_model=InquiryDetail)
async def update_inquiry(
    inquiry_id: UUID,
    data: InquiryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inquiry = await _load_visible(db, inquiry_id, current_user)
    is_author = _is_author(inquiry, current_user)
    now = datetime.utcnow()
    if data.title is not None or data.body is not None or data.category is not None:
        _ensure_content_editable(inquiry, is_author)
        if data.title is not None:
            inquiry.title = data.title
        if data.category is not None:
            inquiry.category = data.category
        if data.body is not None:
            opening = await _opening_message(db, inquiry.id)
            if opening is not None:
                opening.body = data.body
        inquiry.updated_at = now
    if data.status is not None and data.status != inquiry.status:
        _ensure_status_change_allowed(data.status, is_author, current_user)
        inquiry.status = data.status
        inquiry.updated_at = now
        if _is_admin(current_user) and not is_author:
            await _notify_author(
                db, inquiry, KIND_INQUIRY_REPLIED, f"문의 상태가 바뀌었습니다: {inquiry.title}",
                f"상태: {STATUS_LABELS[data.status]}",
            )
    log_audit(db, str(current_user.id), "inquiry.update", "inquiry", str(inquiry.id),
              detail={"fields": sorted(data.model_dump(exclude_none=True))})
    detail = await _detail(db, inquiry, current_user)
    await db.commit()
    return detail


@router.delete("/{inquiry_id}", status_code=204)
async def delete_inquiry(
    inquiry_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inquiry = await _load_visible(db, inquiry_id, current_user)
    if not _is_admin(current_user):
        has_admin_reply = (await db.scalars(
            select(InquiryMessage.id).where(
                InquiryMessage.inquiry_id == str(inquiry.id), InquiryMessage.is_admin.is_(True),
            ).limit(1)
        )).first() is not None
        if has_admin_reply:
            raise HTTPException(status_code=403, detail="관리자가 답변한 문의는 지울 수 없습니다. 종료할 수는 있습니다")
    await db.execute(delete(Notification).where(
        Notification.resource_type == RESOURCE_TYPE, Notification.resource_id == str(inquiry.id),
    ))
    log_audit(db, str(current_user.id), "inquiry.delete", "inquiry", str(inquiry.id))
    await db.delete(inquiry)
    await db.commit()
