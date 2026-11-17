"""화면 알림(전체 점검 2-7): 받는 사람, 중복 방지, 알림 오류가 처리를 막지 않는지."""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.notification import KIND_DOCUMENT_FAILED, KIND_REVIEW_WAITING, Notification
from app.db.models.user import User
from app.services import notifications
from tests.conftest import TEST_DATABASE_URL

SYNC_URL = TEST_DATABASE_URL.replace("+asyncpg", "+psycopg2")


def _user(db, role, is_active=True):
    user = User(id=uuid4(), email=f"{uuid4()}@example.com", username=role, hashed_password="!",
                role=role, is_active=is_active)
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def db():
    engine = create_engine(SYNC_URL)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    created: list = []
    session.info["created"] = created
    yield session
    session.rollback()
    session.query(Notification).delete()
    session.commit()
    session.close()
    engine.dispose()


def _doc(owner):
    return SimpleNamespace(id=uuid4(), filename="계약서.pdf", created_by=owner.id)


def _kinds_for(db, user):
    return [row.kind for row in db.query(Notification).filter(Notification.user_id == user.id).all()]


def test_failure_notifies_uploader_and_active_admins_only(db):
    uploader, admin = _user(db, "editor"), _user(db, "admin")
    disabled_admin, bystander = _user(db, "admin", is_active=False), _user(db, "viewer")

    notifications.notify_document_failed(db, _doc(uploader), "변환에 실패했습니다")
    db.commit()

    assert _kinds_for(db, uploader) == [KIND_DOCUMENT_FAILED]
    assert _kinds_for(db, admin) == [KIND_DOCUMENT_FAILED]
    assert _kinds_for(db, disabled_admin) == [] and _kinds_for(db, bystander) == []


def test_review_waiting_notifies_only_the_uploader(db):
    uploader, admin = _user(db, "editor"), _user(db, "admin")

    notifications.notify_review_waiting(db, _doc(uploader))
    db.commit()

    assert _kinds_for(db, uploader) == [KIND_REVIEW_WAITING] and _kinds_for(db, admin) == []


def test_same_document_does_not_pile_up_unread_notifications(db):
    uploader = _user(db, "editor")
    doc = _doc(uploader)

    notifications.notify_review_waiting(db, doc)
    db.commit()
    assert notifications.notify_review_waiting(db, doc) == 0


def test_notifies_again_after_the_previous_one_was_read(db):
    from datetime import datetime

    uploader = _user(db, "editor")
    doc = _doc(uploader)
    notifications.notify_review_waiting(db, doc)
    db.commit()
    db.query(Notification).filter(Notification.user_id == uploader.id).update({"read_at": datetime.utcnow()})
    db.commit()

    assert notifications.notify_review_waiting(db, doc) == 1


def test_long_text_is_cut_to_column_limits(db):
    uploader = _user(db, "editor")
    doc = SimpleNamespace(id=uuid4(), filename="가" * 400, created_by=uploader.id)

    notifications.notify_document_failed(db, doc, "나" * 2000)
    db.commit()

    row = db.query(Notification).filter(Notification.user_id == uploader.id).one()
    assert len(row.title) == notifications.TITLE_MAX and len(row.body) == notifications.BODY_MAX


def test_notification_error_does_not_break_the_callers_transaction(db, monkeypatch):
    uploader = _user(db, "editor")
    marker = User(id=uuid4(), email=f"{uuid4()}@example.com", username="marker", hashed_password="!", role="viewer")
    db.add(marker)
    # 알림 행을 만들다 오류가 나도 호출한 쪽이 넣던 행은 그대로 커밋돼야 한다
    monkeypatch.setattr(notifications, "_rows", lambda *args, **kwargs: [object()])

    assert notifications.notify_review_waiting(db, _doc(uploader)) == 0
    db.commit()

    assert db.get(User, marker.id) is not None and _kinds_for(db, uploader) == []


def test_connector_account_is_replaced_by_admins(db):
    service = _user(db, "viewer")
    service.auth_source = "system"
    admin = _user(db, "admin")
    db.commit()

    notifications.notify_review_waiting(db, _doc(service))
    db.commit()

    assert _kinds_for(db, service) == [] and _kinds_for(db, admin) == [KIND_REVIEW_WAITING]


def test_unknown_uploader_falls_back_to_admins(db):
    admin = _user(db, "admin")
    ghost = SimpleNamespace(id=uuid4(), filename="a.pdf", created_by=uuid4())

    notifications.notify_review_waiting(db, ghost)
    db.commit()

    assert _kinds_for(db, admin) == [KIND_REVIEW_WAITING]


def test_document_without_expected_fields_never_raises():
    assert notifications.notify_document_failed(object(), SimpleNamespace(), "오류") == 0
