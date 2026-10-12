"""컬렉션 엔드포인트 테스트 — 실제 Postgres(SAVEPOINT 롤백), Celery/Qdrant/MinIO는 가짜.

대상: app/api/v1/endpoints/collections.py (생성·목록·수정·재임베딩 트리거·삭제 연쇄·재처리·내보내기·멤버).
"""
import json
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api.v1.endpoints import collections as api
from app.db.models.chat_conversation import ChatConversation
from app.db.models.collection import Collection
from app.db.models.collection_member import CollectionMember
from app.db.models.document import Document
from app.db.models.golden_query import GoldenQuery
from app.db.models.workflow_run import WorkflowRun
from tests.unit.api_pg_helpers import (  # noqa: F401
    add_member,
    db_session,
    make_collection,
    make_document,
    make_project,
    make_user,
    make_version,
    make_workflow,
)

OTHER_MODEL = "multilingual-e5-large"


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
    pmember = await make_user(db_session, "viewer", "pmember")
    stranger = await make_user(db_session, "viewer", "stranger")
    project = await make_project(db_session, owner, "P1")
    await add_member(db_session, project, pmember, "viewer", owner)
    collection = await make_collection(db_session, owner, project, name="main")
    return dict(db=db_session, owner=owner, pmember=pmember, stranger=stranger,
                project=project, collection=collection)


@pytest.fixture
def qdrant(monkeypatch):
    client, storage = MagicMock(), MagicMock()
    monkeypatch.setattr("app.services.qdrant_service.qdrant_service", client)
    monkeypatch.setattr("app.services.storage.storage_service", storage)
    return MagicMock(qdrant=client, storage=storage)


# ---------- 스키마 / 임베딩 모델 목록 ----------

def test_collection_create_rejects_unknown_or_wrong_dimension_model():
    with pytest.raises(ValidationError):
        api.CollectionCreate(name="x", embedding_model="no-such-model")
    with pytest.raises(ValidationError):
        api.CollectionCreate(name="x", embedding_model="ko-sroberta-multitask")  # 768차원


def test_collection_update_validates_model_only_when_given():
    assert api.CollectionUpdate().embedding_model is None
    with pytest.raises(ValidationError):
        api.CollectionUpdate(embedding_model="bogus")


@pytest.mark.asyncio
async def test_list_embedding_models_only_selectable_dimension(monkeypatch):
    monkeypatch.setattr(api.settings, "openai_api_key", None, raising=False)
    result = await api.list_embedding_models(current_user=None)
    keys = {i["key"] for i in result["items"]}
    assert {"bge-m3", OTHER_MODEL} <= keys
    assert "ko-sroberta-multitask" not in keys and "openai" not in keys
    assert {i["dimension"] for i in result["items"]} == {api.settings.default_embedding_dimension}


# ---------- create ----------

@pytest.mark.asyncio
async def test_create_collection_in_project_derives_qdrant_name(world):
    data = api.CollectionCreate(name="My Docs", project_id=U(world["project"].id))
    created = await api.create_collection(data, world["db"], world["owner"])
    assert created.qdrant_collection_name == "my_docs"
    assert str(created.project_id) == str(world["project"].id)
    assert created.chunk_strategy == "size"


@pytest.mark.asyncio
async def test_create_collection_requires_editor_on_project(world):
    await _expect(403, api.create_collection(
        api.CollectionCreate(name="n", project_id=U(world["project"].id)),
        world["db"], world["pmember"]))


@pytest.mark.asyncio
async def test_create_collection_validates_default_workflow_kinds(world):
    db, owner = world["db"], world["owner"]
    analysis = await make_workflow(db, owner, world["project"], kind="ANALYSIS")
    preprocess = await make_workflow(db, owner, world["project"], kind="PREPROCESS")

    await _expect(400, api.create_collection(
        api.CollectionCreate(name="a", default_workflow_id=U(analysis.id)), db, owner))
    await _expect(400, api.create_collection(
        api.CollectionCreate(name="b", default_workflow_id=uuid4()), db, owner))
    await _expect(400, api.create_collection(
        api.CollectionCreate(name="c", default_analysis_workflow_id=U(preprocess.id)), db, owner))

    ok = await api.create_collection(api.CollectionCreate(
        name="d", default_workflow_id=U(preprocess.id), default_workflow_version=2,
        default_analysis_workflow_id=U(analysis.id), default_analysis_workflow_version=3), db, owner)
    assert str(ok.default_workflow_id) == str(preprocess.id) and ok.default_workflow_version == 2
    assert str(ok.default_analysis_workflow_id) == str(analysis.id)
    assert ok.default_analysis_workflow_version == 3


