"""v3 마일스톤 3 — 원천 연결 관리 API와 원천 관리 대상의 수동 수정 차단."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api.v1.endpoints import connectors as api
from app.api.v1.endpoints import groups as groups_api
from app.api.v1.endpoints import users as users_api
from app.api.v1.endpoints.documents import acl as acl_api
from app.api.v1.endpoints.documents import listing as listing_api
from app.api.v1.endpoints.documents import metadata as metadata_api
from app.core.crypto import decrypt_secret
from app.db.models.audit_log import AuditLog
from app.db.models.document import Document
from app.db.models.source_connector import SourceConnector, SourceItem
from app.db.models.user import User
from app.db.models.user_group import UserGroup
from app.schemas.access import DocumentAclUpdate, GroupMemberAdd, GroupUpdate
from app.schemas.document import DocumentMetadataUpdateRequest
from tests.unit.api_pg_helpers import (  # noqa: F401
    db_session,
    make_collection,
    make_document,
    make_project,
    make_user,
)

pytestmark = pytest.mark.asyncio
SECRET = "smb-password-123"


def _create_body(collection_id, **over):
    body = dict(name="영업 공유", host="fs01.corp.local", share="docs", base_path="부서/영업",
                username="svc-docvec", password=SECRET, collection_id=collection_id,
                level_rules=[{"prefix": "exec/", "level": "Confidential"}])
    return api.ConnectorCreate(**{**body, **over})


@pytest.fixture
async def world(db_session):  # noqa: F811
    db = db_session
    admin = await make_user(db, "admin")
    editor = await make_user(db, "editor")
    project = await make_project(db, admin)
    col = await make_collection(db, admin, project)
    await db.commit()
    return SimpleNamespace(db=db, admin=admin, editor=editor, col=col)


async def _audits(db, action, resource_id):
    return (await db.scalars(
        select(AuditLog).where(AuditLog.action == action, AuditLog.resource_id == resource_id)
    )).all()


async def test_only_admins_manage_connectors(world):
    with pytest.raises(HTTPException) as exc:
        await api.list_connectors(world.db, world.editor)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        await api.create_connector(_create_body(world.col.id), world.db, world.editor)
    assert exc.value.status_code == 403


async def test_create_encrypts_password_hides_it_and_makes_a_system_user(world):
    out = await api.create_connector(_create_body(world.col.id), world.db, world.admin)

    assert "password" not in out and "password_encrypted" not in out
    assert SECRET not in str(out)
    connector = await world.db.get(SourceConnector, out["id"])
    assert connector.password_encrypted != SECRET and decrypt_secret(connector.password_encrypted) == SECRET
    assert connector.base_path == "부서/영업"
    service = await world.db.get(User, connector.service_user_id)
    assert (service.auth_source, service.is_active) == ("system", False)
    assert await _audits(world.db, "connector.create", out["id"])
    assert out["id"] in [c["id"] for c in await api.list_connectors(world.db, world.admin)]


@pytest.mark.parametrize("over", [
    {"host": "fs01; rm -rf /"}, {"share": "docs/../x"}, {"base_path": "a/../b"},
    {"sync_interval_minutes": 1}, {"level_rules": [{"prefix": "x/", "level": "TopSecret"}]},
    {"service_account_sid": "not-a-sid"},
])
async def test_create_validates_input(world, over):
    with pytest.raises(ValidationError):
        _create_body(world.col.id, **over)


async def test_create_with_unknown_collection_is_404(world):
    with pytest.raises(HTTPException) as exc:
        await api.create_connector(_create_body(uuid4()), world.db, world.admin)
    assert exc.value.status_code == 404


async def test_update_replaces_password_only_when_given(world):
    out = await api.create_connector(_create_body(world.col.id), world.db, world.admin)
    await api.update_connector(out["id"], api.ConnectorUpdate(enabled=False), world.db, world.admin)
    connector = await world.db.get(SourceConnector, out["id"])
    assert connector.enabled is False and decrypt_secret(connector.password_encrypted) == SECRET

    await api.update_connector(out["id"], api.ConnectorUpdate(password="new-secret-9"), world.db, world.admin)
    await world.db.refresh(connector)
    assert decrypt_secret(connector.password_encrypted) == "new-secret-9"
    [row] = [a for a in await _audits(world.db, "connector.update", out["id"]) if "password" in a.detail["fields"]]
    assert "new-secret-9" not in str(row.detail)


async def test_sync_now_queues_a_task_and_is_audited(world):
    out = await api.create_connector(_create_body(world.col.id), world.db, world.admin)
    with patch("app.pipeline.tasks.connectors.sync_connector_task") as task:
        result = await api.sync_connector_now(out["id"], world.db, world.admin)
    assert result["status"] == "queued"
    task.delay.assert_called_once_with(out["id"], str(world.admin.id))
    assert await _audits(world.db, "connector.sync_request", out["id"])


async def test_detail_lists_held_items_with_reasons(world):
    out = await api.create_connector(_create_body(world.col.id), world.db, world.admin)
    world.db.add(SourceItem(id=uuid4(), connector_id=out["id"], path="held/a.pdf", state="held",
                            hold_reason="deny_ace"))
    await world.db.commit()

    detail = await api.get_connector(out["id"], world.db, world.admin)
    assert detail["held_count"] == 1
    assert detail["problem_items"][0]["path"] == "held/a.pdf" and detail["problem_items"][0]["reason"] == "deny_ace"


async def test_delete_removes_connector_documents(world, monkeypatch):
    monkeypatch.setattr("app.services.qdrant_service.qdrant_service", MagicMock())
    monkeypatch.setattr("app.services.storage.storage_service", MagicMock())
    monkeypatch.setattr("app.services.summary_index.delete_document_summary", MagicMock())
    monkeypatch.setattr(listing_api, "release_original", AsyncMock())
    out = await api.create_connector(_create_body(world.col.id), world.db, world.admin)
    connector = await world.db.get(SourceConnector, out["id"])
    service = await world.db.get(User, connector.service_user_id)
    doc = await make_document(world.db, service, world.col)
    world.db.add(SourceItem(id=uuid4(), connector_id=connector.id, path="a.pdf", document_id=doc.id))
    await world.db.commit()
    doc_id = doc.id

    await api.delete_connector(out["id"], world.db, world.admin)

    # 아이덴티티 맵이 아니라 DB에 행이 남아 있는지 센다
    assert await world.db.scalar(select(func.count()).select_from(Document).where(Document.id == doc_id)) == 0
    assert await world.db.scalar(
        select(func.count()).select_from(SourceConnector).where(SourceConnector.id == out["id"])
    ) == 0
    [row] = await _audits(world.db, "connector.delete", out["id"])
    assert row.detail["documents_removed"] == 1


# -- 원천 관리 대상의 수동 수정 차단 -------------------------------------------------

async def test_connector_document_acl_and_level_cannot_be_edited(world):
    out = await api.create_connector(_create_body(world.col.id), world.db, world.admin)
    doc = await make_document(world.db, world.admin, world.col)
    world.db.add(SourceItem(id=uuid4(), connector_id=out["id"], path="a.pdf", document_id=doc.id))
    await world.db.commit()

    with pytest.raises(HTTPException) as exc:
        await acl_api.replace_document_acl(doc.id, DocumentAclUpdate(entries=[]), world.db, world.admin)
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        await metadata_api.update_document_metadata(
            doc.id, DocumentMetadataUpdateRequest(security_level="Public"), world.db, world.admin
        )
    assert exc.value.status_code == 409
    acl = await acl_api.get_document_acl(doc.id, world.db, world.admin)
    assert acl.source_managed is True


async def test_directory_group_cannot_be_edited_by_hand(world):
    group = UserGroup(id=str(uuid4()), name=f"ad-{uuid4().hex[:6]}", source="ldap",
                      external_id=f"S-1-5-21-1-{uuid4().int % 10**6}")
    world.db.add(group)
    await world.db.commit()

    for call in (
        lambda: groups_api.update_group(group.id, GroupUpdate(name="renamed"), world.db, world.admin),
        lambda: groups_api.delete_group(group.id, world.db, world.admin),
        lambda: groups_api.add_group_member(group.id, GroupMemberAdd(user_id=world.editor.id), world.db, world.admin),
        lambda: groups_api.remove_group_member(group.id, world.editor.id, world.db, world.admin),
    ):
        with pytest.raises(HTTPException) as exc:
            await call()
        assert exc.value.status_code == 409


async def test_directory_user_cannot_change_password_here_and_system_user_is_untouchable(world):
    ad_user = User(id=str(uuid4()), email=f"ad-{uuid4().hex[:6]}@corp.test", username="ad", role="viewer",
                   hashed_password="!directory-account", auth_source="ldap")
    system = User(id=str(uuid4()), email=f"sys-{uuid4().hex[:6]}@system.invalid", username="sys",
                  role="viewer", hashed_password="!system", auth_source="system", is_active=False)
    world.db.add_all([ad_user, system])
    await world.db.commit()

    with pytest.raises(HTTPException) as exc:
        await users_api.change_my_password(
            users_api.PasswordChange(current_password="whatever1", new_password="new-password-1"), world.db, ad_user
        )
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        await users_api.update_user(system.id, users_api.UserUpdate(is_active=True), world.db, world.admin)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        await users_api.delete_user(system.id, world.db, world.admin)
    assert exc.value.status_code == 403


async def test_directory_account_activation_and_admin_role_follow_ad(world):
    ad_user = User(id=str(uuid4()), email=f"ad-{uuid4().hex[:6]}@corp.test", username="ad", role="viewer",
                   hashed_password="!directory-account", auth_source="ldap")
    world.db.add(ad_user)
    await world.db.commit()

    # 다음 동기화가 되돌릴 변경(사용 중지, 관리자 지정)은 막는다
    for change in (users_api.UserUpdate(is_active=False), users_api.UserUpdate(role="admin")):
        with pytest.raises(HTTPException) as exc:
            await users_api.update_user(ad_user.id, change, world.db, world.admin)
        assert exc.value.status_code == 409
    # 동기화가 건드리지 않는 값(편집자 역할, 열람등급)은 바꿀 수 있다
    out = await users_api.update_user(
        ad_user.id, users_api.UserUpdate(role="editor", clearance_level="Confidential"), world.db, world.admin
    )
    assert (out.role, out.clearance_level) == ("editor", "Confidential")


# ------------------------------------------------------------ 권한 기준과 로컬 폴더
async def test_smb_connector_can_apply_collection_permissions_only(world):
    out = await api.create_connector(_create_body(world.col.id, acl_mode="collection_only"), world.db, world.admin)
    assert out["acl_mode"] == "collection_only"

    changed = await api.update_connector(out["id"], api.ConnectorUpdate(acl_mode="file_acl"), world.db, world.admin)
    assert changed["acl_mode"] == "file_acl"
    [row] = await _audits(world.db, "connector.update", out["id"])
    assert "acl_mode" in row.detail["fields"]


def _local_body(collection_id, **over):
    body = dict(kind="local", name="공용 폴더", base_path="영업", collection_id=collection_id)
    return api.ConnectorCreate(**{**body, **over})


@pytest.fixture
def local_root(tmp_path, monkeypatch):
    (tmp_path / "영업").mkdir()
    monkeypatch.setattr(api.settings, "connector_local_root", str(tmp_path))
    return tmp_path


async def test_local_folder_connector_needs_no_server_credentials_and_always_uses_collection_permissions(
        world, local_root):
    out = await api.create_connector(_local_body(world.col.id, acl_mode="file_acl"), world.db, world.admin)

    assert out["kind"] == "local" and out["acl_mode"] == "collection_only"
    connector = await world.db.get(SourceConnector, out["id"])
    assert connector.password_encrypted == "" and connector.host == ""

    with pytest.raises(HTTPException) as exc:
        await api.update_connector(out["id"], api.ConnectorUpdate(acl_mode="file_acl"), world.db, world.admin)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("folder", ["", "../", "없는폴더"])
async def test_local_folder_must_exist_inside_the_source_root(world, local_root, folder):
    with pytest.raises((HTTPException, ValidationError)) as exc:
        await api.create_connector(_local_body(world.col.id, base_path=folder), world.db, world.admin)
    if isinstance(exc.value, HTTPException):
        assert exc.value.status_code == 422


@pytest.mark.parametrize("missing", ["host", "share", "username", "password"])
async def test_smb_connector_still_requires_server_details(world, missing):
    with pytest.raises(ValidationError):
        _create_body(world.col.id, **{missing: ""})


async def test_connector_options_tell_the_screen_what_is_available(world, local_root, monkeypatch):
    monkeypatch.setattr(api.settings, "ldap_enabled", False)
    options = await api.connector_options(world.admin)
    assert options == {"directory_login": False, "local_root": str(local_root), "local_folders": ["영업"]}
