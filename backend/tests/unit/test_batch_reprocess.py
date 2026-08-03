"""Coverage for POST /documents/batch-reprocess
(app.api.v1.endpoints.documents.batch_reprocess_documents) — added for the
"실패 목록에서 선택한 문서 일괄 재처리" feature. Unlike the single-document
/{document_id}/reprocess endpoint, the caller doesn't specify start_block_type
per document; this endpoint auto-resolves it from whichever WorkflowRunStep
actually failed for each document's active run."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.documents import (
    BatchReprocessRequest,
    batch_reprocess_documents,
)


def _doc(status="FAILED", active_run_id=None):
    doc = MagicMock()
    doc.id = uuid4()
    doc.status = status
    doc.active_run_id = active_run_id if active_run_id is not None else uuid4()
    return doc


@pytest.mark.asyncio
async def test_batch_reprocess_skips_non_failed_document():
    doc = _doc(status="INDEXED")
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=doc)

    with patch("app.api.v1.endpoints.documents.check_document_access", AsyncMock()):
        result = await batch_reprocess_documents(
            BatchReprocessRequest(ids=[doc.id]), db=db, current_user=MagicMock()
        )

    assert result.results[0].status == "skipped"
    assert "INDEXED" in result.results[0].detail


@pytest.mark.asyncio
async def test_batch_reprocess_reports_failed_when_document_not_found():
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    missing_id = uuid4()

    result = await batch_reprocess_documents(
        BatchReprocessRequest(ids=[missing_id]), db=db, current_user=MagicMock()
    )

    assert result.results[0].id == missing_id
    assert result.results[0].status == "failed"
    assert "찾을 수 없습니다" in result.results[0].detail


@pytest.mark.asyncio
async def test_batch_reprocess_reports_failed_on_access_denied():
    doc = _doc(status="FAILED")
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=doc)

    with patch(
        "app.api.v1.endpoints.documents.check_document_access",
        AsyncMock(side_effect=HTTPException(status_code=403, detail="Access denied")),
    ):
        result = await batch_reprocess_documents(
            BatchReprocessRequest(ids=[doc.id]), db=db, current_user=MagicMock()
        )

    assert result.results[0].status == "failed"
    assert result.results[0].detail == "Access denied"


@pytest.mark.asyncio
async def test_batch_reprocess_reports_failed_when_no_failed_step_found():
    run_id = uuid4()
    doc = _doc(status="FAILED", active_run_id=run_id)
    run = MagicMock(id=run_id, version_id=uuid4())
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[doc, None])  # doc lookup, then failed-step lookup
    db.get = AsyncMock(return_value=run)

    with patch("app.api.v1.endpoints.documents.check_document_access", AsyncMock()):
        result = await batch_reprocess_documents(
            BatchReprocessRequest(ids=[doc.id]), db=db, current_user=MagicMock()
        )

    assert result.results[0].status == "failed"
    assert "실패한 블록을 찾을 수 없어" in result.results[0].detail


@pytest.mark.asyncio
async def test_batch_reprocess_auto_resolves_failed_block_and_queues_run():
    run_id = uuid4()
    doc = _doc(status="FAILED", active_run_id=run_id)
    run = MagicMock(id=run_id, version_id=uuid4())
    failed_step = MagicMock(block_instance_id=uuid4())
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[doc, failed_step])
    db.get = AsyncMock(return_value=run)

    start_block = MagicMock()
    new_run = MagicMock(id=uuid4())

    with (
        patch("app.api.v1.endpoints.documents.check_document_access", AsyncMock()),
        patch(
            "app.services.reprocess_service.resolve_start_block",
            AsyncMock(return_value=start_block),
        ) as mock_resolve,
        patch(
            "app.services.reprocess_service.start_partial_reprocess",
            AsyncMock(return_value=new_run),
        ) as mock_start,
    ):
        result = await batch_reprocess_documents(
            BatchReprocessRequest(ids=[doc.id]), db=db, current_user=MagicMock()
        )

    mock_resolve.assert_awaited_once_with(db, run.version_id, None, failed_step.block_instance_id)
    mock_start.assert_awaited_once_with(db, doc, start_block, reason="실패 목록 일괄 재처리")
    assert result.results[0].status == "queued"
    assert result.results[0].run_id == new_run.id


@pytest.mark.asyncio
async def test_batch_reprocess_processes_multiple_documents_independently():
    # One skipped (not FAILED), one queued (failed step resolved) — a partial
    # failure on one document must not affect the others in the same batch.
    skip_doc = _doc(status="INDEXED")
    queue_doc = _doc(status="FAILED")
    run = MagicMock(id=queue_doc.active_run_id, version_id=uuid4())
    failed_step = MagicMock(block_instance_id=uuid4())

    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[skip_doc, queue_doc, failed_step])
    db.get = AsyncMock(return_value=run)

    start_block = MagicMock()
    new_run = MagicMock(id=uuid4())

    with (
        patch("app.api.v1.endpoints.documents.check_document_access", AsyncMock()),
        patch(
            "app.services.reprocess_service.resolve_start_block",
            AsyncMock(return_value=start_block),
        ),
        patch(
            "app.services.reprocess_service.start_partial_reprocess",
            AsyncMock(return_value=new_run),
        ),
    ):
        result = await batch_reprocess_documents(
            BatchReprocessRequest(ids=[skip_doc.id, queue_doc.id]),
            db=db, current_user=MagicMock(),
        )

    assert result.results[0].status == "skipped"
    assert result.results[1].status == "queued"
    assert result.results[1].run_id == new_run.id