@pytest.mark.asyncio
async def test_create_collection_duplicate_name_returns_409(world):
    db, owner = world["db"], world["owner"]
    await api.create_collection(api.CollectionCreate(name="dup"), db, owner)
    await _expect(409, api.create_collection(api.CollectionCreate(name="dup"), db, owner))


# ---------- list / get / vector-stats ----------

@pytest.mark.asyncio
async def test_list_collections_roles_counts_and_project_names(world):
    db = world["db"]
    await make_document(db, world["owner"], world["collection"])
    await make_document(db, world["owner"], world["collection"])
    restricted = await make_collection(db, world["owner"], world["project"], name="secret",
                                       restrict_to_members=True)
    standalone = await make_collection(db, world["owner"], None, name="standalone")

    owner_items = {i["name"]: i for i in (await api.list_collections(None, db, world["owner"]))["items"]}
    pmember_items = {i["name"]: i for i in (await api.list_collections(None, db, world["pmember"]))["items"]}

    assert set(owner_items) == {"main", "secret", "standalone"}
    assert owner_items["main"]["document_count"] == 2
    assert owner_items["main"]["role"] == "owner" and owner_items["main"]["is_owner"] is True
    assert owner_items["main"]["project_name"] == "P1"
    assert owner_items["standalone"]["project_name"] is None
    # 프로젝트 멤버는 restrict_to_members 컬렉션을 보지 못하고, 나머지는 프로젝트 역할을 상속
    assert set(pmember_items) == {"main"}
    assert pmember_items["main"]["role"] == "viewer" and pmember_items["main"]["is_owner"] is False
    assert str(restricted.id) not in {str(i["id"]) for i in pmember_items.values()}
    assert str(standalone.id) not in {str(i["id"]) for i in pmember_items.values()}


@pytest.mark.asyncio
async def test_list_collections_explicit_member_of_restricted_collection_and_project_filter(world):
    db = world["db"]
    restricted = await make_collection(db, world["owner"], world["project"], name="secret",
                                       restrict_to_members=True)
    db.add(CollectionMember(collection_id=str(restricted.id), user_id=str(world["pmember"].id),
                            role="editor", invited_by=str(world["owner"].id)))
    other_project = await make_project(db, world["owner"], "P2")
    await make_collection(db, world["owner"], other_project, name="in-p2")
    await db.flush()

    items = {i["name"]: i for i in (await api.list_collections(None, db, world["pmember"]))["items"]}
    assert items["secret"]["role"] == "editor"

    filtered = (await api.list_collections(U(other_project.id), db, world["owner"]))["items"]
    assert [i["name"] for i in filtered] == ["in-p2"]
    assert (await api.list_collections(None, db, world["stranger"])) == {"items": []}


@pytest.mark.asyncio
async def test_list_collections_project_owner_without_membership_gets_editor_role(world):
    db = world["db"]
    other = await make_user(db, "viewer", "colowner")
    await add_member(db, world["project"], other, "editor", world["owner"])
    foreign_col = await make_collection(db, other, world["project"], name="by-other")

    items = {i["name"]: i for i in (await api.list_collections(None, db, world["owner"]))["items"]}

    assert items["by-other"]["role"] == "editor" and items["by-other"]["is_owner"] is False
    assert str(foreign_col.id) in {str(i["id"]) for i in items.values()}


@pytest.mark.asyncio
async def test_get_collection_access_matrix(world):
    cid = U(world["collection"].id)
    got = await api.get_collection(cid, world["db"], world["pmember"])
    assert str(got.id) == str(cid)
    await _expect(403, api.get_collection(cid, world["db"], world["stranger"]))
    await _expect(404, api.get_collection(uuid4(), world["db"], world["owner"]))


