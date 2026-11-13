"""documents/chunks.py 엔드포인트 — 실제 Postgres(db_session) + Qdrant/Celery 모킹."""
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.v1.endpoints.documents import chunks as chunks_api
from app.core.config import settings
from app.db.models.document_chunk import DocumentChunk
from app.db.models.document_revision import DocumentTextRevision
from app.db.models.quality_report import QualityReport
from app.schemas.document import ChunkUpdateRequest
from tests.unit._docs_api_support import (
    add_doc,
    assert_http_error,
    doc_with_run,
    owner_user,
    stranger_user,
)
from tests.unit._docs_api_support import db_session  # noqa: F401


@pytest.fixture
def qdrant(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr("app.services.qdrant_service.qdrant_service", fake)
    return fake


def _hit(chunk_id, run_id, index: int, text: str = "본문", **payload) -> dict:
    return {"id": str(chunk_id), "payload": {"workflow_run_id": str(run_id), "chunk_index": index, "text": text, **payload}}


async def _chunk(db, doc, run, order: int, text: str = "청크", **fields) -> DocumentChunk:
    chunk = DocumentChunk(id=uuid4(), document_id=doc.id, run_id=run.id, chunk_order=order, chunk_text=text, **fields)
    db.add(chunk)
    await db.flush()
    return chunk


# ------------------------------------------------------------- list chunks
async def test_list_chunks_merges_qdrant_hits_with_postgres_metadata(db_session, qdrant):  # noqa: F811
    doc, run = await doc_with_run(db_session, "c-list")
    parent = await _chunk(db_session, doc, run, 0, "부모 본문", chunk_tier="parent")
    c1 = await _chunk(db_session, doc, run, 1, "자식1", token_count=7, chunk_type="PARAGRAPH", parent_chunk_id=parent.id,
                      section_path=["1장"], language="ko")
    other_run_hit = {"id": str(uuid4()), "payload": {"workflow_run_id": str(uuid4()), "chunk_index": 0}}
    qdrant.scroll_by_document.return_value = [
        _hit(c1.id, run.id, 5, "벡터 본문", page_number=3, disabled=True, edited=True),
        _hit(uuid4(), run.id, 2, "pg에 없는 청크"),
        other_run_hit,  # 이전 run의 고아 벡터는 걸러진다
    ]

    with patch("app.services.chunk_stats.get_hit_counts", return_value={str(c1.id): 4}):
        result = await chunks_api.list_document_chunks(doc.id, db_session, owner_user())

    chunks = result["chunks"]
    assert [c["chunk_index"] for c in chunks] == [2, 5]  # chunk_index 정렬 + 타 run 제외
    merged = chunks[1]
    assert merged["id"] == str(c1.id)
    assert (merged["disabled"], merged["edited"], merged["hit_count"], merged["embedded"]) == (True, True, 4, True)
    assert (merged["page_number"], merged["total_chunks"], merged["char_count"]) == (3, 2, len("벡터 본문"))
    assert (merged["token_count"], merged["chunk_type"], merged["heading_path"]) == (7, "PARAGRAPH", ["1장"])
    assert merged["parent_chunk_text"] == "부모 본문"
    assert "token_count" not in chunks[0] and chunks[0]["hit_count"] == 0


async def test_list_chunks_falls_back_to_postgres_child_rows_when_nothing_embedded(db_session, qdrant):  # noqa: F811
    doc, run = await doc_with_run(db_session, "c-list-pg")
    await _chunk(db_session, doc, run, 0, "부모", chunk_tier="parent")
    second = await _chunk(db_session, doc, run, 2, "둘째", page_start=4, edited=True)
    first = await _chunk(db_session, doc, run, 1, "첫째")
    qdrant.scroll_by_document.return_value = []

    result = await chunks_api.list_document_chunks(doc.id, db_session, owner_user())

    assert [c["id"] for c in result["chunks"]] == [str(first.id), str(second.id)]
    assert all(c["embedded"] is False and c["total_chunks"] == 2 for c in result["chunks"])
    assert result["chunks"][1]["page_number"] == 4 and result["chunks"][1]["edited"] is True


async def test_list_chunks_without_run_returns_empty(db_session, qdrant):  # noqa: F811
    doc = await add_doc(db_session, "c-list-norun")
    qdrant.scroll_by_document.return_value = []

    result = await chunks_api.list_document_chunks(doc.id, db_session, owner_user())

    assert result == {"document_id": str(doc.id), "chunks": []}


async def test_list_chunks_404_and_403(db_session, qdrant):  # noqa: F811
    doc = await add_doc(db_session, "c-list-403")
    await assert_http_error(chunks_api.list_document_chunks(uuid4(), db_session, owner_user()), 404)
    await assert_http_error(chunks_api.list_document_chunks(doc.id, db_session, stranger_user()), 403)


# ------------------------------------------------------------ update chunk
def _point(doc_id) -> dict:
    return {"payload": {"document_id": str(doc_id)}}


async def test_update_chunk_404_403_and_validation_order(db_session, qdrant):  # noqa: F811
    doc = await add_doc(db_session, "c-upd-guard")
    cid = str(uuid4())

    await assert_http_error(chunks_api.update_document_chunk(uuid4(), cid, ChunkUpdateRequest(disabled=True), db_session, owner_user()), 404)
    await assert_http_error(chunks_api.update_document_chunk(doc.id, cid, ChunkUpdateRequest(disabled=True), db_session, stranger_user()), 403)
    await assert_http_error(chunks_api.update_document_chunk(doc.id, cid, ChunkUpdateRequest(), db_session, owner_user()), 422)
    await assert_http_error(chunks_api.update_document_chunk(doc.id, cid, ChunkUpdateRequest(text="a", disabled=True), db_session, owner_user()), 400)
    await assert_http_error(chunks_api.update_document_chunk(doc.id, cid, ChunkUpdateRequest(text="   "), db_session, owner_user()), 422)
    qdrant.get_point.assert_not_called()


async def test_update_chunk_404_when_point_missing_or_belongs_to_other_document(db_session, qdrant):  # noqa: F811
    doc = await add_doc(db_session, "c-upd-404")
    body = ChunkUpdateRequest(disabled=True)

    qdrant.get_point.return_value = None
    await assert_http_error(chunks_api.update_document_chunk(doc.id, "x", body, db_session, owner_user()), 404)
    qdrant.get_point.return_value = _point(uuid4())
    await assert_http_error(chunks_api.update_document_chunk(doc.id, "x", body, db_session, owner_user()), 404)
    qdrant.set_point_payload.assert_not_called()


async def test_update_chunk_disabled_flag_is_written_to_payload(db_session, qdrant):  # noqa: F811
    doc = await add_doc(db_session, "c-upd-disable")
    qdrant.get_point.return_value = _point(doc.id)

    result = await chunks_api.update_document_chunk(doc.id, "pt-1", ChunkUpdateRequest(disabled=True), db_session, owner_user())

    assert result == {"message": "Chunk updated"}
    qdrant.set_point_payload.assert_called_once_with(settings.qdrant_collection_name, "pt-1", {"disabled": True})


def _fake_update_task(outcome=None, error: Exception | None = None):
    result = MagicMock()
    if error is not None:
        result.get.side_effect = error
    else:
        result.get.return_value = outcome
    return MagicMock(delay=MagicMock(return_value=result))


async def test_update_chunk_text_reembeds_on_worker(db_session, qdrant):  # noqa: F811
    doc = await add_doc(db_session, "c-upd-text")
    qdrant.get_point.return_value = _point(doc.id)
    task = _fake_update_task({"status": "OK"})

    with patch("app.pipeline.tasks.chunks.update_chunk_text", task):
        result = await chunks_api.update_document_chunk(doc.id, "pt-1", ChunkUpdateRequest(text="새 텍스트"), db_session, owner_user())

    assert result == {"message": "Chunk updated"}
    task.delay.assert_called_once_with(str(doc.id), "pt-1", "새 텍스트")
    qdrant.set_point_payload.assert_not_called()


async def test_update_chunk_text_maps_worker_failure_to_504_without_leaking_error(db_session, qdrant):  # noqa: F811
    doc = await add_doc(db_session, "c-upd-504")
    qdrant.get_point.return_value = _point(doc.id)
    task = _fake_update_task(error=RuntimeError("secret internal detail"))

    with patch("app.pipeline.tasks.chunks.update_chunk_text", task):
        err = await assert_http_error(
            chunks_api.update_document_chunk(doc.id, "pt-1", ChunkUpdateRequest(text="t"), db_session, owner_user()), 504
        )

    assert "secret" not in err.detail


async def test_update_chunk_text_404_when_worker_reports_missing_chunk(db_session, qdrant):  # noqa: F811
    doc = await add_doc(db_session, "c-upd-worker404")
    qdrant.get_point.return_value = _point(doc.id)

    with patch("app.pipeline.tasks.chunks.update_chunk_text", _fake_update_task({"status": "NOT_FOUND"})):
        await assert_http_error(chunks_api.update_document_chunk(doc.id, "pt-1", ChunkUpdateRequest(text="t"), db_session, owner_user()), 404)


# ------------------------------------------------------------ delete chunk
async def test_delete_chunk_rejects_malformed_uuid_before_any_lookup(db_session, qdrant):  # noqa: F811
    doc = await add_doc(db_session, "c-del-badid")

    await assert_http_error(chunks_api.delete_document_chunk(doc.id, "not-a-uuid", db_session, owner_user()), 422)
    qdrant.get_point.assert_not_called()


async def test_delete_chunk_404_403_and_foreign_point(db_session, qdrant):  # noqa: F811
    doc = await add_doc(db_session, "c-del-guard")
    cid = str(uuid4())

    await assert_http_error(chunks_api.delete_document_chunk(uuid4(), cid, db_session, owner_user()), 404)
    await assert_http_error(chunks_api.delete_document_chunk(doc.id, cid, db_session, stranger_user()), 403)
    qdrant.get_point.return_value = _point(uuid4())
    await assert_http_error(chunks_api.delete_document_chunk(doc.id, cid, db_session, owner_user()), 404)
    qdrant.delete_points.assert_not_called()


async def _report_with_chunk_warnings(db, doc, run, short_ids, long_ids) -> QualityReport:
    report = QualityReport(
        id=uuid4(), run_id=run.id, document_id=doc.id, status="SUCCESS_WITH_WARNING",
        metrics={"short_chunk_ids": short_ids, "long_chunk_ids": long_ids},
        warnings=["짧은 청크", "긴 청크"], warning_categories=["chunking_short", "chunking_long"],
    )
    db.add(report)
    await db.flush()
    return report


async def test_delete_chunk_removes_row_clears_resolved_warning_and_qdrant_point(db_session, qdrant):  # noqa: F811
    doc, run = await doc_with_run(db_session, "c-del-ok")
    victim = await _chunk(db_session, doc, run, 0)
    keeper = await _chunk(db_session, doc, run, 1)
    report = await _report_with_chunk_warnings(db_session, doc, run, [str(victim.id)], [str(keeper.id)])
    qdrant.get_point.return_value = _point(doc.id)

    result = await chunks_api.delete_document_chunk(doc.id, str(victim.id), db_session, owner_user())

    assert result == {"message": "Chunk deleted"}
    remaining = (await db_session.scalars(select(DocumentChunk.id).where(DocumentChunk.document_id == doc.id))).all()
    assert remaining == [keeper.id]
    await db_session.refresh(report)
    assert report.metrics["short_chunk_ids"] == []
    assert report.metrics["long_chunk_ids"] == [str(keeper.id)]
    # 해결된 chunking_short 경고만 사라지고 chunking_long은 남는다
    assert (report.warnings, report.warning_categories) == (["긴 청크"], ["chunking_long"])
    qdrant.delete_points.assert_called_once_with(settings.qdrant_collection_name, [str(victim.id)])


async def test_delete_chunk_keeps_warning_while_other_chunks_still_flagged(db_session, qdrant):  # noqa: F811
    doc, run = await doc_with_run(db_session, "c-del-partial")
    a, b = await _chunk(db_session, doc, run, 0), await _chunk(db_session, doc, run, 1)
    report = await _report_with_chunk_warnings(db_session, doc, run, [str(a.id), str(b.id)], [])
    qdrant.get_point.return_value = _point(doc.id)

    await chunks_api.delete_document_chunk(doc.id, str(a.id), db_session, owner_user())

    await db_session.refresh(report)
    assert report.metrics["short_chunk_ids"] == [str(b.id)]
    assert "chunking_short" in report.warning_categories


async def test_delete_chunk_uses_latest_report_when_no_active_run_and_survives_qdrant_failure(db_session, qdrant):  # noqa: F811
    doc, run = await doc_with_run(db_session, "c-del-fallback")
    doc.active_run_id = None
    chunk = await _chunk(db_session, doc, run, 0)
    report = await _report_with_chunk_warnings(db_session, doc, run, [str(chunk.id)], [])
    qdrant.get_point.return_value = _point(doc.id)
    qdrant.delete_points.side_effect = RuntimeError("qdrant down")

    result = await chunks_api.delete_document_chunk(doc.id, str(chunk.id), db_session, owner_user())

    assert result == {"message": "Chunk deleted"}  # DB는 이미 정리됨 — Qdrant 실패는 삼키고 로그만
    await db_session.refresh(report)
    assert report.metrics["short_chunk_ids"] == []


async def test_delete_chunk_without_any_report_still_succeeds(db_session, qdrant):  # noqa: F811
    doc = await add_doc(db_session, "c-del-noreport")
    qdrant.get_point.return_value = _point(doc.id)

    assert await chunks_api.delete_document_chunk(doc.id, str(uuid4()), db_session, owner_user()) == {"message": "Chunk deleted"}


# --------------------------------------------------------------- revisions
def _revision(doc_id, text: str, source: str = "RAG_EDIT") -> DocumentTextRevision:
    return DocumentTextRevision(id=uuid4(), document_id=doc_id, source=source, parsed_text=text, created_by=None)


async def test_revisions_list_has_preview_and_length(db_session):  # noqa: F811
    doc = await add_doc(db_session, "r-list")
    long_text = "가" * 300
    db_session.add(_revision(doc.id, long_text))
    await db_session.flush()

    result = await chunks_api.list_document_revisions(doc.id, db_session, owner_user())

    [item] = result["revisions"]
    assert item["text_length"] == 300
    assert item["preview"] == "가" * chunks_api._REVISION_PREVIEW_CHARS
    assert item["source"] == "RAG_EDIT"


async def test_revisions_hide_the_masked_text_kept_for_analysis(db_session):  # noqa: F811
    """청크 분할이 남기는 분석용 최종 텍스트는 개인정보가 가려진 텍스트라 버전 이력에 보이거나
    복원되면 원문이 마스킹된 텍스트로 바뀐다."""
    doc = await add_doc(db_session, "r-normalized", status="INDEXED")
    normalized = _revision(doc.id, "전화 ***-****-****", source="NORMALIZED")
    db_session.add_all([_revision(doc.id, "원문", source="PARSE"), normalized])
    await db_session.flush()

    result = await chunks_api.list_document_revisions(doc.id, db_session, owner_user())

    assert [r["source"] for r in result["revisions"]] == ["PARSE"]
    with patch("app.pipeline.tasks.process.continue_processing") as task:
        await assert_http_error(
            chunks_api.restore_document_revision(doc.id, normalized.id, db_session, owner_user()), 404)
    task.delay.assert_not_called()


async def test_revisions_list_404_and_403(db_session):  # noqa: F811
    doc = await add_doc(db_session, "r-list-403")
    await assert_http_error(chunks_api.list_document_revisions(uuid4(), db_session, owner_user()), 404)
    await assert_http_error(chunks_api.list_document_revisions(doc.id, db_session, stranger_user()), 403)


async def test_restore_revision_records_restore_and_dispatches(db_session):  # noqa: F811
    doc = await add_doc(db_session, "r-restore", status="INDEXED")
    rev = _revision(doc.id, "옛 본문")
    db_session.add(rev)
    await db_session.flush()

    with patch("app.pipeline.tasks.process.continue_processing") as task:
        result = await chunks_api.restore_document_revision(doc.id, rev.id, db_session, owner_user())

    assert result == {"message": "Restore started", "status": "CHUNKING"}
    task.delay.assert_called_once_with(str(doc.id), edited_text="옛 본문")
    sources = (await db_session.scalars(select(DocumentTextRevision.source).where(DocumentTextRevision.document_id == doc.id))).all()
    assert sorted(sources) == ["RAG_EDIT", "RESTORE"]


async def test_restore_revision_guards(db_session):  # noqa: F811
    indexed = await add_doc(db_session, "r-restore-g1", status="INDEXED")
    parsing = await add_doc(db_session, "r-restore-g2", status="PARSING")
    foreign_rev = _revision(parsing.id, "다른 문서")
    db_session.add(foreign_rev)
    await db_session.flush()

    with patch("app.pipeline.tasks.process.continue_processing") as task:
        await assert_http_error(chunks_api.restore_document_revision(uuid4(), uuid4(), db_session, owner_user()), 404)
        await assert_http_error(chunks_api.restore_document_revision(indexed.id, uuid4(), db_session, stranger_user()), 403)
        await assert_http_error(chunks_api.restore_document_revision(parsing.id, foreign_rev.id, db_session, owner_user()), 409)
        # 다른 문서의 revision은 내 문서에서 복원할 수 없다
        await assert_http_error(chunks_api.restore_document_revision(indexed.id, foreign_rev.id, db_session, owner_user()), 404)
    task.delay.assert_not_called()


# ------------------------------------------------------------------- retry
async def test_retry_404_403_and_409_when_not_failed(db_session):  # noqa: F811
    ok = await add_doc(db_session, "retry-409", status="INDEXED")

    await assert_http_error(chunks_api.retry_failed_document(uuid4(), db_session, owner_user()), 404)
    await assert_http_error(chunks_api.retry_failed_document(ok.id, db_session, stranger_user()), 403)
    err = await assert_http_error(chunks_api.retry_failed_document(ok.id, db_session, owner_user()), 409)
    assert "INDEXED" in err.detail
