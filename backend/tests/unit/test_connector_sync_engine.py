"""v3 마일스톤 3 — SMB 커넥터 동기화 엔진.

원천 목록과 지난 동기화 상태를 비교해 신규, 내용 변경, 권한만 변경, 원천 삭제를 처리한다.
원천 권한을 표현할 수 없으면 문서를 만들지 않고(이미 있으면 지우고) 보류한다.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.v1.endpoints.documents import listing as listing_api
from app.api.v1.endpoints.documents import upload as upload_api
from app.db.models.document import Document
from app.db.models.document_acl import DocumentAclEntry
from app.db.models.source_connector import SourceConnector, SourceItem
from app.db.models.user import User
from app.db.models.user_group import UserGroup
from app.services.connectors import sync_engine
from app.services.connectors.smb_client import RemoteFile
from tests.unit.api_pg_helpers import db_session, make_collection, make_project, make_user  # noqa: F401
from tests.unit.test_connector_acl_mapping import _sd

pytestmark = pytest.mark.asyncio

DOM = "S-1-5-21-5-5-5"
READ, FULL = 0x1200A9, 0x1F01FF
SVC = f"{DOM}-1103"


def _sid():
    return f"{DOM}-{10000 + uuid4().int % 10**8}"


def acl(*entries):
    """(ace_type, sid) 목록으로 보안 설명자를 만든다. 관리자와 수집 계정은 항상 들어 있다."""
    return _sd([(0, 0, FULL, f"{DOM}-500"), (0, 0, READ, SVC)] + [(t, 0, READ, s) for t, s in entries])


class FakeSource:
    def __init__(self, files):
        self.files = dict(files)  # path -> (content, sd, mtime)
        self.broken_paths = set()
        self.broken_descriptors = set()
        self.listing_fails = False

    def list_files(self):
        if self.listing_fails:
            raise ConnectionError("share offline")
        for path, (content, _sd_bytes, mtime) in sorted(self.files.items()):
            yield RemoteFile(path=path, size=len(content), mtime=mtime)

    def read_file(self, path, max_bytes):
        if path in self.broken_paths:
            raise OSError("read failed")
        return self.files[path][0]

    def read_security_descriptor(self, path):
        if path in self.broken_descriptors:
            raise PermissionError("access denied")
        return self.files[path][1]

    def close(self):
        pass


@pytest.fixture
def externals(monkeypatch):
    storage, qdrant, summary = MagicMock(), MagicMock(), MagicMock()
    start = AsyncMock()
    access_sync = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.storage.storage_service", storage)
    monkeypatch.setattr("app.services.qdrant_service.qdrant_service", qdrant)
    monkeypatch.setattr("app.services.summary_index.delete_document_summary", summary)
    monkeypatch.setattr(listing_api, "release_original", AsyncMock())
    monkeypatch.setattr(upload_api, "_start_workflow_or_mark_failed", start)
    monkeypatch.setattr(sync_engine, "sync_document_access", access_sync)
    return SimpleNamespace(storage=storage, start=start, access_sync=access_sync)


@pytest.fixture
async def world(db_session):  # noqa: F811
    db = db_session
    admin = await make_user(db, "admin")
    project = await make_project(db, admin)
    col = await make_collection(db, admin, project)
    a_sid, s_sid = _sid(), _sid()
    alice = User(id=str(uuid4()), email=f"alice-{uuid4().hex[:6]}@corp.test", username="alice",
                 hashed_password="!", role="viewer", auth_source="ldap", external_id=a_sid)
    sales = UserGroup(id=str(uuid4()), name=f"sales-{uuid4().hex[:6]}", source="ldap", external_id=s_sid)
    service = User(id=str(uuid4()), email=f"connector-{uuid4().hex[:6]}@system.invalid", username="커넥터",
                   hashed_password="!", role="viewer", auth_source="system", is_active=False)
    db.add_all([alice, sales, service])
    await db.flush()
    connector = SourceConnector(
        id=str(uuid4()), name="공유", host="fs", share="docs", username="svc", password_encrypted="x",
        service_account_sid=SVC, collection_id=col.id, service_user_id=service.id, created_by=admin.id,
        level_rules=[{"prefix": "exec/", "level": "Confidential"}], max_new_per_run=50,
    )
    db.add(connector)
    await db.commit()
    source = FakeSource({
        "public/notice.pdf": (b"notice", acl((0, f"{DOM}-513")), 1.0),
        "sales/plan.pdf": (b"plan", acl((0, s_sid)), 1.0),
        "personal/alice.pdf": (b"alice", acl((0, a_sid)), 1.0),
        "exec/salary.pdf": (b"salary", acl((0, a_sid)), 1.0),
        "held/denied.pdf": (b"denied", acl((1, f"{DOM}-1109"), (0, s_sid)), 1.0),
        "held/unmapped.pdf": (b"unmapped", acl((0, "S-1-5-21-1-2-3-1001")), 1.0),
        "notes.txt": (b"plain text", acl((0, a_sid)), 1.0),
    })
    return SimpleNamespace(db=db, connector=connector, source=source, alice=alice, sales=sales,
                           service=service, a_sid=a_sid, s_sid=s_sid, col=col)


async def _sync(w):
    connector = await w.db.get(SourceConnector, w.connector.id)
    return await sync_engine.run_connector_sync(w.db, connector, w.source)


async def _items(w):
    rows = (await w.db.scalars(select(SourceItem).where(SourceItem.connector_id == w.connector.id))).all()
    return {i.path: i for i in rows}


async def _acl(db, document_id):
    rows = (await db.scalars(select(DocumentAclEntry).where(DocumentAclEntry.document_id == document_id))).all()
    return {(r.principal_type, str(r.principal_id)) for r in rows}


async def test_first_sync_creates_documents_with_source_permissions(world, externals):
    run = await _sync(world)

    assert run.status == "success"
    assert run.counts["added"] == 4 and run.counts["held"] == 2 and run.counts["skipped"] == 1
    items = await _items(world)
    assert "notes.txt" not in items  # 지원하지 않는 형식은 추적하지 않는다

    docs = {p: await world.db.get(Document, items[p].document_id) for p in
            ("public/notice.pdf", "sales/plan.pdf", "personal/alice.pdf", "exec/salary.pdf")}
    assert all(str(d.created_by) == str(world.service.id) for d in docs.values())
    assert await _acl(world.db, docs["public/notice.pdf"].id) == set()
    assert await _acl(world.db, docs["sales/plan.pdf"].id) == {("group", str(world.sales.id))}
    assert await _acl(world.db, docs["personal/alice.pdf"].id) == {("user", str(world.alice.id))}
    assert docs["exec/salary.pdf"].security_level == "Confidential"
    assert docs["sales/plan.pdf"].security_level is None
    assert externals.start.await_count == 4

    held = items["held/denied.pdf"]
    assert (held.state, held.hold_reason, held.document_id) == ("held", "deny_ace", None)
    # 관리자(-500)도 읽기 권한이 있지만 v3 사용자가 아니므로 함께 보고한다
    assert items["held/unmapped.pdf"].hold_detail == {"unmapped_sids": [f"{DOM}-500", "S-1-5-21-1-2-3-1001"]}


async def test_second_sync_without_changes_does_nothing(world, externals):
    await _sync(world)
    run = await _sync(world)
    assert run.counts.get("added", 0) == 0 and run.counts["unchanged"] == 4
    assert externals.start.await_count == 4


async def test_permission_only_change_updates_acl_without_reindexing(world, externals):
    await _sync(world)
    content, _old, mtime = world.source.files["sales/plan.pdf"]
    world.source.files["sales/plan.pdf"] = (content, acl((0, world.a_sid)), mtime)

    run = await _sync(world)

    doc_id = (await _items(world))["sales/plan.pdf"].document_id
    assert run.counts["acl_changed"] == 1
    assert await _acl(world.db, doc_id) == {("user", str(world.alice.id))}
    assert externals.start.await_count == 4  # 다시 처리하지 않는다
    externals.access_sync.assert_awaited()


async def test_content_change_becomes_a_new_version_and_keeps_the_old_one_until_indexed(world, externals):
    await _sync(world)
    old_id = (await _items(world))["sales/plan.pdf"].document_id
    world.source.files["sales/plan.pdf"] = (b"plan v2", acl((0, world.s_sid)), 2.0)

    run = await _sync(world)

    new_id = (await _items(world))["sales/plan.pdf"].document_id
    assert run.counts["content_changed"] == 1 and new_id != old_id
    old, new = await world.db.get(Document, old_id), await world.db.get(Document, new_id)
    # v3 마일스톤 7: 이전 버전은 새 버전이 처리를 마칠 때까지 현재 버전으로 남는다
    assert (old.lifecycle_state, new.lifecycle_state) == ("current", "pending")
    assert (new.lineage_id, new.version_number) == (old.lineage_id, 2)
    assert await _acl(world.db, new_id) == {("group", str(world.sales.id))}


async def test_file_removed_at_source_removes_every_version(world, externals):
    await _sync(world)
    old_id = (await _items(world))["sales/plan.pdf"].document_id
    world.source.files["sales/plan.pdf"] = (b"plan v2", acl((0, world.s_sid)), 2.0)
    await _sync(world)
    new_id = (await _items(world))["sales/plan.pdf"].document_id
    del world.source.files["sales/plan.pdf"]

    await _sync(world)

    assert await world.db.get(Document, old_id) is None and await world.db.get(Document, new_id) is None


async def test_touched_file_with_same_bytes_is_not_reprocessed(world, externals):
    await _sync(world)
    content, sd_bytes, _ = world.source.files["sales/plan.pdf"]
    world.source.files["sales/plan.pdf"] = (content, sd_bytes, 5.0)

    run = await _sync(world)
    assert run.counts.get("content_changed", 0) == 0 and externals.start.await_count == 4


async def test_file_removed_at_source_removes_the_document(world, externals):
    await _sync(world)
    doc_id = (await _items(world))["personal/alice.pdf"].document_id
    del world.source.files["personal/alice.pdf"]

    run = await _sync(world)

    assert run.counts["deleted"] == 1
    assert await world.db.get(Document, doc_id) is None
    assert "personal/alice.pdf" not in await _items(world)


async def test_file_that_becomes_unrepresentable_is_removed_and_held(world, externals):
    await _sync(world)
    doc_id = (await _items(world))["sales/plan.pdf"].document_id
    content, _old, mtime = world.source.files["sales/plan.pdf"]
    world.source.files["sales/plan.pdf"] = (content, acl((1, world.a_sid), (0, world.s_sid)), mtime)

    await _sync(world)

    item = (await _items(world))["sales/plan.pdf"]
    assert (item.state, item.document_id) == ("held", None)
    assert await world.db.get(Document, doc_id) is None


async def test_new_document_budget_defers_the_rest_to_the_next_run(world, externals):
    world.connector.max_new_per_run = 2
    await world.db.commit()

    first = await _sync(world)
    second = await _sync(world)

    assert (first.counts["added"], first.counts["deferred"]) == (2, 2)
    assert second.counts["added"] == 2


async def test_one_broken_file_does_not_stop_the_run(world, externals):
    world.source.broken_paths.add("sales/plan.pdf")
    run = await _sync(world)

    assert run.status == "partial" and run.counts["errors"] == 1 and run.counts["added"] == 3
    assert (await _items(world))["sales/plan.pdf"].state == "error"


async def test_listing_failure_fails_the_run_without_deleting_anything(world, externals):
    await _sync(world)
    world.source.listing_fails = True

    run = await _sync(world)

    assert run.status == "failed" and run.error_message
    assert len([i for i in (await _items(world)).values() if i.document_id]) == 4


# -- 리뷰에서 보강한 실패 경로 ------------------------------------------------------

async def test_unreadable_permissions_take_an_existing_document_down(world, externals):
    """이미 가져온 문서의 권한을 다시 읽지 못하면 옛 권한으로 열어 두지 않는다(fail-closed)."""
    await _sync(world)
    doc_id = (await _items(world))["sales/plan.pdf"].document_id
    world.source.broken_descriptors.add("sales/plan.pdf")

    run = await _sync(world)

    item = (await _items(world))["sales/plan.pdf"]
    assert (item.state, item.hold_reason, item.document_id) == ("held", "descriptor_unreadable", None)
    assert await world.db.get(Document, doc_id) is None
    assert run.counts["held"] == 3


async def test_narrowed_permissions_apply_even_when_content_cannot_be_read(world, externals):
    await _sync(world)
    doc_id = (await _items(world))["public/notice.pdf"].document_id
    world.source.files["public/notice.pdf"] = (b"notice v2", acl((0, world.a_sid)), 2.0)
    world.source.broken_paths.add("public/notice.pdf")

    run = await _sync(world)

    assert run.counts["errors"] == 1
    assert await _acl(world.db, doc_id) == {("user", str(world.alice.id))}
    assert (await _items(world))["public/notice.pdf"].state == "error"


async def test_empty_listing_does_not_delete_imported_documents(world, externals):
    await _sync(world)
    world.source.files.clear()

    run = await _sync(world)

    assert run.status == "failed" and "하나도" in run.error_message
    assert len([i for i in (await _items(world)).values() if i.document_id]) == 4


async def test_failed_search_copy_update_is_an_error_for_that_file_only(world, externals):
    await _sync(world)
    for path in ("sales/plan.pdf", "personal/alice.pdf"):
        content, _old, mtime = world.source.files[path]
        world.source.files[path] = (content, acl((0, f"{DOM}-513")), mtime)
    externals.access_sync.side_effect = [RuntimeError("qdrant down"), []]

    run = await _sync(world)

    assert run.status == "partial"
    assert (run.counts["errors"], run.counts["acl_changed"]) == (1, 1)
    items = await _items(world)
    # 실패한 파일은 지난 권한 해시를 그대로 둬 다음 실행이 다시 맞춘다
    failed = items["personal/alice.pdf"]
    assert failed.state == "error" and failed.sd_hash != sync_engine.descriptor_hash(acl((0, f"{DOM}-513")))


async def test_document_and_source_link_are_committed_together(world, externals):
    """처리 시작이 실패해도 문서는 원천 항목에 묶여 있어 다음 실행이 중복 문서를 만들지 않는다."""
    externals.start.side_effect = RuntimeError("broker down")

    run = await _sync(world)

    assert run.status == "failed"
    linked = [i for i in (await _items(world)).values() if i.document_id]
    assert len(linked) == 1
    owned = (await world.db.scalars(select(Document.id).where(Document.created_by == world.service.id))).all()
    assert {str(d) for d in owned} == {str(linked[0].document_id)}


async def test_interrupted_run_is_closed_by_the_next_run(world, externals):
    from datetime import datetime

    from app.db.models.source_connector import ConnectorRun

    stale = ConnectorRun(id=str(uuid4()), connector_id=world.connector.id, status="running", counts={},
                         started_at=datetime(2026, 1, 1))
    world.db.add(stale)
    await world.db.commit()
    stale_id = stale.id

    await _sync(world)

    status = await world.db.scalar(select(ConnectorRun.status).where(ConnectorRun.id == stale_id))
    assert status == "failed"