@pytest.mark.asyncio
async def test_vector_stats_counts_documents_and_live_vectors(world, qdrant):
    db = world["db"]
    await make_document(db, world["owner"], world["collection"], status="INDEXED")
    await make_document(db, world["owner"], world["collection"], status="FAILED")
    qdrant.qdrant.count_by_collection.return_value = 7

    stats = await api.get_collection_vector_stats(U(world["collection"].id), db, world["owner"])

    assert stats["total_documents"] == 2 and stats["indexed_documents"] == 1
    assert stats["total_vectors"] == 7
    assert stats["dimension"] == 1024 and stats["embedding_model"] == "bge-m3"


@pytest.mark.asyncio
async def test_vector_stats_unknown_model_falls_back_to_key(world, qdrant):
    world["collection"].embedding_model = "legacy-model"
    await world["db"].flush()
    qdrant.qdrant.count_by_collection.return_value = 0
    stats = await api.get_collection_vector_stats(U(world["collection"].id), world["db"], world["owner"])
    assert stats["embedding_model_label"] == "legacy-model" and stats["dimension"] is None


# ---------- update ----------

@pytest.mark.asyncio
async def test_update_collection_simple_fields(world):
    result = await api.update_collection(
        U(world["collection"].id),
        api.CollectionUpdate(name="renamed", description="d", restrict_to_members=True,
                             chunk_max_tokens=900, chunk_min_tokens=50, chunk_overlap_tokens=10,
                             chunk_strategy="semantic"),
        world["db"], world["owner"])
    assert (result.name, result.description, result.restrict_to_members) == ("renamed", "d", True)
    assert (result.chunk_max_tokens, result.chunk_min_tokens, result.chunk_overlap_tokens) == (900, 50, 10)
    assert result.chunk_strategy == "semantic"


@pytest.mark.asyncio
async def test_update_collection_requires_editor(world):
    await _expect(403, api.update_collection(
        U(world["collection"].id), api.CollectionUpdate(name="x"), world["db"], world["pmember"]))


@pytest.mark.asyncio
async def test_update_collection_moves_to_project_after_access_check(world):
    db = world["db"]
    foreign = await make_project(db, world["stranger"], "foreign")
    await _expect(403, api.update_collection(
        U(world["collection"].id), api.CollectionUpdate(project_id=U(foreign.id)), db, world["owner"]))

    target = await make_project(db, world["owner"], "P2")
    moved = await api.update_collection(
        U(world["collection"].id), api.CollectionUpdate(project_id=U(target.id)), db, world["owner"])
    assert str(moved.project_id) == str(target.id)


@pytest.mark.asyncio
async def test_update_collection_model_change_without_documents_resets_reembed_state(world):
    world["collection"].reembed_status = "DONE"
    await world["db"].flush()
    with patch("app.pipeline.tasks.reembed.reembed_collection.delay") as delay:
        result = await api.update_collection(
            U(world["collection"].id), api.CollectionUpdate(embedding_model=OTHER_MODEL),
            world["db"], world["owner"])
    assert result.embedding_model == OTHER_MODEL
    assert result.reembed_status is None and result.reembed_progress is None
    delay.assert_not_called()


@pytest.mark.asyncio
async def test_update_collection_model_change_with_documents_queues_reembed(world):
    await make_document(world["db"], world["owner"], world["collection"])
    await make_document(world["db"], world["owner"], world["collection"])
    with patch("app.pipeline.tasks.reembed.reembed_collection.delay") as delay:
        result = await api.update_collection(
            U(world["collection"].id), api.CollectionUpdate(embedding_model=OTHER_MODEL),
            world["db"], world["owner"])
    assert result.reembed_status == "PENDING" and result.reembed_progress == "0/2"
    delay.assert_called_once_with(str(U(world["collection"].id)), OTHER_MODEL)


@pytest.mark.asyncio
async def test_update_collection_model_change_rejected_while_reembed_running(world):
    world["collection"].reembed_status = "RUNNING"
    await world["db"].flush()
    await _expect(409, api.update_collection(
        U(world["collection"].id), api.CollectionUpdate(embedding_model=OTHER_MODEL),
        world["db"], world["owner"]))


@pytest.mark.asyncio
async def test_update_collection_same_model_is_noop(world):
    with patch("app.pipeline.tasks.reembed.reembed_collection.delay") as delay:
        result = await api.update_collection(
            U(world["collection"].id), api.CollectionUpdate(embedding_model="bge-m3"),
            world["db"], world["owner"])
    assert result.embedding_model == "bge-m3"
    delay.assert_not_called()


