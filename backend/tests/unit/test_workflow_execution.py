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
from app.pipeline.tasks.workflow import (
    _advance,
    _evaluate_condition,
    _localize_error_message,
    run_workflow_step,
)


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
    target = MagicMock(id=target_id, block_type="postprocess", config={})

    db = _mock_db(edges=[edge], get_map={WorkflowBlockInstance: target})
    _advance(db, run_id, source, {"text": "hello"})

    # _advance dispatches via apply_async(time_limit=...) (per-block timeout,
    # not the old .delay()) — 1800 is the block-config-less default.
    mock_task.apply_async.assert_called_once_with(
        args=[run_id, str(target_id)], time_limit=1800, queue="normal",
    )


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
    true_target = MagicMock(id=true_target_id, block_type="postprocess", config={})

    db = _mock_db(edges=[true_edge, false_edge], get_map={WorkflowBlockInstance: true_target})
    _advance(db, run_id, source, {"is_valid": True})

    mock_task.apply_async.assert_called_once_with(
        args=[run_id, str(true_target_id)], time_limit=1800, queue="normal",
    )


@patch("app.pipeline.tasks.workflow.run_workflow_step")
def test_merge_waits_until_all_incoming_edges_complete(mock_task):
    run_id = str(uuid4())
    source = MagicMock(id=uuid4())
    merge_id = uuid4()
    edge = MagicMock(from_block_id=source.id, to_block_id=merge_id, condition=None)
    merge_block = MagicMock(id=merge_id, block_type="merge", config={})

    # merge has 2 incoming edges total; only 1 has completed so far (this one).
    existing_step = MagicMock(completed_incoming_edges=0)
    db = _mock_db(
        edges=[edge], edge_count=2, run_step_first=existing_step,
        get_map={WorkflowBlockInstance: merge_block},
    )
    _advance(db, run_id, source, {})

    assert existing_step.completed_incoming_edges == 1
    mock_task.apply_async.assert_not_called()


@patch("app.pipeline.tasks.workflow.run_workflow_step")
def test_merge_fires_once_last_incoming_edge_completes(mock_task):
    run_id = str(uuid4())
    source = MagicMock(id=uuid4())
    merge_id = uuid4()
    edge = MagicMock(from_block_id=source.id, to_block_id=merge_id, condition=None)
    merge_block = MagicMock(id=merge_id, block_type="merge", config={})

    # merge has 2 incoming edges total; 1 already completed before this call.
    existing_step = MagicMock(completed_incoming_edges=1)
    db = _mock_db(
        edges=[edge], edge_count=2, run_step_first=existing_step,
        get_map={WorkflowBlockInstance: merge_block},
    )
    _advance(db, run_id, source, {})

    assert existing_step.completed_incoming_edges == 2
    mock_task.apply_async.assert_called_once_with(
        args=[run_id, str(merge_id)], time_limit=1800, queue="normal",
    )


@patch("app.pipeline.tasks.workflow.run_workflow_step")
def test_advance_uses_run_timeout_override_over_block_config(mock_task):
    # A stuck run retried via reprocess_service.start_partial_reprocess carries
    # a per-run {block_type: timeoutSeconds} override (WorkflowRun.timeout_overrides)
    # that must win over the block's own persisted config.timeoutSeconds, without
    # mutating that shared config (other documents on the same workflow version
    # still use the block's default).
    run_id = str(uuid4())
    source = MagicMock(id=uuid4())
    target_id = uuid4()
    edge = MagicMock(from_block_id=source.id, to_block_id=target_id, condition=None)
    target = MagicMock(id=target_id, block_type="text_extract", config={"timeoutSeconds": 300})
    run = MagicMock(timeout_overrides={"text_extract": 1200})

    db = _mock_db(edges=[edge], get_map={WorkflowBlockInstance: target, WorkflowRun: run})
    _advance(db, run_id, source, {})

    mock_task.apply_async.assert_called_once_with(
        args=[run_id, str(target_id)], time_limit=1200, queue="normal",
    )


@patch("app.pipeline.tasks.workflow.run_workflow_step")
def test_advance_falls_back_to_block_config_when_no_override_for_block_type(mock_task):
    run_id = str(uuid4())
    source = MagicMock(id=uuid4())
    target_id = uuid4()
    edge = MagicMock(from_block_id=source.id, to_block_id=target_id, condition=None)
    target = MagicMock(id=target_id, block_type="text_extract", config={"timeoutSeconds": 300})
    # Override exists for this run, but not for this block's type.
    run = MagicMock(timeout_overrides={"structure_analyze": 1200})

    db = _mock_db(edges=[edge], get_map={WorkflowBlockInstance: target, WorkflowRun: run})
    _advance(db, run_id, source, {})

    mock_task.apply_async.assert_called_once_with(
        args=[run_id, str(target_id)], time_limit=300, queue="normal",
    )


