"""화면 알림 만들기(전체 점검 2-7, 2026-11-16).

알림은 부가 기능이다. 알림을 남기다 난 오류가 문서 처리나 동기화를 실패시키면 안 되므로, 여기 함수는
오류를 로그에만 남기고 삼킨다. 호출한 쪽의 트랜잭션도 건드리지 않도록 세이브포인트 안에서 쓴다.
커밋은 호출한 쪽이 한다.

받는 사람
- 문서 처리 실패: 문서를 올린 사람과 관리자
- 검토 대기: 문서를 올린 사람(검토는 올린 사람이 결과를 보고 승인하는 흐름이다)
- 파일 서버 동기화 실패: 관리자

파일 서버 연결이 가져온 문서는 올린 사람이 연결용 계정(auth_source가 system)이다. 그 계정은 화면을
보지 않으므로 받는 사람에서 빼고, 사람이 한 명도 남지 않으면 관리자에게 보낸다(실측으로 확인, 2026-11-16).

워커는 동기 세션을, 동기화 엔진은 비동기 세션을 쓴다. 두 쪽이 같은 조회문과 같은 행 만들기 함수를
쓰도록 나눠 두었다.
"""
import logging
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select

from app.db.models.notification import (
    KIND_DOCUMENT_FAILED,
    KIND_REVIEW_WAITING,
    KIND_SYNC_FAILED,
    Notification,
)
from app.db.models.user import User

logger = logging.getLogger(__name__)

SYSTEM_AUTH_SOURCE = "system"
TITLE_MAX = 255
BODY_MAX = 500


def _admins_stmt():
    return select(User.id).where(User.role == "admin", User.is_active.is_(True))


def _people_stmt(user_ids: set[str]):
    """받는 사람 가운데 실제로 화면을 보는 계정만 고른다(쓰는 중인 계정이고 연결용 계정이 아닌 것)."""
    return select(User.id).where(
        User.id.in_(user_ids), User.is_active.is_(True), User.auth_source != SYSTEM_AUTH_SOURCE,
    )


def _already_notified_stmt(kind: str, resource_id: str):
    return select(Notification.user_id).where(
        Notification.kind == kind,
        Notification.resource_id == resource_id,
        Notification.read_at.is_(None),
    )


def _rows(recipients: set[str], skip: set[str], *, kind: str, title: str, body: str | None,
          link: str | None, resource_type: str, resource_id: str) -> list[Notification]:
    now = datetime.utcnow()
    return [
        Notification(
            id=uuid4(), user_id=user_id, kind=kind, title=title[:TITLE_MAX],
            body=(body or None) and body[:BODY_MAX], link=link,
            resource_type=resource_type, resource_id=resource_id, created_at=now,
        )
        for user_id in sorted(recipients - skip)
    ]


def notify(db, *, kind: str, title: str, body: str | None, link: str | None, resource_type: str,
           resource_id: str, user_ids: list, include_admins: bool) -> int:
    """동기 세션용. 만든 알림 수를 돌려준다. 실패하면 0을 돌려주고 로그만 남긴다."""
    try:
        with db.begin_nested():
            named = {str(u) for u in user_ids if u}
            recipients = {str(row[0]) for row in db.execute(_people_stmt(named)).all()} if named else set()
            if include_admins or not recipients:
                recipients |= {str(row[0]) for row in db.execute(_admins_stmt()).all()}
            skip = {str(row[0]) for row in db.execute(_already_notified_stmt(kind, resource_id)).all()}
            rows = _rows(recipients, skip, kind=kind, title=title, body=body, link=link,
                         resource_type=resource_type, resource_id=resource_id)
            db.add_all(rows)
        return len(rows)
    except Exception:
        logger.exception("notification failed: kind=%s resource=%s", kind, resource_id)
        return 0


async def notify_async(db, *, kind: str, title: str, body: str | None, link: str | None, resource_type: str,
                       resource_id: str, user_ids: list, include_admins: bool) -> int:
    """비동기 세션용. notify와 같은 규칙이다."""
    try:
        async with db.begin_nested():
            named = {str(u) for u in user_ids if u}
            recipients = (
                {str(row[0]) for row in (await db.execute(_people_stmt(named))).all()} if named else set()
            )
            if include_admins or not recipients:
                recipients |= {str(row[0]) for row in (await db.execute(_admins_stmt())).all()}
            skip = {
                str(row[0]) for row in (await db.execute(_already_notified_stmt(kind, resource_id))).all()
            }
            rows = _rows(recipients, skip, kind=kind, title=title, body=body, link=link,
                         resource_type=resource_type, resource_id=resource_id)
            db.add_all(rows)
        return len(rows)
    except Exception:
        logger.exception("notification failed: kind=%s resource=%s", kind, resource_id)
        return 0


def _document_name(document) -> str:
    return getattr(document, "original_filename", None) or getattr(document, "filename", None) or "이름 없는 문서"


def _notify_about_document(db, document, *, kind: str, title: str, body: str | None, include_admins: bool) -> int:
    # 문서에서 값을 꺼내다 나는 오류도 처리를 막으면 안 된다. notify 밖에서 나는 오류라 여기서 따로 막는다
    try:
        document_id = str(document.id)
        full_title = f"{title}: {_document_name(document)}"
        user_ids = [getattr(document, "created_by", None)]
    except Exception:
        logger.exception("notification skipped: kind=%s", kind)
        return 0
    return notify(
        db, kind=kind, title=full_title, body=body, link=f"/documents/{document_id}",
        resource_type="document", resource_id=document_id, user_ids=user_ids, include_admins=include_admins,
    )


def notify_document_failed(db, document, error_message: str) -> int:
    return _notify_about_document(
        db, document, kind=KIND_DOCUMENT_FAILED, title="문서 처리에 실패했습니다",
        body=error_message, include_admins=True,
    )


def notify_review_waiting(db, document) -> int:
    return _notify_about_document(
        db, document, kind=KIND_REVIEW_WAITING, title="검토를 기다리는 문서가 있습니다",
        body="처리 결과를 확인하고 승인하면 다음 단계로 넘어갑니다.", include_admins=False,
    )


async def notify_sync_failed(db, connector_id, connector_name: str, error_message: str | None) -> int:
    return await notify_async(
        db, kind=KIND_SYNC_FAILED, title=f"파일 서버 동기화에 실패했습니다: {connector_name}",
        body=error_message, link="/connectors", resource_type="connector",
        resource_id=str(connector_id), user_ids=[], include_admins=True,
    )
