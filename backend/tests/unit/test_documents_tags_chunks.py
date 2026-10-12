"""태그 동기화(Postgres 정본 → Qdrant)와 청크 PATCH 입력 검증 회귀 테스트 — 실제 DB.

- 색인 전 문서(컬렉션 없음)의 태그 저장은 Qdrant 오류로 500이 되지 않는다.
- 색인된 문서에서 Qdrant 동기화가 실패하면 저장은 유지하고 502로 알린다.
- 태그는 공백 제거 + 중복 제거.
- 청크 PATCH는 잘못된 요청에서 Qdrant를 호출하지 않는다.
"""
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.endpoints import documents as documents_api
from app.api.v1.endpoints.documents import chunks as chunks_api
from app.db.models.document import Document
from app.db.models.user import User
from app.schemas.document import ChunkUpdateRequest, DocumentTagsUpdateRequest
from tests.unit.test_documents_storage_release import OWNER_ID, _doc, db_session  # noqa: F401


class FailingQdrant:
    def __init__(self) -> None:
        self.calls = 0

    def set_payload_by_document(self, *args, **kwargs):
        self.calls += 1
        raise RuntimeError("Collection `documents` doesn't exist!")

    def get_point(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("잘못된 요청은 Qdrant를 호출하면 안 된다")


class RecordingQdrant:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def set_payload_by_document(self, collection, document_id, payload):
        self.payloads.append(payload)


@pytest.fixture
def failing_qdrant(monkeypatch):
    fake = FailingQdrant()
    monkeypatch.setattr("app.services.qdrant_service.qdrant_service", fake)
    return fake


async def _owner(db_session) -> User:
    return await db_session.get(User, OWNER_ID)


async def _tags_in_db(db_session, doc_id):
    return await db_session.scalar(select(Document.tags).where(Document.id == doc_id))


@pytest.mark.asyncio
async def test_tagging_unindexed_document_survives_qdrant_failure(db_session, failing_qdrant):
    doc = _doc(f"{uuid4()}/a.pdf", status="PARSING")
    db_session.add(doc)
    await db_session.flush()

    result = await documents_api.update_document_tags(
        doc.id, DocumentTagsUpdateRequest(tags=[" 계약 ", "계약", "", "보안"]), db_session, await _owner(db_session)
    )

    assert result == {"tags": ["계약", "보안"]}
    assert await _tags_in_db(db_session, doc.id) == ["계약", "보안"]


@pytest.mark.asyncio
async def test_tagging_indexed_document_reports_502_but_keeps_saved_tags(db_session, failing_qdrant):
    doc = _doc(f"{uuid4()}/b.pdf", status="INDEXED")
    db_session.add(doc)
    await db_session.flush()

    with pytest.raises(HTTPException) as caught:
        await documents_api.update_document_tags(
            doc.id, DocumentTagsUpdateRequest(tags=["계약"]), db_session, await _owner(db_session)
        )

    assert caught.value.status_code == 502
    assert await _tags_in_db(db_session, doc.id) == ["계약"]


@pytest.mark.asyncio
async def test_tags_are_pushed_to_index_for_indexed_document(db_session, monkeypatch):
    recorder = RecordingQdrant()
    monkeypatch.setattr("app.services.qdrant_service.qdrant_service", recorder)
    doc = _doc(f"{uuid4()}/c.pdf", status="INDEXED")
    db_session.add(doc)
    await db_session.flush()

    await documents_api.update_document_tags(
        doc.id, DocumentTagsUpdateRequest(tags=["a", "a", "b"]), db_session, await _owner(db_session)
    )

    assert recorder.payloads == [{"tags": ["a", "b"]}]


def test_tag_longer_than_100_chars_is_rejected_by_schema():
    with pytest.raises(ValueError):
        DocumentTagsUpdateRequest(tags=["x" * 101])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body,status",
    [
        (ChunkUpdateRequest(), 422),
        (ChunkUpdateRequest(text="내용", disabled=True), 400),
        (ChunkUpdateRequest(text="   "), 422),
    ],
)
async def test_chunk_patch_rejects_bad_requests_before_touching_qdrant(db_session, failing_qdrant, body, status):
    doc = _doc(f"{uuid4()}/d.pdf")
    db_session.add(doc)
    await db_session.flush()

    with pytest.raises(HTTPException) as caught:
        await documents_api.update_document_chunk(doc.id, str(uuid4()), body, db_session, await _owner(db_session))

    assert caught.value.status_code == status
    assert failing_qdrant.calls == 0