def test_localize_error_message_maps_known_nul_byte_pattern_to_korean():
    exc = Exception(
        "This Session's transaction has been rolled back due to a previous "
        "exception during flush. Original exception was: A string literal "
        "cannot contain NUL (0x00) characters."
    )
    result = _localize_error_message(exc)
    assert "0x00" not in result
    assert "rolled back" not in result
    assert "문자" in result


def test_localize_error_message_passes_through_existing_korean_message():
    # BlockExecutionError raised by our own block code is almost always
    # already authored in Korean — must not be replaced with the generic
    # fallback (that would discard useful, specific detail).
    exc = Exception("지원하지 않는 파일 형식입니다: .xyz")
    assert _localize_error_message(exc) == "지원하지 않는 파일 형식입니다: .xyz"


def test_localize_error_message_falls_back_for_unrecognized_english_exception():
    # 알려진 패턴에도 없고 한글도 없는 예외는 사용자 안내 문구를 앞에 두되,
    # 워커 로그 유실 시에도 진단 가능하도록 예외 타입/원문을 덧붙여야 한다
    # (2026-07-29 classify 블록 실패 건 — 원본 예외가 로그에도 DB에도 전혀
    # 남지 않아 원인 파악이 불가능했던 회귀).
    exc = Exception("division by zero")
    result = _localize_error_message(exc)
    assert "오류" in result
    assert "Exception: division by zero" in result


def test_terminal_block_completes_run_when_nothing_else_pending():
    run_id = str(uuid4())
    source = MagicMock(id=uuid4())
    run = MagicMock(status="RUNNING")

    db = _mock_db(edges=[], run_step_count=0, get_map={WorkflowRun: run})
    _advance(db, run_id, source, {})

    assert run.status == "COMPLETED"
    assert run.completed_at is not None


def test_terminal_block_flips_failed_document_back_to_indexed_when_run_is_still_active():
    # A reprocess started on a FAILED document leaves doc.status literally
    # "FAILED" for the whole run if nothing else updates it in the meantime
    # (e.g. an analysis-tier start block with no _STATUS_FOR_BLOCK_TYPE
    # mapping). The completion guard must key off "is this still the
    # document's active run", not "doc.status != FAILED" — otherwise a
    # genuinely successful reprocess never flips the document back to
    # INDEXED (실측: 2026-08-03, documents 3bf3c8d4.../16e00066...).
    from app.db.models.document import Document

    run_id = str(uuid4())
    source = MagicMock(id=uuid4())
    run = MagicMock(id=run_id, status="RUNNING", document_id=uuid4())
    doc = MagicMock(status="FAILED", active_run_id=run_id)

    db = _mock_db(edges=[], run_step_count=0, get_map={WorkflowRun: run, Document: doc})
    _advance(db, run_id, source, {})

    assert run.status == "COMPLETED"
    assert doc.status == "INDEXED"


def test_terminal_block_does_not_flip_document_superseded_by_a_newer_run():
    # A stale run finishing late after a newer reprocess has already taken
    # over (active_run_id points elsewhere) must not resurrect a document
    # that the newer run may have already failed again.
    from app.db.models.document import Document

    run_id = str(uuid4())
    source = MagicMock(id=uuid4())
    run = MagicMock(id=run_id, status="RUNNING", document_id=uuid4())
    doc = MagicMock(status="FAILED", active_run_id=str(uuid4()))

    db = _mock_db(edges=[], run_step_count=0, get_map={WorkflowRun: run, Document: doc})
    _advance(db, run_id, source, {})

    assert run.status == "COMPLETED"
    assert doc.status == "FAILED"


def test_terminal_block_does_not_complete_run_when_others_still_pending():
    run_id = str(uuid4())
    source = MagicMock(id=uuid4())
    run = MagicMock(status="RUNNING")

    db = _mock_db(edges=[], run_step_count=1, get_map={WorkflowRun: run})
    _advance(db, run_id, source, {})

    assert run.status == "RUNNING"


