"""Regression coverage for sweep_stuck_workflow_runs (app/pipeline/tasks/workflow.py)
— the Celery-beat-driven counterpart to reprocess_service.reconcile_stuck_run
that clears a RUNNING run stuck behind a SIGKILLed Celery hard time_limit even
if nobody ever opens the document detail page (2026-07-30). Uses a mocked sync
Session, same convention as test_workflow_execution.py, since Celery tasks in
this codebase use sync SQLAlchemy sessions."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.db.models.document import Document
from app.db.models.workflow import WorkflowBlockInstance
from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep
from app.pipeline.tasks.workflow import sweep_stuck_workflow_runs


def _mock_db(running_runs, stuck_step=None, block=None, document=None):
    db = MagicMock()

    def query_side_effect(model):
        q = MagicMock()
        if model is WorkflowRun:
            q.filter.return_value.all.return_value = running_runs
        elif model is WorkflowRunStep:
            q.filter.return_value.first.return_value = stuck_step
        return q

    db.query.side_effect = query_side_effect
    db.get.side_effect = lambda model, _id: (
        block if model is WorkflowBlockInstance else document if model is Document else None
    )
    return db


def test_sweep_returns_empty_when_no_running_runs():
    db = _mock_db(running_runs=[])

    with patch("app.db.session.get_sync_db", return_value=db):
        result = sweep_stuck_workflow_runs()

    assert result == {"swept_run_ids": []}
    db.commit.assert_not_called()
    db.close.assert_called_once()


def test_sweep_skips_run_within_timeout_and_grace():
    run = MagicMock(id=uuid4(), timeout_overrides=None, document_id=uuid4())
    step = MagicMock(started_at=datetime.utcnow() - timedelta(seconds=100), status="RUNNING")
    block = MagicMock(block_type="text_extract", config={"timeoutSeconds": 300})
    db = _mock_db(running_runs=[run], stuck_step=step, block=block)

    with patch("app.db.session.get_sync_db", return_value=db):
        result = sweep_stuck_workflow_runs()

    assert result == {"swept_run_ids": []}
    assert step.status == "RUNNING"
    db.commit.assert_not_called()


def test_sweep_fails_run_past_timeout_and_grace():
    run_id = uuid4()
    run = MagicMock(id=run_id, timeout_overrides=None, document_id=uuid4())
    step = MagicMock(started_at=datetime.utcnow() - timedelta(seconds=400), status="RUNNING")
    block = MagicMock(block_type="text_extract", config={"timeoutSeconds": 300})
    document = MagicMock(status="PARSING")
    db = _mock_db(running_runs=[run], stuck_step=step, block=block, document=document)

    with patch("app.db.session.get_sync_db", return_value=db):
        result = sweep_stuck_workflow_runs()

    assert result == {"swept_run_ids": [str(run_id)]}
    assert step.status == "FAILED"
    assert step.error_code == "TIMEOUT_EXCEEDED"
    assert run.status == "FAILED"
    assert document.status == "FAILED"
    db.commit.assert_called_once()


def test_sweep_honors_per_run_timeout_override():
    """timeout_overrides로 개별 run이 늘려둔 제한 시간은 블록 기본값(300초)보다
    우선해야 한다 — 1000초 경과는 기본값 기준으로는 초과지만 1200초 오버라이드
    + grace 안에는 들어온다."""
    run = MagicMock(id=uuid4(), timeout_overrides={"text_extract": 1200}, document_id=uuid4())
    step = MagicMock(started_at=datetime.utcnow() - timedelta(seconds=1000), status="RUNNING")
    block = MagicMock(block_type="text_extract", config={"timeoutSeconds": 300})
    db = _mock_db(running_runs=[run], stuck_step=step, block=block)

    with patch("app.db.session.get_sync_db", return_value=db):
        result = sweep_stuck_workflow_runs()

    assert result == {"swept_run_ids": []}
    db.commit.assert_not_called()
