"""Unit coverage for the workflow DAG executor's dispatch logic
(app/pipeline/tasks/workflow.py) — linear, branch, and merge cases. The
executor's `db` argument is a sync SQLAlchemy Session (Celery tasks use sync
sessions, unlike the async API layer) — mocked here per-model via
`db.query(Model)` so each test controls exactly what "the DB" returns
without needing a live Postgres connection."""
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.db.models.workflow import WorkflowBlockInstance, WorkflowEdge
from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep
from app.pipeline.tasks.workflow import _advance, _evaluate_condition


def test_evaluate_condition_none_is_always_true():
    assert _evaluate_condition(None, {"anything": "goes"}) is True


def test_evaluate_condition_matches_field_value():
    condition = {"output_field": "is_valid", "equals": True}
    assert _evaluate_condition(condition, {"is_valid": True}) is True
    assert _evaluate_condition(condition, {"is_valid": False}) is False


def _mock_db(*, edges=None, edge_count=0, run_step_first=None, run_step_count=0, get_map=None):
    db = MagicMock()

    edge_query = MagicMock()
    edge_query.filter.return_value.all.return_value = edges or []
    edge_query.filter.return_value.count.return_value = edge_count

    run_step_query = MagicMock()
    run_step_query.filter.return_value.first.return_value = run_step_first
    run_step_query.filter.return_value.count.return_value = run_step_count

    def query_side_effect(model):
        if model is WorkflowEdge:
            return edge_query
        if model is WorkflowRunStep:
            return run_step_query
        return MagicMock()

    db.query.side_effect = query_side_effect
    db.get.side_effect = lambda model, _id: (get_map or {}).get(model)
    return db


@patch("app.pipeline.tasks.workflow.run_workflow_step")
def test_linear_unconditional_edge_enqueues_next_block(mock_task):
    run_id = str(uuid4())
    source = MagicMock(id=uuid4())
    target_id = uuid4()
    edge = MagicMock(from_block_id=source.id, to_block_id=target_id, condition=None)
    target = MagicMock(id=target_id, block_type="postprocess")

    db = _mock_db(edges=[edge], get_map={WorkflowBlockInstance: target})
    _advance(db, run_id, source, {"text": "hello"})

    mock_task.delay.assert_called_once_with(run_id, str(target_id))


@patch("app.pipeline.tasks.workflow.run_workflow_step")
def test_branch_only_true_edge_fires(mock_task):
    run_id = str(uuid4())
    source = MagicMock(id=uuid4())
    true_target_id, false_target_id = uuid4(), uuid4()
    true_edge = MagicMock(
        from_block_id=source.id, to_block_id=true_target_id,
        condition={"output_field": "is_valid", "equals": True},
    )
    false_edge = MagicMock(
        from_block_id=source.id, to_block_id=false_target_id,
        condition={"output_field": "is_valid", "equals": False},
    )
    true_target = MagicMock(id=true_target_id, block_type="postprocess")

    db = _mock_db(edges=[true_edge, false_edge], get_map={WorkflowBlockInstance: true_target})
    _advance(db, run_id, source, {"is_valid": True})

    mock_task.delay.assert_called_once_with(run_id, str(true_target_id))


@patch("app.pipeline.tasks.workflow.run_workflow_step")
def test_merge_waits_until_all_incoming_edges_complete(mock_task):
    run_id = str(uuid4())
    source = MagicMock(id=uuid4())
    merge_id = uuid4()
    edge = MagicMock(from_block_id=source.id, to_block_id=merge_id, condition=None)
    merge_block = MagicMock(id=merge_id, block_type="merge")

    # merge has 2 incoming edges total; only 1 has completed so far (this one).
    existing_step = MagicMock(completed_incoming_edges=0)
    db = _mock_db(
        edges=[edge], edge_count=2, run_step_first=existing_step,
        get_map={WorkflowBlockInstance: merge_block},
    )
    _advance(db, run_id, source, {})

    assert existing_step.completed_incoming_edges == 1
    mock_task.delay.assert_not_called()


@patch("app.pipeline.tasks.workflow.run_workflow_step")
def test_merge_fires_once_last_incoming_edge_completes(mock_task):
    run_id = str(uuid4())
    source = MagicMock(id=uuid4())
    merge_id = uuid4()
    edge = MagicMock(from_block_id=source.id, to_block_id=merge_id, condition=None)
    merge_block = MagicMock(id=merge_id, block_type="merge")

    # merge has 2 incoming edges total; 1 already completed before this call.
    existing_step = MagicMock(completed_incoming_edges=1)
    db = _mock_db(
        edges=[edge], edge_count=2, run_step_first=existing_step,
        get_map={WorkflowBlockInstance: merge_block},
    )
    _advance(db, run_id, source, {})

    assert existing_step.completed_incoming_edges == 2
    mock_task.delay.assert_called_once_with(run_id, str(merge_id))


def test_terminal_block_completes_run_when_nothing_else_pending():
    run_id = str(uuid4())
    source = MagicMock(id=uuid4())
    run = MagicMock(status="RUNNING")

    db = _mock_db(edges=[], run_step_count=0, get_map={WorkflowRun: run})
    _advance(db, run_id, source, {})

    assert run.status == "COMPLETED"
    assert run.completed_at is not None


def test_terminal_block_does_not_complete_run_when_others_still_pending():
    run_id = str(uuid4())
    source = MagicMock(id=uuid4())
    run = MagicMock(status="RUNNING")

    db = _mock_db(edges=[], run_step_count=1, get_map={WorkflowRun: run})
    _advance(db, run_id, source, {})

    assert run.status == "RUNNING"
