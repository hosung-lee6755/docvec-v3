"""documents/processing.py 엔드포인트 — 실제 Postgres(db_session) + Celery/재처리 서비스 모킹."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.v1.endpoints.documents import processing as proc
from app.db.models.document import Document
from app.db.models.document_node import DocumentNode
from app.db.models.document_revision import DocumentTextRevision
from app.db.models.quality_report import QualityReport
from app.schemas.document import (
    DocumentProceedRequest,
    DocumentReprocessRequest,
    ElementCorrectionRequest,
    NodeCorrectionRequest,
)
from app.services.reprocess_service import ReprocessError
from tests.unit._docs_api_support import (
    add_doc,
    assert_http_error,
    doc_with_run,
    owner_user,
    stranger_user,
)
from tests.unit._docs_api_support import db_session  # noqa: F401

CONTINUE = "app.pipeline.tasks.process.continue_processing"


async def _revisions(db, document_id) -> list[DocumentTextRevision]:
    return list((await db.scalars(select(DocumentTextRevision).where(DocumentTextRevision.document_id == document_id))).all())


async def _fresh_status(db, doc) -> str:
    await db.refresh(doc)
    return doc.status


# ---------------------------------------------------------------- status
async def test_status_returns_status_and_error_message(db_session):  # noqa: F811
    doc = await add_doc(db_session, "p-status", status="FAILED", error_message="boom")

    result = await proc.get_document_status(doc.id, db_session, owner_user())

    assert result == {"status": "FAILED", "error_message": "boom"}


async def test_status_404_for_unknown_document(db_session):  # noqa: F811
    await assert_http_error(proc.get_document_status(uuid4(), db_session, owner_user()), 404)


async def test_status_403_for_user_without_access(db_session):  # noqa: F811
    doc = await add_doc(db_session, "p-status-403")

    await assert_http_error(proc.get_document_status(doc.id, db_session, stranger_user()), 403)


# --------------------------------------------------------------- proceed
async def test_proceed_404_for_unknown_document(db_session):  # noqa: F811
    await assert_http_error(
        proc.proceed_document(uuid4(), DocumentProceedRequest(), db_session, owner_user()), 404
    )


async def test_proceed_409_when_document_is_not_awaiting_review(db_session):  # noqa: F811
    doc = await add_doc(db_session, "p-proceed-409", status="INDEXED")

    with patch(CONTINUE) as task:
        err = await assert_http_error(
            proc.proceed_document(doc.id, DocumentProceedRequest(), db_session, owner_user()), 409
        )

    assert "INDEXED" in err.detail
    task.delay.assert_not_called()


async def test_proceed_with_edited_text_claims_status_and_records_revision(db_session):  # noqa: F811
    doc = await add_doc(db_session, "p-proceed-ok", status="REVIEW_PENDING")

    with patch(CONTINUE) as task:
        result = await proc.proceed_document(
            doc.id, DocumentProceedRequest(edited_text="수정된 본문"), db_session, owner_user()
        )

    assert result == {"message": "Processing resumed", "status": "CHUNKING"}
    task.delay.assert_called_once_with(str(doc.id))
    assert await _fresh_status(db_session, doc) == "CHUNKING"
    assert doc.parsed_text == "수정된 본문"
    revisions = await _revisions(db_session, doc.id)
    assert [(r.source, r.parsed_text) for r in revisions] == [("REVIEW_EDIT", "수정된 본문")]


async def test_proceed_without_edited_text_adds_no_revision(db_session):  # noqa: F811
    doc = await add_doc(db_session, "p-proceed-noedit", status="REVIEW_PENDING", parsed_text="원본")

    with patch(CONTINUE) as task:
        await proc.proceed_document(doc.id, DocumentProceedRequest(), db_session, owner_user())

    task.delay.assert_called_once()
    assert await _revisions(db_session, doc.id) == []
    assert await _fresh_status(db_session, doc) == "CHUNKING"
    assert doc.parsed_text == "원본"


# ------------------------------------------------------------- reprocess
async def test_reprocess_404_and_403(db_session):  # noqa: F811
    doc = await add_doc(db_session, "p-rep-403")

    await assert_http_error(proc.reprocess_document(uuid4(), DocumentReprocessRequest(edited_text="x"), db_session, owner_user()), 404)
    await assert_http_error(
        proc.reprocess_document(doc.id, DocumentReprocessRequest(edited_text="x"), db_session, stranger_user()), 403
    )


async def test_reprocess_legacy_path_409_when_not_indexed(db_session):  # noqa: F811
    doc = await add_doc(db_session, "p-rep-409", status="FAILED")

    with patch(CONTINUE) as task:
        err = await assert_http_error(
            proc.reprocess_document(doc.id, DocumentReprocessRequest(edited_text="x"), db_session, owner_user()), 409
        )

    assert "FAILED" in err.detail
    task.delay.assert_not_called()


async def test_reprocess_legacy_path_replaces_text_and_dispatches(db_session):  # noqa: F811
    doc = await add_doc(db_session, "p-rep-ok", status="INDEXED")

    with patch(CONTINUE) as task:
        result = await proc.reprocess_document(
            doc.id, DocumentReprocessRequest(edited_text="새 본문"), db_session, owner_user()
        )

    assert result == {"message": "Reprocessing started", "status": "CHUNKING"}
    task.delay.assert_called_once_with(str(doc.id), edited_text="새 본문")
    assert await _fresh_status(db_session, doc) == "CHUNKING"
    assert [r.source for r in await _revisions(db_session, doc.id)] == ["RAG_EDIT"]


def test_reprocess_request_schema_requires_text_or_start_block():
    # 스키마가 edited_text 없는 레거시 호출을 막아 NOT NULL revision 삽입에 도달하지 못한다
    with pytest.raises(ValueError):
        DocumentReprocessRequest()


async def test_reprocess_partial_409_when_document_never_ran_a_workflow(db_session):  # noqa: F811
    doc = await add_doc(db_session, "p-rep-norun")
    body = DocumentReprocessRequest(start_block_type="chunk_split")

    with patch("app.services.reprocess_service.reconcile_stuck_run", new=AsyncMock()) as reconcile:
        err = await assert_http_error(proc.reprocess_document(doc.id, body, db_session, owner_user()), 409)

    reconcile.assert_awaited_once()
    assert "워크플로우" in err.detail


async def test_reprocess_partial_starts_new_run(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "p-rep-partial")
    new_run = MagicMock(id=uuid4(), impact={"steps": 3})
    body = DocumentReprocessRequest(start_block_type="chunk_split", reason="재시도", timeout_overrides={"chunk_split": 900})

    with (
        patch("app.services.reprocess_service.reconcile_stuck_run", new=AsyncMock()),
        patch("app.services.reprocess_service.resolve_start_block", new=AsyncMock(return_value="blk")) as resolve,
        patch("app.services.reprocess_service.start_partial_reprocess", new=AsyncMock(return_value=new_run)) as start,
    ):
        result = await proc.reprocess_document(doc.id, body, db_session, owner_user())

    assert result == {
        "message": "부분 재처리가 시작되었습니다", "run_id": str(new_run.id), "status": "QUEUED", "impact": {"steps": 3},
    }
    assert resolve.await_args.args[1:] == (run.version_id, "chunk_split", None)
    assert start.await_args.kwargs["timeout_overrides"] == {"chunk_split": 900}
    assert start.await_args.args[3] == "재시도"


async def test_reprocess_partial_maps_reprocess_error_to_409(db_session):  # noqa: F811
    doc, _ = await doc_with_run(db_session, "p-rep-partial-err")
    body = DocumentReprocessRequest(start_block_instance_id=uuid4())

    with (
        patch("app.services.reprocess_service.reconcile_stuck_run", new=AsyncMock()),
        patch("app.services.reprocess_service.resolve_start_block", new=AsyncMock(side_effect=ReprocessError("블록 없음"))),
    ):
        err = await assert_http_error(proc.reprocess_document(doc.id, body, db_session, owner_user()), 409)

    assert err.detail == "블록 없음"


# ------------------------------------------------------------ runs/quality
async def test_runs_lists_newest_first(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "p-runs")
    older_version = run.version_id
    from tests.unit._docs_api_support import _run
    class _V:  # _run은 version.id만 쓴다
        id = older_version
    older = await _run(db_session, doc, _V, "REPROCESS", minutes_ago=30)

    result = await proc.list_document_runs(doc.id, db_session, owner_user())

    assert [r.id for r in result["runs"]] == [run.id, older.id]
    assert result["document_id"] == str(doc.id)


async def test_runs_404_and_403(db_session):  # noqa: F811
    doc = await add_doc(db_session, "p-runs-403")
    await assert_http_error(proc.list_document_runs(uuid4(), db_session, owner_user()), 404)
    await assert_http_error(proc.list_document_runs(doc.id, db_session, stranger_user()), 403)


def _report(doc, run_id, score: float) -> QualityReport:
    return QualityReport(id=uuid4(), run_id=run_id, document_id=doc.id, overall_score=score, status="SUCCESS")


async def test_quality_prefers_active_run_report(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "p-q-active")
    report = _report(doc, run.id, 0.9)
    db_session.add(report)
    await db_session.flush()

    assert (await proc.get_document_quality(doc.id, db_session, owner_user())).id == report.id


async def test_quality_falls_back_to_latest_report_when_active_run_has_none(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "p-q-fallback")
    doc.active_run_id = None
    report = _report(doc, run.id, 0.5)
    db_session.add(report)
    await db_session.flush()

    assert (await proc.get_document_quality(doc.id, db_session, owner_user())).id == report.id


async def test_quality_returns_none_without_reports_and_404_for_unknown(db_session):  # noqa: F811
    doc = await add_doc(db_session, "p-q-none")

    assert await proc.get_document_quality(doc.id, db_session, owner_user()) is None
    await assert_http_error(proc.get_document_quality(uuid4(), db_session, owner_user()), 404)
    await assert_http_error(proc.get_document_quality(doc.id, db_session, stranger_user()), 403)


# ---------------------------------------------------------------- impact
async def test_impact_requires_a_start_block_selector(db_session):  # noqa: F811
    await assert_http_error(proc.get_document_reprocess_impact(uuid4(), None, None, db_session, owner_user()), 422)


async def test_impact_404_403_and_409_without_run(db_session):  # noqa: F811
    doc = await add_doc(db_session, "p-imp-norun")

    await assert_http_error(proc.get_document_reprocess_impact(uuid4(), "chunk_split", None, db_session, owner_user()), 404)
    await assert_http_error(proc.get_document_reprocess_impact(doc.id, "chunk_split", None, db_session, stranger_user()), 403)
    await assert_http_error(proc.get_document_reprocess_impact(doc.id, "chunk_split", None, db_session, owner_user()), 409)


async def test_impact_returns_computed_impact(db_session):  # noqa: F811
    doc, _ = await doc_with_run(db_session, "p-imp-ok")
    computed = MagicMock(impact={"downstream": ["a", "b"]})

    with (
        patch("app.services.reprocess_service.resolve_start_block", new=AsyncMock(return_value="blk")),
        patch("app.services.reprocess_service.compute_reprocess_impact", new=AsyncMock(return_value=computed)),
    ):
        result = await proc.get_document_reprocess_impact(doc.id, "chunk_split", None, db_session, owner_user())

    assert result == {"downstream": ["a", "b"]}


async def test_impact_maps_reprocess_error_to_409(db_session):  # noqa: F811
    doc, _ = await doc_with_run(db_session, "p-imp-err")

    with patch("app.services.reprocess_service.resolve_start_block", new=AsyncMock(side_effect=ReprocessError("x"))):
        err = await assert_http_error(
            proc.get_document_reprocess_impact(doc.id, None, uuid4(), db_session, owner_user()), 409
        )

    assert err.detail == "x"


# ----------------------------------------------------- _resolve_display_run_id
async def test_display_run_is_none_for_document_without_runs(db_session):  # noqa: F811
    doc = await add_doc(db_session, "p-disp-none")

    assert await proc._resolve_display_run_id(db_session, doc) is None


# ----------------------------------------------------------------- nodes
async def _node(db, doc, run, **fields) -> DocumentNode:
    node = DocumentNode(id=uuid4(), document_id=doc.id, run_id=run.id, node_type="PARAGRAPH", **fields)
    db.add(node)
    await db.flush()
    return node


async def test_nodes_are_sorted_and_scoped_to_display_run(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "p-nodes")
    second = await _node(db_session, doc, run, sort_order=2, text="b")
    first = await _node(db_session, doc, run, sort_order=1, text="a")

    result = await proc.list_document_nodes(doc.id, db_session, owner_user())

    assert result["run_id"] == str(run.id)
    assert [n.id for n in result["nodes"]] == [first.id, second.id]


async def test_nodes_empty_without_run(db_session):  # noqa: F811
    doc = await add_doc(db_session, "p-nodes-empty")

    result = await proc.list_document_nodes(doc.id, db_session, owner_user())

    assert result == {"document_id": str(doc.id), "run_id": None, "nodes": []}
    await assert_http_error(proc.list_document_nodes(uuid4(), db_session, owner_user()), 404)
    await assert_http_error(proc.list_document_nodes(doc.id, db_session, stranger_user()), 403)


async def test_correct_node_updates_type_level_and_merges_style(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "p-node-fix")
    node = await _node(db_session, doc, run, style={"bold": True, "font_size": 10.0})
    body = NodeCorrectionRequest(node_type="HEADING", level=2, font_size=14.0, style_name="제목", correction_notes="오분류")

    result = await proc.correct_document_node(doc.id, node.id, body, db_session, owner_user())

    assert (result.node_type, result.level) == ("HEADING", 2)
    assert result.style == {"bold": True, "font_size": 14.0, "style_name": "제목"}
    assert result.user_corrected is True
    assert result.correction_type == "node_type,level,style"
    assert result.correction_notes == "오분류"


async def test_correct_node_rejects_unknown_node_type(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "p-node-badtype")
    node = await _node(db_session, doc, run)

    err = await assert_http_error(
        proc.correct_document_node(doc.id, node.id, NodeCorrectionRequest(node_type="BOGUS"), db_session, owner_user()), 422
    )

    assert "BOGUS" in err.detail
    assert node.user_corrected is not True


async def test_correct_node_404_and_403(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "p-node-404")
    node = await _node(db_session, doc, run)
    body = NodeCorrectionRequest(level=1)

    await assert_http_error(proc.correct_document_node(uuid4(), node.id, body, db_session, owner_user()), 404)
    await assert_http_error(proc.correct_document_node(doc.id, uuid4(), body, db_session, owner_user()), 404)
    await assert_http_error(proc.correct_document_node(doc.id, node.id, body, db_session, stranger_user()), 403)


# -------------------------------------------------------------- elements
async def test_elements_default_to_empty_list_and_return_stored(db_session):  # noqa: F811
    empty = await add_doc(db_session, "p-el-empty")
    filled = await add_doc(db_session, "p-el-filled", elements=[{"id": "e1", "type": "paragraph"}])

    assert (await proc.list_document_elements(empty.id, db_session, owner_user()))["elements"] == []
    assert (await proc.list_document_elements(filled.id, db_session, owner_user()))["elements"] == [
        {"id": "e1", "type": "paragraph"}
    ]
    await assert_http_error(proc.list_document_elements(uuid4(), db_session, owner_user()), 404)
    await assert_http_error(proc.list_document_elements(filled.id, db_session, stranger_user()), 403)


async def test_correct_element_updates_content_and_metadata_only_for_target(db_session):  # noqa: F811
    elements = [
        {"id": "e1", "content": {"markdown": "old", "html": "<p/>"}, "metadata": {"page": 1}},
        {"id": "e2", "content": {"markdown": "keep"}},
    ]
    doc = await add_doc(db_session, "p-el-fix", elements=elements)
    body = ElementCorrectionRequest(markdown="# new", style="Heading1", font_size=12.0, correction_notes="수정")

    result = await proc.correct_document_element(doc.id, "e1", body, db_session, owner_user())

    assert result["content"] == {"markdown": "# new", "html": "<p/>", "text": "# new"}
    assert result["metadata"] == {"page": 1, "style": "Heading1", "font_size": 12.0}
    assert result["user_corrected"] is True
    await db_session.refresh(doc)  # DB에 실제로 UPDATE가 나갔는지(JSON 재할당 추적) 확인
    assert doc.elements[0]["content"]["markdown"] == "# new"
    assert doc.elements[1] == {"id": "e2", "content": {"markdown": "keep"}}


async def test_correct_element_without_metadata_updates_leaves_metadata_untouched(db_session):  # noqa: F811
    doc = await add_doc(db_session, "p-el-nometa", elements=[{"id": "e1"}])

    result = await proc.correct_document_element(doc.id, "e1", ElementCorrectionRequest(markdown="m"), db_session, owner_user())

    assert "metadata" not in result


async def test_correct_element_404_for_unknown_element_document_and_403(db_session):  # noqa: F811
    doc = await add_doc(db_session, "p-el-404", elements=[{"id": "e1"}])
    body = ElementCorrectionRequest(markdown="m")

    await assert_http_error(proc.correct_document_element(doc.id, "nope", body, db_session, owner_user()), 404)
    await assert_http_error(proc.correct_document_element(uuid4(), "e1", body, db_session, owner_user()), 404)
    await assert_http_error(proc.correct_document_element(doc.id, "e1", body, db_session, stranger_user()), 403)
    assert isinstance(doc, Document)
