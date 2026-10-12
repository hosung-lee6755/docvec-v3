"""프로젝트 엔드포인트 테스트 — 실제 Postgres(SAVEPOINT 롤백), 외부 서비스(Qdrant/MinIO/Redis)는 가짜.

대상: app/api/v1/endpoints/projects.py (CRUD, 멤버 초대/제거, 시스템 프롬프트, API 키, 연쇄 삭제).
"""
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api.v1.endpoints import projects as api
from app.core.crypto import decrypt_secret
from app.db.models.audit_log import AuditLog
from app.db.models.chat_conversation import ChatConversation
from app.db.models.chat_message import ChatMessage
from app.db.models.collection import Collection
from app.db.models.project import Project
from app.db.models.project_api_key import ProjectApiKey
from app.db.models.project_member import ProjectMember
from app.db.models.workflow import WorkflowDefinition
from tests.unit.api_pg_helpers import (  # noqa: F401
    add_member,
    db_session,
    make_collection,
    make_document,
    make_project,
    make_user,
    make_valid_graph,
    make_version,
    make_workflow,
)


def U(value) -> UUID:
    return UUID(str(value))


async def _count(db, model, *where) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(*where))


async def _expect(status: int, coro):
    with pytest.raises(HTTPException) as exc:
        await coro
    assert exc.value.status_code == status


@pytest.fixture
async def world(db_session):
    owner = await make_user(db_session, "editor", "owner")
    member = await make_user(db_session, "viewer", "member")
    stranger = await make_user(db_session, "viewer", "stranger")
    project = await make_project(db_session, owner, "P1")
    await add_member(db_session, project, member, "viewer", owner)
    return dict(db=db_session, owner=owner, member=member, stranger=stranger, project=project)


@pytest.fixture
def externals(monkeypatch):
    """cascade_delete_collection이 쓰는 Qdrant/MinIO와 API 키 속도 제한을 가짜로 대체."""
    qdrant, storage = MagicMock(), MagicMock()
    monkeypatch.setattr("app.services.qdrant_service.qdrant_service", qdrant)
    monkeypatch.setattr("app.services.storage.storage_service", storage)
    monkeypatch.setattr("app.core.rate_limit.enforce_user_rate_limit", MagicMock())
    return MagicMock(qdrant=qdrant, storage=storage)


# ---------- create / get / list ----------

@pytest.mark.asyncio
async def test_create_project_returns_owner_view(world):
    result = await api.create_project(
        api.ProjectCreate(name="새 프로젝트", description="설명"), world["db"], world["owner"])

    assert result["name"] == "새 프로젝트" and result["description"] == "설명"
    assert result["is_owner"] is True and result["role"] == "owner"
    assert result["collection_count"] == 0 and result["member_count"] == 1


def test_project_create_rejects_empty_name():
    with pytest.raises(ValidationError):
        api.ProjectCreate(name="")


@pytest.mark.asyncio
async def test_get_project_for_member_reports_role_and_member_count(world):
    await make_collection(world["db"], world["owner"], world["project"])

    result = await api.get_project(U(world["project"].id), world["db"], world["member"])

    assert result["is_owner"] is False and result["role"] == "viewer"
    assert result["member_count"] == 2 and result["collection_count"] == 1


@pytest.mark.asyncio
async def test_get_project_denies_stranger_and_404s_unknown(world):
    await _expect(403, api.get_project(U(world["project"].id), world["db"], world["stranger"]))
    await _expect(404, api.get_project(uuid4(), world["db"], world["owner"]))


