"""짧은 청크를 앞뒤 청크와 합치기, 검토 대기 중(임베딩 전) 청크 수정·삭제 (2026-11-17 화면 검토 의견)."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.v1.endpoints.documents import chunk_edits as edits_api
from app.api.v1.endpoints.documents import chunks as chunks_api
from app.db.models.document_chunk import DocumentChunk
from app.db.models.quality_report import QualityReport
from app.schemas.document import ChunkMergeRequest, ChunkUpdateRequest
from tests.unit._docs_api_support import assert_http_error, owner_user, stranger_user
from tests.unit._docs_api_support import db_session  # noqa: F401
from tests.unit._docs_api_support import doc_with_run as _doc_with_run

LONG = "가" * 60


async def doc_with_run(db, key, **overrides):
    """검토 대기 문서면 run도 실제처럼 WAITING_REVIEW로 멈춰 둔다."""
    doc, run = await _doc_with_run(db, key, **overrides)
    if doc.status == "WAITING_REVIEW":
        run.status = "WAITING_REVIEW"
        await db.flush()
    return doc, run


@pytest.fixture
def qdrant(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr("app.services.qdrant_service.qdrant_service", fake)
    return fake


async def _chain(db, doc, run, texts, *, embedded=False):
    """앞뒤 링크가 이어진 child 청크들. parent 행을 하나 섞어 둔다(합칠 대상이 되면 안 된다)."""
    parent = DocumentChunk(id=uuid4(), document_id=doc.id, run_id=run.id, chunk_order=1_000_000,
                           chunk_text="부모", chunk_tier="parent")
    db.add(parent)
    chunks = []
    for order, text in enumerate(texts):
        chunk = DocumentChunk(id=uuid4(), document_id=doc.id, run_id=run.id, chunk_order=order, chunk_text=text,
                              char_count=len(text), embedded=embedded, parent_chunk_id=parent.id, page_start=order + 1)
        db.add(chunk)
        chunks.append(chunk)
    await db.flush()
    for prev, nxt in zip(chunks, chunks[1:]):
        prev.next_chunk_id = nxt.id
        nxt.prev_chunk_id = prev.id
    await db.flush()
    # 테스트가 expire_all() 뒤에 id를 읽어도 지연 로드가 일어나지 않게 값으로 바꿔 둔다
    return [SimpleNamespace(id=c.id) for c in chunks]


async def _report(db, doc, run, short_ids):
    report = QualityReport(
        document_id=doc.id, run_id=run.id, overall_score=90.0, status="REVIEW_REQUIRED",
        metrics={"short_chunk_ids": [str(i) for i in short_ids], "long_chunk_ids": []},
        warnings=["너무 짧은 청크가 1개 있습니다(50자 미만)."], warning_categories=["chunking_short"],
    )
    db.add(report)
    await db.flush()
    return report


async def _reload(db, chunk_id):
    # 다른 객체를 만료시키지 않고 이 행만 DB 값으로 새로 읽는다
    return await db.scalar(
        select(DocumentChunk).where(DocumentChunk.id == chunk_id).execution_options(populate_existing=True)
    )


# ---------------------------------------------------------------- 합치기(검토 대기, 임베딩 전)
async def test_merge_short_chunk_into_previous_while_waiting_for_review(db_session, qdrant):  # noqa: F811
    doc, run = await doc_with_run(db_session, "m-prev", status="WAITING_REVIEW")
    a, b, c = await _chain(db_session, doc, run, [LONG, "짧은 꼬리", LONG + "다"])
    report = await _report(db_session, doc, run, [b.id])

    result = await edits_api.merge_document_chunk(doc.id, str(b.id), ChunkMergeRequest(direction="prev"),
                                                  db_session, owner_user("editor"))

    kept = await _reload(db_session, a.id)
    assert result["kept_chunk_id"] == str(a.id)
    assert kept.chunk_text == f"{LONG}\n짧은 꼬리" and kept.edited and kept.char_count == len(kept.chunk_text)
    assert await _reload(db_session, b.id) is None
    kept_next = str(kept.next_chunk_id)
    assert kept_next == str(c.id) and str((await _reload(db_session, c.id)).prev_chunk_id) == str(a.id)
    await db_session.refresh(report)
    assert report.metrics["short_chunk_ids"] == [] and "chunking_short" not in report.warning_categories
    qdrant.get_point.assert_not_called()  # 임베딩 전이라 벡터 저장소는 건드리지 않는다


async def test_merge_short_chunk_into_next(db_session, qdrant):  # noqa: F811
    doc, run = await doc_with_run(db_session, "m-next", status="WAITING_REVIEW")
    a, b, c = await _chain(db_session, doc, run, ["표 제목", LONG, LONG])

    result = await edits_api.merge_document_chunk(doc.id, str(a.id), ChunkMergeRequest(direction="next"),
                                                  db_session, owner_user("editor"))

    kept = await _reload(db_session, b.id)
    assert result["kept_chunk_id"] == str(b.id)
    assert kept.chunk_text == f"표 제목\n{LONG}" and kept.prev_chunk_id is None and kept.page_start == 1
    assert await _reload(db_session, a.id) is None


async def test_merge_without_a_neighbour_is_rejected(db_session, qdrant):  # noqa: F811
    doc, run = await doc_with_run(db_session, "m-edge", status="WAITING_REVIEW")
    a, _b = await _chain(db_session, doc, run, ["처음", LONG])

    await assert_http_error(
        edits_api.merge_document_chunk(doc.id, str(a.id), ChunkMergeRequest(direction="prev"), db_session, owner_user("editor")),
        409,
    )


async def test_merge_needs_editor_access(db_session, qdrant):  # noqa: F811
    doc, run = await doc_with_run(db_session, "m-perm", status="WAITING_REVIEW")
    _a, b = await _chain(db_session, doc, run, [LONG, "짧음"])

    await assert_http_error(
        edits_api.merge_document_chunk(doc.id, str(b.id), ChunkMergeRequest(direction="prev"), db_session, stranger_user()),
        403,
    )


# ---------------------------------------------------------------- 합치기(색인 완료, 임베딩됨)
async def test_merge_embedded_chunks_reembeds_the_kept_one_and_removes_the_other(db_session, qdrant):  # noqa: F811
    doc, run = await doc_with_run(db_session, "m-emb", status="INDEXED")
    a, b = await _chain(db_session, doc, run, ["앞 청크 본문", "짧음"], embedded=True)
    qdrant.get_point.side_effect = lambda _col, pid: {
        "id": pid, "payload": {"document_id": str(doc.id), "text": {str(a.id): "앞 청크(수정본)", str(b.id): "짧음"}[pid]},
    }
    task = MagicMock()
    task.delay.return_value.get.return_value = {"status": "OK"}

    with patch("app.pipeline.tasks.chunks.update_chunk_text", task):
        await edits_api.merge_document_chunk(doc.id, str(b.id), ChunkMergeRequest(direction="prev"),
                                             db_session, owner_user("editor"))

    # 수정된 적이 있으면 벡터 저장소의 글이 최신이므로 그것을 기준으로 합친다
    task.delay.assert_called_once_with(str(doc.id), str(a.id), "앞 청크(수정본)\n짧음")
    qdrant.delete_points.assert_called_once()
    assert str(b.id) in qdrant.delete_points.call_args.args[1]
    assert (await _reload(db_session, a.id)).chunk_text == "앞 청크(수정본)\n짧음"
    assert await _reload(db_session, b.id) is None


async def test_merge_is_refused_while_the_document_is_being_processed(db_session, qdrant):  # noqa: F811
    doc, run = await doc_with_run(db_session, "m-busy", status="CHUNKING")
    _a, b = await _chain(db_session, doc, run, [LONG, "짧음"])

    await assert_http_error(
        edits_api.merge_document_chunk(doc.id, str(b.id), ChunkMergeRequest(direction="prev"), db_session, owner_user("editor")),
        409,
    )


# ---------------------------------------------------------------- 검토 대기 중 수정·삭제
async def test_editing_a_draft_chunk_updates_postgres_only_and_clears_a_resolved_warning(db_session, qdrant):  # noqa: F811
    doc, run = await doc_with_run(db_session, "e-draft", status="WAITING_REVIEW")
    _a, b = await _chain(db_session, doc, run, [LONG, "짧음"])
    report = await _report(db_session, doc, run, [b.id])

    await chunks_api.update_document_chunk(doc.id, str(b.id), ChunkUpdateRequest(text=LONG + "보강"),
                                           db_session, owner_user("editor"))

    edited = await _reload(db_session, b.id)
    assert edited.chunk_text == LONG + "보강" and edited.edited
    await db_session.refresh(report)
    assert report.metrics["short_chunk_ids"] == []
    qdrant.get_point.assert_not_called()


async def test_draft_chunks_cannot_be_excluded_from_search_before_approval(db_session, qdrant):  # noqa: F811
    doc, run = await doc_with_run(db_session, "x-draft", status="WAITING_REVIEW")
    _a, b = await _chain(db_session, doc, run, [LONG, "짧음"])

    await assert_http_error(
        chunks_api.update_document_chunk(doc.id, str(b.id), ChunkUpdateRequest(disabled=True), db_session, owner_user("editor")),
        409,
    )


async def test_deleting_a_draft_chunk_relinks_neighbours_without_touching_qdrant(db_session, qdrant):  # noqa: F811
    doc, run = await doc_with_run(db_session, "d-draft", status="WAITING_REVIEW")
    a, b, c = await _chain(db_session, doc, run, [LONG, "짧음", LONG])

    await chunks_api.delete_document_chunk(doc.id, str(b.id), db_session, owner_user("editor"))

    assert await _reload(db_session, b.id) is None
    assert str((await _reload(db_session, a.id)).next_chunk_id) == str(c.id)
    qdrant.get_point.assert_not_called()
    qdrant.delete_points.assert_not_called()


# ---------------------------------------------------------------- 리뷰 지적 사항(2026-11-17)
async def test_merging_a_pii_excluded_chunk_into_a_normal_one_is_refused(db_session, qdrant):  # noqa: F811
    doc, run = await doc_with_run(db_session, "m-pii", status="WAITING_REVIEW")
    a, b = await _chain(db_session, doc, run, [LONG, "짧음"])
    (await _reload(db_session, b.id)).excluded_pii = True
    await db_session.flush()

    await assert_http_error(
        edits_api.merge_document_chunk(doc.id, str(b.id), ChunkMergeRequest(direction="prev"), db_session, owner_user("editor")),
        409,
    )
    assert (await _reload(db_session, a.id)).chunk_text == LONG


async def test_merging_chunks_with_different_search_exclusion_is_refused(db_session, qdrant):  # noqa: F811
    doc, run = await doc_with_run(db_session, "m-dis", status="INDEXED")
    a, b = await _chain(db_session, doc, run, ["앞 청크 본문", "짧음"], embedded=True)
    qdrant.get_point.side_effect = lambda _col, pid: {
        "id": pid, "payload": {"document_id": str(doc.id), "text": "글", "disabled": pid == str(b.id)},
    }
    task = MagicMock()

    with patch("app.pipeline.tasks.chunks.update_chunk_text", task):
        await assert_http_error(
            edits_api.merge_document_chunk(doc.id, str(b.id), ChunkMergeRequest(direction="prev"), db_session, owner_user("editor")),
            409,
        )
    task.delay.assert_not_called()


async def test_draft_chunks_are_locked_once_the_review_is_approved(db_session, qdrant):  # noqa: F811
    # 승인 직후 run은 RUNNING이고 문서는 rag_store가 끝날 때까지 WAITING_REVIEW로 남는다
    doc, run = await doc_with_run(db_session, "m-resumed", status="WAITING_REVIEW")
    _a, b = await _chain(db_session, doc, run, [LONG, "짧음"])
    run.status = "RUNNING"
    await db_session.flush()

    await assert_http_error(
        edits_api.merge_document_chunk(doc.id, str(b.id), ChunkMergeRequest(direction="prev"), db_session, owner_user("editor")),
        409,
    )
    await assert_http_error(
        chunks_api.update_document_chunk(doc.id, str(b.id), ChunkUpdateRequest(text=LONG), db_session, owner_user("editor")),
        409,
    )
