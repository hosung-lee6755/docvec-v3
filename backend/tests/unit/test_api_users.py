"""사용자 엔드포인트 테스트 — 실제 Postgres(SAVEPOINT 롤백).

대상: app/api/v1/endpoints/users.py (목록·내 프로필·비밀번호·시스템 프롬프트·관리자 수정/삭제 연쇄·개인 API 키).
기존 test_users_endpoints.py(mock 기반 삭제 분기)를 보완한다.
"""
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api.v1.endpoints import users as api
from app.core.crypto import decrypt_secret
from app.core.security import get_password_hash, verify_password
from app.db.models.audit_log import AuditLog
from app.db.models.chat_conversation import ChatConversation
from app.db.models.chat_message import ChatMessage
from app.db.models.collection import Collection
from app.db.models.collection_member import CollectionMember
from app.db.models.document_revision import DocumentTextRevision
from app.db.models.golden_query import GoldenQuery
from app.db.models.project import Project
from app.db.models.project_member import ProjectMember
from app.db.models.user import User
from app.db.models.user_api_key import UserApiKey
from tests.unit.api_pg_helpers import (  # noqa: F401
    add_member,
    db_session,
    make_collection,
    make_document,
    make_project,
    make_user,
)


def U(value) -> UUID:
    return UUID(str(value))


async def _count(db, model, *where) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(*where))


async def _expect(status: int, coro):
    with pytest.raises(HTTPException) as exc:
        await coro
    assert exc.value.status_code == status
    return exc.value


@pytest.fixture
async def world(db_session):
    admin = await make_user(db_session, "admin", "root")
    viewer = await make_user(db_session, "viewer", "viewer")
    return dict(db=db_session, admin=admin, viewer=viewer)


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    monkeypatch.setattr("app.core.rate_limit.enforce_user_rate_limit", MagicMock())


# ---------- list / profile ----------

@pytest.mark.asyncio
async def test_list_users_admin_sees_everyone_viewer_forbidden(world):
    result = await api.list_users(world["db"], world["admin"])
    emails = {u.email for u in result["items"]}
    assert {world["admin"].email, world["viewer"].email} <= emails
    await _expect(403, api.list_users(world["db"], world["viewer"]))


@pytest.mark.asyncio
async def test_get_my_profile_returns_current_user(world):
    me = await api.get_my_profile(world["viewer"])
    assert str(me.id) == str(world["viewer"].id) and me.role == "viewer"


@pytest.mark.asyncio
async def test_update_my_profile_trims_username(world):
    result = await api.update_my_profile(api.ProfileUpdate(username="  새이름  "), world["db"], world["viewer"])
    assert result.username == "새이름"


def test_profile_update_rejects_empty_username():
    with pytest.raises(ValidationError):
        api.ProfileUpdate(username="")


@pytest.mark.asyncio
async def test_change_password_requires_correct_current_password(world):
    db = world["db"]
    user = await make_user(db, "viewer", "pw")
    user.hashed_password = get_password_hash("old-password-1")
    await db.flush()

    await _expect(403, api.change_my_password(
        api.PasswordChange(current_password="wrong", new_password="new-password-1"), db, user))

    result = await api.change_my_password(
        api.PasswordChange(current_password="old-password-1", new_password="new-password-1"), db, user)
    assert result == {"message": "비밀번호가 변경되었습니다"}
    assert verify_password("new-password-1", user.hashed_password)
    assert not verify_password("old-password-1", user.hashed_password)


def test_password_change_enforces_min_length():
    with pytest.raises(ValidationError):
        api.PasswordChange(current_password="x", new_password="short")


@pytest.mark.asyncio
async def test_set_my_system_prompt_strips_and_clears(world):
    db, user = world["db"], world["viewer"]
    got = await api.set_my_system_prompt(api.SystemPromptUpdate(system_prompt="  hi  "), db, user)
    assert got.system_prompt == "hi"
    cleared = await api.set_my_system_prompt(api.SystemPromptUpdate(system_prompt=None), db, user)
    assert cleared.system_prompt is None


# ---------- update_user ----------

@pytest.mark.asyncio
async def test_update_user_changes_role_and_active_and_audits(world):
    db = world["db"]
    result = await api.update_user(
        U(world["viewer"].id), api.UserUpdate(role="editor", is_active=False), db, world["admin"])
    assert result.role == "editor" and result.is_active is False
    audit = await db.scalar(select(AuditLog).where(AuditLog.action == "user.update"))
    assert audit.resource_id == str(world["viewer"].id)
    assert audit.detail == {"role": "editor", "is_active": False}


@pytest.mark.asyncio
async def test_update_user_empty_patch_changes_nothing(world):
    result = await api.update_user(U(world["viewer"].id), api.UserUpdate(), world["db"], world["admin"])
    assert result.role == "viewer" and result.is_active is True


@pytest.mark.asyncio
async def test_update_user_guards(world):
    db = world["db"]
    await _expect(403, api.update_user(U(world["viewer"].id), api.UserUpdate(role="admin"), db, world["viewer"]))
    await _expect(403, api.update_user(UUID(api.SYSTEM_USER_ID), api.UserUpdate(is_active=False), db, world["admin"]))
    await _expect(404, api.update_user(uuid4(), api.UserUpdate(is_active=False), db, world["admin"]))


def test_user_update_rejects_unknown_role():
    with pytest.raises(ValidationError):
        api.UserUpdate(role="superuser")


# ---------- delete_user (실제 FK 그래프) ----------