@pytest.mark.asyncio
async def test_list_projects_includes_owned_and_member_projects_only(world):
    db = world["db"]
    foreign = await make_project(db, world["stranger"], "foreign")
    other_owned = await make_project(db, world["member"], "member-owned")

    owner_items = (await api.list_projects(db, world["owner"]))["items"]
    member_items = {i["name"]: i for i in (await api.list_projects(db, world["member"]))["items"]}

    assert [i["name"] for i in owner_items] == ["P1"]
    assert owner_items[0]["role"] == "owner" and owner_items[0]["member_count"] == 2
    assert set(member_items) == {"P1", "member-owned"}
    assert member_items["P1"]["role"] == "viewer" and member_items["P1"]["is_owner"] is False
    assert member_items["member-owned"]["role"] == "owner"
    assert str(foreign.id) not in {str(i["id"]) for i in member_items.values()}
    assert str(other_owned.id) in {str(i["id"]) for i in member_items.values()}


@pytest.mark.asyncio
async def test_list_projects_empty_for_user_without_projects(world):
    assert (await api.list_projects(world["db"], world["stranger"])) == {"items": []}


# ---------- update / system prompt ----------

@pytest.mark.asyncio
async def test_update_project_changes_fields_for_owner(world):
    result = await api.update_project(
        U(world["project"].id), api.ProjectUpdate(name="renamed", description="d2"),
        world["db"], world["owner"])
    assert result["name"] == "renamed" and result["description"] == "d2"


@pytest.mark.asyncio
async def test_update_project_partial_update_keeps_other_fields(world):
    await api.update_project(
        U(world["project"].id), api.ProjectUpdate(description="only-desc"), world["db"], world["owner"])
    saved = await world["db"].scalar(select(Project).where(Project.id == world["project"].id))
    assert saved.name == "P1" and saved.description == "only-desc"


@pytest.mark.asyncio
async def test_update_project_rejects_member_and_unknown(world):
    await _expect(403, api.update_project(
        U(world["project"].id), api.ProjectUpdate(name="x"), world["db"], world["member"]))
    await _expect(404, api.update_project(
        uuid4(), api.ProjectUpdate(name="x"), world["db"], world["owner"]))


@pytest.mark.asyncio
async def test_set_system_prompt_strips_and_blank_clears(world):
    pid = U(world["project"].id)
    set_result = await api.set_project_system_prompt(
        pid, api.ProjectSystemPromptUpdate(system_prompt="  친절하게  "), world["db"], world["owner"])
    assert set_result["system_prompt"] == "친절하게"

    cleared = await api.set_project_system_prompt(
        pid, api.ProjectSystemPromptUpdate(system_prompt="   "), world["db"], world["owner"])
    assert cleared["system_prompt"] is None


@pytest.mark.asyncio
async def test_set_system_prompt_owner_only(world):
    await _expect(403, api.set_project_system_prompt(
        U(world["project"].id), api.ProjectSystemPromptUpdate(system_prompt="x"),
        world["db"], world["member"]))
    await _expect(404, api.set_project_system_prompt(
        uuid4(), api.ProjectSystemPromptUpdate(system_prompt="x"), world["db"], world["owner"]))


# ---------- members ----------

@pytest.mark.asyncio
async def test_invite_adds_member_and_writes_audit(world):
    db = world["db"]
    invitee = await make_user(db, "viewer", "invitee")

    result = await api.invite_project_member(
        U(world["project"].id), api.ProjectMemberInvite(email=invitee.email, role="editor"),
        db, world["owner"])

    assert result["role"] == "editor" and result["email"] == invitee.email
    membership = await db.scalar(select(ProjectMember).where(
        ProjectMember.project_id == world["project"].id, ProjectMember.user_id == invitee.id))
    assert membership.role == "editor"
    audit = await db.scalar(select(AuditLog).where(AuditLog.action == "project.member_invite"))
    assert audit.detail == {"invitee_email": invitee.email, "role": "editor"}


@pytest.mark.asyncio
async def test_invite_existing_member_updates_role_without_duplicate(world):
    db = world["db"]
    await api.invite_project_member(
        U(world["project"].id), api.ProjectMemberInvite(email=world["member"].email, role="editor"),
        db, world["owner"])
    assert await _count(db, ProjectMember, ProjectMember.project_id == world["project"].id) == 1
    membership = await db.scalar(select(ProjectMember).where(
        ProjectMember.project_id == world["project"].id))
    assert membership.role == "editor"


