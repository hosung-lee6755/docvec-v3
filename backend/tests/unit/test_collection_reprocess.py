"""컬렉션 일괄 재처리 — 권한과 중복 디스패치 방지(실제 DB)."""
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.endpoints import collections as collections_api
from app.db.models.collection import Collection
from app.db.models.collection_member import CollectionMember
from app.db.models.document import Document
from app.db.models.user import User
from tests.unit.test_documents_storage_release import OWNER_ID, _doc, db_session  # noqa: F401


@pytest.fixture
def dispatched(monkeypatch):
    calls: list[str] = []

    class FakeTask:
        @staticmethod
        def delay(document_id):
            calls.append(document_id)

    monkeypatch.setattr("app.pipeline.tasks.process.continue_processing", FakeTask)
    return calls


async def _user(db_session, role: str = "viewer") -> User:
    user = User(
        id=str(uuid4()), email=f"{uuid4()}@example.com", username="u",
        hashed_password="!", role=role, is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _collection(db_session) -> str:
    collection = Collection(
        id=uuid4(), name="c", qdrant_collection_name=f"q-{uuid4()}", embedding_model="m",
        chunk_max_tokens=500, chunk_min_tokens=50, chunk_overlap_tokens=0,
        chunk_strategy="fixed", created_by=OWNER_ID,
    )
    db_session.add(collection)
    await db_session.flush()
    return collection.id


async def _statuses(db_session, collection_id):
    rows = await db_session.execute(
        select(Document.status).where(Document.collection_id == collection_id)
    )
    return sorted(r[0] for r in rows)


@pytest.mark.asyncio
async def test_owner_reprocess_queues_only_documents_with_text(db_session, dispatched):
    collection_id = await _collection(db_session)
    db_session.add_all([
        _doc(f"{uuid4()}/a.pdf", collection_id=collection_id, status="INDEXED", parsed_text="본문"),
        _doc(f"{uuid4()}/b.pdf", collection_id=collection_id, status="FAILED", parsed_text=None),
    ])
    await db_session.flush()
    owner = await db_session.get(User, OWNER_ID)

    result = await collections_api.reprocess_collection(collection_id, db_session, owner)

    assert result == {"queued": 1, "skipped": 1}
    assert len(dispatched) == 1
    assert await _statuses(db_session, collection_id) == ["CHUNKING", "FAILED"]


@pytest.mark.asyncio
async def test_editor_member_may_reprocess_but_viewer_may_not(db_session, dispatched):
    collection_id = await _collection(db_session)
    db_session.add(_doc(f"{uuid4()}/c.pdf", collection_id=collection_id, status="INDEXED", parsed_text="본문"))
    editor, viewer = await _user(db_session), await _user(db_session)
    db_session.add_all([
        CollectionMember(collection_id=collection_id, user_id=editor.id, role="editor", invited_by=OWNER_ID),
        CollectionMember(collection_id=collection_id, user_id=viewer.id, role="viewer", invited_by=OWNER_ID),
    ])
    await db_session.flush()

    with pytest.raises(HTTPException) as denied:
        await collections_api.reprocess_collection(collection_id, db_session, viewer)
    assert denied.value.status_code == 403
    assert dispatched == []

    result = await collections_api.reprocess_collection(collection_id, db_session, editor)
    assert result["queued"] == 1


@pytest.mark.asyncio
async def test_documents_already_claimed_are_not_dispatched_twice(db_session, dispatched):
    collection_id = await _collection(db_session)
    db_session.add(_doc(f"{uuid4()}/d.pdf", collection_id=collection_id, status="INDEXED", parsed_text="본문"))
    await db_session.flush()
    owner = await db_session.get(User, OWNER_ID)

    first = await collections_api.reprocess_collection(collection_id, db_session, owner)
    second = await collections_api.reprocess_collection(collection_id, db_session, owner)

    assert first["queued"] == 1
    assert second["queued"] == 0  # 이미 CHUNKING이라 대상이 아니다
    assert len(dispatched) == 1



# ---- 처음부터 재처리(2026-11-13) ----
# 예전 일괄 재처리는 고정 파이프라인으로 청크와 임베딩만 다시 만들어 추출 개선이 반영되지 않았다.
# "처음부터 재처리"는 문서마다 워크플로우 최신 게시 버전으로 추출부터 다시 돈다.


@pytest.fixture
def started(monkeypatch):
    from app.services import reprocess_service

    calls: list[tuple[str, str | None]] = []

    async def fake_reconcile(db, doc):
        return None

    async def fake_start(db, doc, reason, timeout_overrides=None):
        if doc.minio_key.endswith("legacy.pdf"):
            raise reprocess_service.ReprocessError("이 문서는 아직 워크플로우로 처리된 적이 없어 이 기능을 사용할 수 없습니다.")
        calls.append((str(doc.id), reason))
        return None

    monkeypatch.setattr(reprocess_service, "reconcile_stuck_run", fake_reconcile)
    monkeypatch.setattr(reprocess_service, "start_reprocess_on_latest_version", fake_start)
    return calls


@pytest.mark.asyncio
async def test_reprocess_from_start_runs_every_workflow_document_and_reports_skips(db_session, started):
    collection_id = await _collection(db_session)
    with_run = _doc(f"{uuid4()}/a.pdf", collection_id=collection_id, status="INDEXED", parsed_text="본문")
    legacy = _doc(f"{uuid4()}/legacy.pdf", collection_id=collection_id, status="INDEXED", parsed_text="본문")
    db_session.add_all([with_run, legacy])
    await db_session.flush()
    owner = await db_session.get(User, OWNER_ID)

    result = await collections_api.reprocess_collection_from_start(collection_id, db_session, owner)

    assert result["queued"] == 1
    assert result["skipped"] == 1
    assert result["skipped_reasons"] == {
        "이 문서는 아직 워크플로우로 처리된 적이 없어 이 기능을 사용할 수 없습니다.": 1,
    }
    assert started == [(str(with_run.id), "컬렉션 처음부터 재처리")]


@pytest.mark.asyncio
async def test_viewer_may_not_reprocess_from_start(db_session, started):
    collection_id = await _collection(db_session)
    viewer = await _user(db_session)
    db_session.add(CollectionMember(collection_id=collection_id, user_id=viewer.id, role="viewer", invited_by=OWNER_ID))
    await db_session.flush()

    with pytest.raises(HTTPException) as denied:
        await collections_api.reprocess_collection_from_start(collection_id, db_session, viewer)

    assert denied.value.status_code == 403
    assert started == []
