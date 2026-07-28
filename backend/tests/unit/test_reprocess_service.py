"""Unit coverage for the stuck-run watchdog and reprocess guard relaxation
added to recover a WorkflowRun/WorkflowRunStep that Celery's hard time limit
SIGKILLed mid-execution (billiard kills the worker fork process directly, so
no application code ever runs to mark the run FAILED — see
app/services/reprocess_service.py::reconcile_stuck_run)."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.reprocess_service import (
    ReprocessError,
    ReprocessImpact,
    compute_reprocess_impact,
    reconcile_stuck_run,
    start_partial_reprocess,
)


def _doc(active_run_id=None):
    doc = MagicMock()
    doc.id = uuid4()
    doc.active_run_id = active_run_id
    doc.status = "PARSING"
    doc.error_message = None
    return doc


def _run(status="RUNNING", timeout_overrides=None):
    run = MagicMock()
    run.id = uuid4()
    run.status = status
    run.error_message = None
    run.completed_at = None
    run.timeout_overrides = timeout_overrides
    return run


def _step(started_at, status="RUNNING"):
    step = MagicMock()
    step.status = status
    step.started_at = started_at
    step.error_code = None
    step.error_message = None
    step.completed_at = None
    step.block_instance_id = uuid4()
    return step


def _block(block_type, config=None):
    block = MagicMock()
    block.block_type = block_type
    block.config = config or {}
    return block


@pytest.mark.asyncio
async def test_reconcile_stuck_run_returns_false_when_no_active_run():
    doc = _doc(active_run_id=None)
    db = AsyncMock()

    assert await reconcile_stuck_run(db, doc) is False
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_stuck_run_returns_false_when_run_not_running():
    run = _run(status="COMPLETED")
    doc = _doc(active_run_id=run.id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=run)

    assert await reconcile_stuck_run(db, doc) is False
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_stuck_run_returns_false_when_no_running_step():
    run = _run(status="RUNNING")
    doc = _doc(active_run_id=run.id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=run)
    db.scalar = AsyncMock(return_value=None)

    assert await reconcile_stuck_run(db, doc) is False
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_stuck_run_returns_false_within_timeout_grace():
    run = _run(status="RUNNING")
    doc = _doc(active_run_id=run.id)
    step = _step(started_at=datetime.utcnow() - timedelta(seconds=100))
    block = _block("text_extract", config={"timeoutSeconds": 300})

    db = AsyncMock()
    db.get = AsyncMock(side_effect=[run, block])
    db.scalar = AsyncMock(return_value=step)

    assert await reconcile_stuck_run(db, doc) is False
    assert step.status == "RUNNING"
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_stuck_run_marks_failed_when_timeout_and_grace_exceeded():
    run = _run(status="RUNNING")
    doc = _doc(active_run_id=run.id)
    step = _step(started_at=datetime.utcnow() - timedelta(seconds=400))
    block = _block("text_extract", config={"timeoutSeconds": 300})

    db = AsyncMock()
    db.get = AsyncMock(side_effect=[run, block])
    db.scalar = AsyncMock(return_value=step)

    result = await reconcile_stuck_run(db, doc)

    assert result is True
    assert step.status == "FAILED"
    assert step.error_code == "TIMEOUT_EXCEEDED"
    assert "300" in step.error_message
    assert run.status == "FAILED"
    assert run.error_message == step.error_message
    assert doc.status == "FAILED"
    assert doc.error_message == step.error_message
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconcile_stuck_run_prefers_run_timeout_override_over_block_config():
    run = _run(status="RUNNING", timeout_overrides={"text_extract": 1200})
    doc = _doc(active_run_id=run.id)
    # 1000s elapsed: exceeds the block's own default (300s) but stays within
    # this run's 1200s override + grace — must NOT be marked failed.
    step = _step(started_at=datetime.utcnow() - timedelta(seconds=1000))
    block = _block("text_extract", config={"timeoutSeconds": 300})

    db = AsyncMock()
    db.get = AsyncMock(side_effect=[run, block])
    db.scalar = AsyncMock(return_value=step)

    assert await reconcile_stuck_run(db, doc) is False
    db.commit.assert_not_called()


def _impact_db(parent_run):
    """compute_reprocess_impact's calls beyond the status guard, wired to an
    empty graph (no upstream blocks) so only the guard itself is exercised."""
    db = AsyncMock()
    db.get = AsyncMock(return_value=parent_run)
    empty_result = MagicMock()
    empty_result.all.return_value = []
    db.scalars = AsyncMock(return_value=empty_result)
    db.scalar = AsyncMock(return_value=0)
    return db


@pytest.mark.asyncio
async def test_compute_reprocess_impact_allows_failed_parent_run():
    run = _run(status="FAILED")
    doc = _doc(active_run_id=run.id)
    start_block = _block("text_extract")
    start_block.id = uuid4()
    db = _impact_db(run)

    impact = await compute_reprocess_impact(db, doc, start_block)

    assert impact.parent_run is run


@pytest.mark.asyncio
async def test_compute_reprocess_impact_allows_completed_parent_run():
    run = _run(status="COMPLETED")
    doc = _doc(active_run_id=run.id)
    start_block = _block("text_extract")
    start_block.id = uuid4()
    db = _impact_db(run)

    impact = await compute_reprocess_impact(db, doc, start_block)

    assert impact.parent_run is run


@pytest.mark.asyncio
async def test_compute_reprocess_impact_still_blocks_running_parent_run():
    run = _run(status="RUNNING")
    doc = _doc(active_run_id=run.id)
    start_block = _block("text_extract")
    start_block.id = uuid4()
    db = _impact_db(run)

    with pytest.raises(ReprocessError):
        await compute_reprocess_impact(db, doc, start_block)


@pytest.mark.asyncio
async def test_start_partial_reprocess_carries_over_parent_skip_review():
    """새 run이 WorkflowRun.skip_review 컬럼 기본값(False)으로 조용히 되돌아가면
    "검토 없이 자동 진행"으로 업로드된 문서가 재처리할 때마다 예상 밖으로
    WAITING_REVIEW에 멈춘다 — 2026-07-27 test_data 15건 E2E 검증 중 실제로
    재현되어 발견한 회귀."""
    run = _run(status="COMPLETED")
    run.skip_review = True
    run.collection_id = uuid4()
    doc = _doc(active_run_id=run.id)
    start_block = _block("text_extract")
    start_block.id = uuid4()

    impact = ReprocessImpact(
        parent_run=run, upstream_blocks=[], parent_steps_by_block={}, impact={},
    )
    db = AsyncMock()
    db.add = MagicMock()

    with patch(
        "app.services.reprocess_service.compute_reprocess_impact",
        AsyncMock(return_value=impact),
    ), patch(
        "app.services.reprocess_service.current_dictionary_version",
        AsyncMock(return_value=1),
    ):
        await start_partial_reprocess(db, doc, start_block, reason=None)

    new_run = db.add.call_args[0][0]
    assert new_run.skip_review is True