@pytest.mark.asyncio
async def test_invite_rejections(world):
    pid, db = U(world["project"].id), world["db"]
    await _expect(404, api.invite_project_member(
        uuid4(), api.ProjectMemberInvite(email="x@example.com"), db, world["owner"]))
    await _expect(403, api.invite_project_member(
        pid, api.ProjectMemberInvite(email=world["stranger"].email), db, world["member"]))
    await _expect(404, api.invite_project_member(
        pid, api.ProjectMemberInvite(email="nobody@example.com"), db, world["owner"]))
    await _expect(400, api.invite_project_member(
        pid, api.ProjectMemberInvite(email=world["owner"].email), db, world["owner"]))


def test_member_invite_rejects_unknown_role():
    with pytest.raises(ValidationError):
        api.ProjectMemberInvite(email="a@b.c", role="admin")


@pytest.mark.asyncio
async def test_list_members_puts_owner_first_with_roles(world):
    result = await api.list_project_members(U(world["project"].id), world["db"], world["member"])
    assert [(m["username"], m["role"]) for m in result["items"]] == [
        ("owner", "owner"), ("member", "viewer")]


@pytest.mark.asyncio
async def test_list_members_denies_stranger(world):
    await _expect(403, api.list_project_members(U(world["project"].id), world["db"], world["stranger"]))


@pytest.mark.asyncio
async def test_remove_member_deletes_membership_and_audits(world):
    db = world["db"]
    result = await api.remove_project_member(
        U(world["project"].id), U(world["member"].id), db, world["owner"])
    assert result == {"message": "멤버가 제거되었습니다"}
    assert await _count(db, ProjectMember, ProjectMember.project_id == world["project"].id) == 0
    assert await _count(db, AuditLog, AuditLog.action == "project.member_remove") == 1


@pytest.mark.asyncio
async def test_remove_member_rejections(world):
    pid, db = U(world["project"].id), world["db"]
    await _expect(404, api.remove_project_member(uuid4(), U(world["member"].id), db, world["owner"]))
    await _expect(403, api.remove_project_member(pid, U(world["member"].id), db, world["member"]))
    await _expect(400, api.remove_project_member(pid, U(world["owner"].id), db, world["owner"]))


# ---------- api keys ----------

@pytest.mark.asyncio
async def test_api_key_lifecycle_never_exposes_secret(world, externals):
    pid, db = U(world["project"].id), world["db"]

    before = await api.list_project_api_keys(pid, db, world["owner"])
    assert [(i["provider"], i["registered"]) for i in before["items"]] == [
        ("openai", False), ("anthropic", False)]

    await api.set_project_api_key(pid, "openai", api.ProjectApiKeyUpdate(api_key="  sk-test  "),
                                  db, world["owner"])
    stored = await db.scalar(select(ProjectApiKey).where(ProjectApiKey.provider == "openai"))
    assert stored.encrypted_key != "sk-test" and decrypt_secret(stored.encrypted_key) == "sk-test"

    after = await api.list_project_api_keys(pid, db, world["owner"])
    assert after["items"][0]["registered"] is True and after["items"][0]["updated_at"] is not None
    assert after["items"][1]["registered"] is False
    assert "encrypted_key" not in after["items"][0]

    await api.delete_project_api_key(pid, "openai", db, world["owner"])
    assert await _count(db, ProjectApiKey, ProjectApiKey.project_id == world["project"].id) == 0