@pytest.mark.asyncio
async def test_delete_user_removes_owned_resources_memberships_chats_and_keys(world):
    db, admin = world["db"], world["admin"]
    target = await make_user(db, "editor", "target")
    friend = await make_user(db, "viewer", "friend")
    # 대상이 소유한 프로젝트(+컬렉션) / 독립 컬렉션
    project = await make_project(db, target, "owned")
    await make_collection(db, target, project, name="in-project")
    standalone = await make_collection(db, target, None, name="standalone")
    # 대상이 멤버로 참여한 남의 프로젝트/컬렉션
    other_project = await make_project(db, friend, "friend-proj")
    await add_member(db, other_project, target, "viewer", friend)
    other_col = await make_collection(db, friend, None, name="friend-col")
    db.add(CollectionMember(collection_id=str(other_col.id), user_id=str(target.id),
                            role="viewer", invited_by=str(friend.id)))
    # 대화/키/리비전 이력
    conv = ChatConversation(id=str(uuid4()), user_id=str(target.id), model_key="m", title="t")
    db.add(conv)
    await db.flush()
    db.add(ChatMessage(conversation_id=conv.id, query="q", status="DONE"))
    db.add(UserApiKey(user_id=str(target.id), provider="openai", encrypted_key="x"))
    doc = await make_document(db, friend, other_col)
    revision = DocumentTextRevision(document_id=str(doc.id), source="MANUAL", parsed_text="t",
                                    created_by=str(target.id))
    db.add(revision)
    await db.flush()

    result = await api.delete_user(U(target.id), db, admin)

    assert result is None
    tid = target.id
    assert await _count(db, User, User.id == tid) == 0
    assert await _count(db, Project, Project.created_by == tid) == 0
    assert await _count(db, Collection, Collection.id == standalone.id) == 0
    assert await _count(db, ProjectMember, ProjectMember.user_id == tid) == 0
    assert await _count(db, CollectionMember, CollectionMember.user_id == tid) == 0
    assert await _count(db, ChatConversation, ChatConversation.user_id == tid) == 0
    assert await _count(db, UserApiKey, UserApiKey.user_id == tid) == 0
    # 리비전 이력은 보존되고 작성자만 비워진다
    kept = await db.scalar(select(DocumentTextRevision).where(DocumentTextRevision.id == revision.id),
                           execution_options={"populate_existing": True})
    assert kept is not None and kept.created_by is None
    # 남의 리소스는 그대로
    assert await _count(db, Project, Project.id == other_project.id) == 1
    assert await _count(db, Collection, Collection.id == other_col.id) == 1
    assert await _count(db, AuditLog, AuditLog.action == "user.delete") == 1


@pytest.mark.asyncio
async def test_delete_user_blocked_by_unowned_reference_returns_409(world):
    """남의 컬렉션에 골든 쿼리를 만든 계정은 cascade가 다루지 않아 409로 명확히 실패한다."""
    db, admin = world["db"], world["admin"]
    target = await make_user(db, "editor", "target")
    friend = await make_user(db, "viewer", "friend")
    col = await make_collection(db, friend, None, name="friend-col")
    db.add(GoldenQuery(collection_id=str(col.id), query="q", expected_document_ids=[], created_by=str(target.id)))
    await db.flush()

    error = await _expect(409, api.delete_user(U(target.id), db, admin))
    assert "삭제할 수 없습니다" in error.detail


@pytest.mark.asyncio
async def test_delete_user_guards(world):
    db = world["db"]
    await _expect(403, api.delete_user(UUID(api.SYSTEM_USER_ID), db, world["admin"]))
    await _expect(404, api.delete_user(uuid4(), db, world["admin"]))
    await _expect(403, api.delete_user(U(world["viewer"].id), db, world["viewer"]))


# ---------- 개인 API 키 ----------

@pytest.mark.asyncio
async def test_my_api_key_lifecycle_encrypts_and_never_returns_secret(world):
    db, user = world["db"], world["viewer"]
    before = await api.list_my_api_keys(db, user)
    assert [(i["provider"], i["registered"]) for i in before["items"]] == [("openai", False), ("anthropic", False)]

    await api.set_my_api_key("anthropic", api.ApiKeyUpdate(api_key="  sk-ant  "), db, user)
    stored = await db.scalar(select(UserApiKey).where(UserApiKey.user_id == user.id))
    assert stored.encrypted_key != "sk-ant" and decrypt_secret(stored.encrypted_key) == "sk-ant"

    after = await api.list_my_api_keys(db, user)
    assert after["items"][1]["registered"] is True and after["items"][0]["registered"] is False
    assert all("encrypted_key" not in item for item in after["items"])

    await api.delete_my_api_key("anthropic", db, user)
    assert await _count(db, UserApiKey, UserApiKey.user_id == user.id) == 0
    actions = (await db.scalars(select(AuditLog.action).order_by(AuditLog.created_at))).all()
    assert {"api_key.set", "api_key.delete"} <= set(actions)


@pytest.mark.asyncio
async def test_set_my_api_key_overwrites_and_rejects_blank(world):
    db, user = world["db"], world["viewer"]
    await api.set_my_api_key("openai", api.ApiKeyUpdate(api_key="one"), db, user)
    await api.set_my_api_key("openai", api.ApiKeyUpdate(api_key="two"), db, user)
    rows = (await db.scalars(select(UserApiKey).where(UserApiKey.user_id == user.id))).all()
    assert len(rows) == 1 and decrypt_secret(rows[0].encrypted_key) == "two"

    await _expect(422, api.set_my_api_key("openai", api.ApiKeyUpdate(api_key="   "), db, user))