@patch("app.db.session.get_sync_db")
def test_run_workflow_step_completes_run_on_duplicate_dispatch_dedup_path(mock_get_sync_db):
    # A block with 2+ incoming edges that isn't type "merge" gets dispatched
    # once per completed upstream edge — two concurrent executions of the
    # same block instance. Whichever finishes LAST is the only one that could
    # see every other step as done, but it may itself resolve to an
    # already-COMPLETED downstream step here (the dedup early-return) instead
    # of reaching _advance()'s own completion check. This regresses the
    # 2026-08-03 bug where every step was COMPLETED yet the run stayed
    # RUNNING forever — the dedup path must also confirm run completion.
    run_id = str(uuid4())
    block_id = uuid4()
    run = MagicMock(id=run_id, status="RUNNING", document_id=None)
    block = MagicMock(id=block_id, block_type="postprocess")
    already_completed_step = MagicMock(status="COMPLETED", output=None)

    db = MagicMock()

    def query_side_effect(model):
        q = MagicMock()
        if model is WorkflowRunStep:
            q.filter.return_value.first.return_value = already_completed_step
            q.filter.return_value.count.return_value = 0
        return q

    db.query.side_effect = query_side_effect
    db.get.side_effect = lambda model, _id: (
        run if model is WorkflowRun else block if model is WorkflowBlockInstance else None
    )
    mock_get_sync_db.return_value = db

    result = run_workflow_step(run_id, str(block_id))

    assert result == {"status": "COMPLETED", "output": {}}
    assert run.status == "COMPLETED"


def test_maybe_trigger_analysis_points_active_run_id_at_the_new_analysis_run():
    # Before this fix, _maybe_trigger_analysis set Document.status="ANALYZING"
    # but never updated Document.active_run_id — it kept pointing at the just-
    # completed PREPROCESS run. Any later lookup keyed off active_run_id (stuck-
    # run detection, reprocess, "which run is this document actually on")
    # inspected the wrong, already-finished run instead of the live analysis
    # run, silently going stale forever if that analysis run ever failed or
    # hung (실측: 2026-08-03, documents 17c08458.../92f34f36.../3bf3c8d4...).
    from app.db.models.collection import Collection
    from app.db.models.document import Document
    from app.db.models.workflow import (
        WorkflowBlockInstance,
        WorkflowDefinition,
        WorkflowEdge,
        WorkflowVersion,
    )
    from app.pipeline.tasks.workflow import _maybe_trigger_analysis

    stale_run_id = uuid4()
    parent_run = MagicMock(document_id=uuid4(), version_id=uuid4(), dictionary_version=1)
    version = MagicMock(workflow_id=uuid4())
    workflow_def = MagicMock(kind="PREPROCESS")
    document = MagicMock(
        id=parent_run.document_id, collection_id=uuid4(), active_run_id=stale_run_id,
    )
    collection = MagicMock(
        id=document.collection_id,
        default_analysis_workflow_id=uuid4(),
        default_analysis_workflow_version=None,
    )
    analysis_version = MagicMock(id=uuid4())

    db = MagicMock()

    def get_side_effect(model, _id):
        return {
            WorkflowVersion: version,
            WorkflowDefinition: workflow_def,
            Document: document,
            Collection: collection,
        }.get(model)

    db.get.side_effect = get_side_effect

    def query_side_effect(model):
        q = MagicMock()
        if model is WorkflowVersion:
            q.filter.return_value.filter.return_value.order_by.return_value.first.return_value = (
                analysis_version
            )
        elif model in (WorkflowBlockInstance, WorkflowEdge):
            q.filter.return_value.all.return_value = []
        return q

    db.query.side_effect = query_side_effect

    _maybe_trigger_analysis(db, parent_run)

    assert document.status == "ANALYZING"
    added_run = db.add.call_args[0][0]
    assert document.active_run_id == added_run.id
    assert document.active_run_id != stale_run_id


def test_fail_document_repoints_active_run_id_at_the_failed_run():
    # Same stale-active_run_id class of bug as _maybe_trigger_analysis above,
    # but on the failure path: if a document's active_run_id was ever left
    # pointing at an older, already-finished run, a later run failing on this
    # document must still repoint active_run_id at itself so reprocess/stuck-
    # detection look at the run that actually failed, not a stale one.
    from app.db.models.document import Document
    from app.pipeline.tasks.workflow import _fail_document

    stale_run_id = uuid4()
    run = MagicMock(id=uuid4(), document_id=uuid4())
    document = MagicMock(active_run_id=stale_run_id)

    db = MagicMock()
    db.get.side_effect = lambda model, _id: document if model is Document else None

    _fail_document(db, run, "처리 중 오류가 발생했습니다.")

    assert document.status == "FAILED"
    assert document.active_run_id == run.id
    assert document.active_run_id != stale_run_id