@pytest.mark.asyncio
async def test_update_collection_sets_validates_and_clears_default_workflows(world):
    db, owner, cid = world["db"], world["owner"], U(world["collection"].id)
    pre = await make_workflow(db, owner, world["project"], kind="PREPROCESS")
    ana = await make_workflow(db, owner, world["project"], kind="ANALYSIS")

    await _expect(400, api.update_collection(cid, api.CollectionUpdate(default_workflow_id=U(ana.id)), db, owner))
    await _expect(400, api.update_collection(
        cid, api.CollectionUpdate(default_analysis_workflow_id=U(pre.id)), db, owner))

    result = await api.update_collection(cid, api.CollectionUpdate(
        default_workflow_id=U(pre.id), default_workflow_version=4,
        default_analysis_workflow_id=U(ana.id), default_analysis_workflow_version=5), db, owner)
    assert str(result.default_workflow_id) == str(pre.id) and result.default_workflow_version == 4
    assert str(result.default_analysis_workflow_id) == str(ana.id)

    cleared = await api.update_collection(cid, api.CollectionUpdate(
        clear_default_workflow=True, clear_default_analysis_workflow=True), db, owner)
    assert cleared.default_workflow_id is None and cleared.default_workflow_version is None
    assert cleared.default_analysis_workflow_id is None and cleared.default_analysis_workflow_version is None


# ---------- delete / cascade ----------

@pytest.mark.asyncio
async def test_delete_collection_cascades_documents_runs_chats_goldens_members(world, qdrant):
    db, owner, col = world["db"], world["owner"], world["collection"]
    doc = await make_document(db, owner, col)
    wf = await make_workflow(db, owner, world["project"])
    version = await make_version(db, wf, owner)
    db.add(WorkflowRun(version_id=str(version.id), document_id=str(doc.id), status="COMPLETED"))
    db.add(WorkflowRun(version_id=str(version.id), collection_id=str(col.id), status="COMPLETED"))
    db.add(ChatConversation(id=str(uuid4()), user_id=str(owner.id), collection_id=str(col.id),
                            model_key="m", title="t"))
    db.add(GoldenQuery(collection_id=str(col.id), query="q", expected_document_ids=[], created_by=str(owner.id)))
    db.add(CollectionMember(collection_id=str(col.id), user_id=str(world["pmember"].id),
                            role="viewer", invited_by=str(owner.id)))
    await db.flush()

    result = await api.delete_collection(U(col.id), db, owner)

    assert result == {"message": "Collection deleted"}
    assert await _count(db, Collection, Collection.id == col.id) == 0
    assert await _count(db, Document, Document.id == doc.id) == 0
    assert await _count(db, WorkflowRun, WorkflowRun.version_id == version.id) == 0
    assert await _count(db, ChatConversation, ChatConversation.collection_id == col.id) == 0
    assert await _count(db, GoldenQuery, GoldenQuery.collection_id == col.id) == 0
    assert await _count(db, CollectionMember, CollectionMember.collection_id == col.id) == 0
    qdrant.qdrant.delete_by_document.assert_called_once()
    qdrant.storage.delete_file.assert_called_once()


@pytest.mark.asyncio
async def test_delete_collection_permissions(world, qdrant):
    db = world["db"]
    admin = await make_user(db, "admin", "root")
    cid = U(world["collection"].id)
    await _expect(404, api.delete_collection(uuid4(), db, world["owner"]))
    await _expect(403, api.delete_collection(cid, db, world["pmember"]))
    assert await api.delete_collection(cid, db, admin) == {"message": "Collection deleted"}


# ---------- reprocess ----------

@pytest.mark.asyncio
async def test_reprocess_claims_eligible_documents_and_skips_the_rest(world):
    db = world["db"]
    ok = await make_document(db, world["owner"], world["collection"], status="INDEXED", parsed_text="t")
    await make_document(db, world["owner"], world["collection"], status="FAILED", parsed_text=None)
    await make_document(db, world["owner"], world["collection"], status="CHUNKING", parsed_text="t")

    with patch("app.pipeline.tasks.process.continue_processing.delay") as delay:
        result = await api.reprocess_collection(U(world["collection"].id), db, world["owner"])

    assert result == {"queued": 1, "skipped": 1}
    delay.assert_called_once_with(str(ok.id))
    status = await db.scalar(select(Document.status).where(Document.id == ok.id))
    assert status == "CHUNKING"


