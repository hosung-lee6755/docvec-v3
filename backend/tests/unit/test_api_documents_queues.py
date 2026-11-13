"""documents/queues.py — 검토 대기와 실패 화면 전용 목록. 실제 Postgres(db_session)."""
from uuid import uuid4

from app.api.v1.endpoints.documents import queues as qs
from app.db.models.pii_detection import PiiDetection
from app.db.models.quality_report import QualityReport
from app.db.models.workflow_run import WorkflowRun
from tests.unit._docs_api_support import add_step, doc_with_run, owner_user, stranger_user
from tests.unit._docs_api_support import db_session  # noqa: F401


async def _review(db, user=None):
    return await qs.review_queue(limit=200, db=db, current_user=user or owner_user())


async def _failures(db, user=None):
    return await qs.failure_queue(limit=200, db=db, current_user=user or owner_user())


def _mine(response, doc):
    return [item for item in response.items if item.document_id == doc.id]


async def test_review_queue_explains_quality_warnings(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "q-rev-quality", status="WAITING_REVIEW", original_filename="report.pdf")
    db_session.add(QualityReport(
        id=uuid4(), run_id=run.id, document_id=doc.id, status="REVIEW_REQUIRED", overall_score=42.5,
        warnings=["OCR 신뢰도가 낮은 쪽이 있습니다"], warning_categories=["ocr"],
    ))
    await db_session.flush()

    [item] = _mine(await _review(db_session), doc)

    assert item.reasons == ["quality"]
    assert item.filename == "report.pdf"
    assert item.overall_score == 42.5
    assert item.warnings == ["OCR 신뢰도가 낮은 쪽이 있습니다"]
    assert item.warning_categories == ["ocr"]


async def test_review_queue_counts_only_pending_pii(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "q-rev-pii", status="WAITING_REVIEW")
    for entity_type, approved in (("PHONE", False), ("PHONE", False), ("EMAIL", False), ("RRN", True)):
        db_session.add(PiiDetection(
            id=uuid4(), run_id=run.id, document_id=doc.id, entity_type=entity_type, action="MASK",
            approved_by=owner_user().id if approved else None,
        ))
    await db_session.flush()

    response = await _review(db_session)
    [item] = _mine(response, doc)

    assert item.reasons == ["pii"]
    assert item.pii_pending_count == 3
    assert item.pii_entity_types == ["EMAIL", "PHONE"]
    assert response.counts["pii"] >= 1


async def test_review_queue_marks_unknown_reason_and_hides_others_documents(db_session):  # noqa: F811
    doc, _ = await doc_with_run(db_session, "q-rev-unknown", status="WAITING_REVIEW")

    [item] = _mine(await _review(db_session), doc)
    other_view = await _review(db_session, user=stranger_user())

    assert item.reasons == ["unknown"]
    assert _mine(other_view, doc) == []


async def test_review_queue_skips_already_reviewed_quality_report(db_session):  # noqa: F811
    from datetime import datetime

    doc, run = await doc_with_run(db_session, "q-rev-done", status="WAITING_REVIEW")
    db_session.add(QualityReport(
        id=uuid4(), run_id=run.id, document_id=doc.id, status="FAILURE", reviewed_at=datetime.utcnow(),
    ))
    await db_session.flush()

    [item] = _mine(await _review(db_session), doc)

    assert item.reasons == ["unknown"]


async def test_failure_queue_reports_failed_step_cause_and_count(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "q-fail-step", status="FAILED", original_filename="scan.pdf")
    run.status = "FAILED"
    step = await add_step(db_session, run, block_type="ocr")
    step.status = "FAILED"
    step.error_message = "ReadTimeout: timed out"
    db_session.add(WorkflowRun(
        id=uuid4(), version_id=run.version_id, document_id=doc.id, status="FAILED", trigger="UPLOAD",
    ))
    await db_session.flush()

    [item] = _mine(await _failures(db_session), doc)

    assert item.failed_block_type == "ocr"
    assert item.error_message == "ReadTimeout: timed out"
    assert item.failure_count == 2
    assert item.can_retry is True


async def test_failure_queue_falls_back_to_document_message_when_no_failed_step(db_session):  # noqa: F811
    doc, _ = await doc_with_run(
        db_session, "q-fail-doc", status="FAILED", error_message="사용자가 검토를 반려하여 처리가 취소되었습니다",
    )

    [item] = _mine(await _failures(db_session), doc)

    assert item.failed_block_type is None
    assert item.error_message == "사용자가 검토를 반려하여 처리가 취소되었습니다"
    assert item.failure_count == 1
    assert item.can_retry is False