# ---- 상태 선점(동시 클릭/요청 중복 디스패치 방지) --------------------------------------------


@pytest.fixture
def dispatched(monkeypatch):
    calls: list[tuple] = []

    class FakeTask:
        @staticmethod
        def delay(*args, **kwargs):
            calls.append((args, kwargs))

    monkeypatch.setattr("app.pipeline.tasks.process.continue_processing", FakeTask)
    return calls


@pytest.mark.asyncio
async def test_proceed_dispatches_once_even_if_called_twice(db_session, dispatched):
    from app.schemas.document import DocumentProceedRequest

    doc = _doc(f"{uuid4()}/p.pdf", status="REVIEW_PENDING", parsed_text="원문")
    db_session.add(doc)
    await db_session.flush()
    doc_id = doc.id
    owner = await _owner(db_session)

    await documents_api.proceed_document(doc_id, DocumentProceedRequest(edited_text="수정본"), db_session, owner)
    with pytest.raises(HTTPException) as second:
        await documents_api.proceed_document(doc_id, DocumentProceedRequest(), db_session, owner)

    assert second.value.status_code == 409
    assert len(dispatched) == 1
    row = (await db_session.execute(select(Document.status, Document.parsed_text).where(Document.id == doc_id))).one()
    assert tuple(row) == ("CHUNKING", "수정본")


@pytest.mark.asyncio
async def test_retry_starts_workflow_once_and_second_retry_conflicts(db_session, monkeypatch):
    started: list[str] = []

    async def fake_start(db, document, version_id, skip_review):
        started.append(str(document.id))

    monkeypatch.setattr(chunks_api, "_start_workflow_or_mark_failed", fake_start)
    doc = _doc(f"{uuid4()}/r.pdf", status="FAILED", error_message="이전 오류")
    db_session.add(doc)
    await db_session.flush()
    doc_id = doc.id
    owner = await _owner(db_session)

    await documents_api.retry_failed_document(doc_id, db_session, owner)
    with pytest.raises(HTTPException) as second:
        await documents_api.retry_failed_document(doc_id, db_session, owner)

    assert second.value.status_code == 409
    assert started == [str(doc_id)]
    row = (await db_session.execute(select(Document.status, Document.error_message).where(Document.id == doc_id))).one()
    assert tuple(row) == ("QUEUED", None)


@pytest.mark.asyncio
async def test_full_reprocess_claims_document_once(db_session, dispatched):
    from app.schemas.document import DocumentReprocessRequest

    doc = _doc(f"{uuid4()}/f.pdf", status="INDEXED", parsed_text="기존 본문")
    db_session.add(doc)
    await db_session.flush()
    doc_id = doc.id
    owner = await _owner(db_session)

    await documents_api.reprocess_document(doc_id, DocumentReprocessRequest(edited_text="새 본문"), db_session, owner)
    with pytest.raises(HTTPException) as second:
        await documents_api.reprocess_document(
            doc_id, DocumentReprocessRequest(edited_text="또 다른 본문"), db_session, owner
        )

    assert second.value.status_code == 409
    assert len(dispatched) == 1
    row = (await db_session.execute(select(Document.status, Document.parsed_text).where(Document.id == doc_id))).one()
    assert tuple(row) == ("CHUNKING", "새 본문")