@pytest.mark.asyncio
async def test_set_api_key_overwrites_existing_key(world, externals):
    pid, db = U(world["project"].id), world["db"]
    await api.set_project_api_key(pid, "anthropic", api.ProjectApiKeyUpdate(api_key="old"), db, world["owner"])
    await api.set_project_api_key(pid, "anthropic", api.ProjectApiKeyUpdate(api_key="new"), db, world["owner"])
    rows = (await db.scalars(select(ProjectApiKey))).all()
    assert len(rows) == 1 and decrypt_secret(rows[0].encrypted_key) == "new"


@pytest.mark.asyncio
async def test_set_api_key_blank_after_strip_is_422(world, externals):
    await _expect(422, api.set_project_api_key(
        U(world["project"].id), "openai", api.ProjectApiKeyUpdate(api_key="   "),
        world["db"], world["owner"]))


@pytest.mark.asyncio
async def test_api_key_endpoints_are_owner_only(world, externals):
    pid, db = U(world["project"].id), world["db"]
    await _expect(403, api.list_project_api_keys(pid, db, world["member"]))
    await _expect(403, api.set_project_api_key(
        pid, "openai", api.ProjectApiKeyUpdate(api_key="k"), db, world["member"]))
    await _expect(403, api.delete_project_api_key(pid, "openai", db, world["member"]))
    await _expect(404, api.list_project_api_keys(uuid4(), db, world["owner"]))
    await _expect(404, api.set_project_api_key(
        uuid4(), "openai", api.ProjectApiKeyUpdate(api_key="k"), db, world["owner"]))
    await _expect(404, api.delete_project_api_key(uuid4(), "openai", db, world["owner"]))


# ---------- delete / cascade ----------

async def _populate_project(world):
    """컬렉션+문서, 대화/메시지, API 키, 워크플로우(버전·그래프), 멤버가 모두 달린 프로젝트."""
    db, owner, project = world["db"], world["owner"], world["project"]
    collection = await make_collection(db, owner, project)
    doc = await make_document(db, owner, collection)
    conversation = ChatConversation(
        id=str(uuid4()), user_id=str(owner.id), project_id=str(project.id),
        model_key="m", title="t")
    db.add(conversation)
    await db.flush()
    db.add(ChatMessage(conversation_id=conversation.id, query="q", answer="a", status="DONE"))
    db.add(ProjectApiKey(project_id=str(project.id), provider="openai", encrypted_key="x"))
    workflow = await make_workflow(db, owner, project)
    version = await make_version(db, workflow, owner)
    await make_valid_graph(db, version)
    await db.flush()
    return collection, doc, conversation, workflow


@pytest.mark.asyncio
async def test_delete_project_cascades_everything(world, externals):
    db = world["db"]
    collection, doc, conversation, workflow = await _populate_project(world)

    result = await api.delete_project(U(world["project"].id), db, world["owner"])

    assert result == {"message": "Project deleted"}
    pid = world["project"].id
    assert await _count(db, Project, Project.id == pid) == 0
    assert await _count(db, Collection, Collection.project_id == pid) == 0
    assert await _count(db, ChatConversation, ChatConversation.id == conversation.id) == 0
    assert await _count(db, ChatMessage, ChatMessage.conversation_id == conversation.id) == 0
    assert await _count(db, ProjectApiKey, ProjectApiKey.project_id == pid) == 0
    assert await _count(db, ProjectMember, ProjectMember.project_id == pid) == 0
    assert await _count(db, WorkflowDefinition, WorkflowDefinition.id == workflow.id) == 0
    externals.qdrant.delete_by_document.assert_called_once()
    externals.storage.delete_file.assert_called_once()


@pytest.mark.asyncio
async def test_delete_project_allows_admin_but_not_member(world, externals):
    db = world["db"]
    admin = await make_user(db, "admin", "root")
    await _expect(403, api.delete_project(U(world["project"].id), db, world["member"]))
    assert await api.delete_project(U(world["project"].id), db, admin) == {"message": "Project deleted"}
    await _expect(404, api.delete_project(uuid4(), db, admin))