@pytest.mark.asyncio
async def test_reprocess_requires_editor(world):
    await _expect(403, api.reprocess_collection(U(world["collection"].id), world["db"], world["pmember"]))


# ---------- export ----------

@pytest.mark.asyncio
async def test_export_collection_returns_sorted_chunks_as_attachment(world, qdrant):
    doc = await make_document(world["db"], world["owner"], world["collection"],
                              original_filename="한글.txt", tags=["a"], summary="요약")
    qdrant.qdrant.scroll_by_document.return_value = [
        {"payload": {"chunk_index": 1, "text": "둘째", "page_number": 2, "disabled": True}},
        {"payload": {"chunk_index": 0, "text": "첫째"}},
    ]

    response = await api.export_collection(U(world["collection"].id), world["db"], world["pmember"])

    payload = json.loads(response.body)
    assert response.headers["content-disposition"].endswith('-export.json"')
    assert "한글.txt" in response.body.decode()  # ensure_ascii=False
    exported = payload["documents"][0]
    assert exported["id"] == str(doc.id) and exported["tags"] == ["a"] and exported["summary"] == "요약"
    assert [c["text"] for c in exported["chunks"]] == ["첫째", "둘째"]
    assert exported["chunks"][0]["disabled"] is False and exported["chunks"][1]["disabled"] is True
    assert payload["collection"]["name"] == "main"


@pytest.mark.asyncio
async def test_export_collection_404_and_403(world, qdrant):
    await _expect(404, api.export_collection(uuid4(), world["db"], world["owner"]))
    await _expect(403, api.export_collection(U(world["collection"].id), world["db"], world["stranger"]))


# ---------- members ----------

@pytest.mark.asyncio
async def test_invite_member_adds_then_updates_role(world):
    db = world["db"]
    cid = U(world["collection"].id)
    invitee = await make_user(db, "viewer", "invitee")

    first = await api.invite_member(cid, api.MemberInvite(email=invitee.email), db, world["owner"])
    second = await api.invite_member(cid, api.MemberInvite(email=invitee.email, role="editor"), db, world["owner"])

    assert first["role"] == "viewer" and second["role"] == "editor"
    rows = (await db.scalars(select(CollectionMember).where(
        CollectionMember.collection_id == world["collection"].id))).all()
    assert [r.role for r in rows] == ["editor"]


@pytest.mark.asyncio
async def test_invite_member_rejections(world):
    db, cid = world["db"], U(world["collection"].id)
    await _expect(404, api.invite_member(uuid4(), api.MemberInvite(email="a@b.c"), db, world["owner"]))
    await _expect(403, api.invite_member(cid, api.MemberInvite(email=world["stranger"].email), db, world["pmember"]))
    await _expect(404, api.invite_member(cid, api.MemberInvite(email="nobody@example.com"), db, world["owner"]))
    await _expect(400, api.invite_member(cid, api.MemberInvite(email=world["owner"].email), db, world["owner"]))


@pytest.mark.asyncio
async def test_list_members_owner_first_then_members(world):
    db = world["db"]
    invitee = await make_user(db, "viewer", "invitee")
    await api.invite_member(U(world["collection"].id), api.MemberInvite(email=invitee.email), db, world["owner"])

    result = await api.list_members(U(world["collection"].id), db, world["owner"])

    assert [(m["username"], m["role"]) for m in result["items"]] == [("owner", "owner"), ("invitee", "viewer")]
    await _expect(403, api.list_members(U(world["collection"].id), db, world["stranger"]))


@pytest.mark.asyncio
async def test_remove_member_deletes_and_guards_owner(world):
    db, cid = world["db"], U(world["collection"].id)
    invitee = await make_user(db, "viewer", "invitee")
    await api.invite_member(cid, api.MemberInvite(email=invitee.email), db, world["owner"])

    assert await api.remove_member(cid, U(invitee.id), db, world["owner"]) == {"message": "멤버가 제거되었습니다"}
    assert await _count(db, CollectionMember, CollectionMember.collection_id == world["collection"].id) == 0

    await _expect(400, api.remove_member(cid, U(world["owner"].id), db, world["owner"]))
    await _expect(403, api.remove_member(cid, U(invitee.id), db, world["pmember"]))
    await _expect(404, api.remove_member(uuid4(), U(invitee.id), db, world["owner"]))
