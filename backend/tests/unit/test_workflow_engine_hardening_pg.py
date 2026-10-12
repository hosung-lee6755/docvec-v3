"""sweeper 재디스패치·완료 처리의 견고성 (코드 리뷰 지적 사항) — 실제 Postgres.

- 재디스패치는 유실된 대상만 다시 낸다: 이미 카운트된 merge 엣지를 다시 발화하면 merge 가 일찍 실행된다.
- 마지막 스텝이 끝난 직후 워커가 죽어 완료 처리가 유실돼도 run 이 RUNNING 에 영구히 남지 않는다.
- run 하나의 재디스패치 실패가 나머지 run 의 정리를 막지 않는다.
- 두 워커가 동시에 완료 처리해도 분석 run 이 중복 생성되지 않는다.
"""
from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models.workflow import WorkflowBlockInstance, WorkflowEdge
from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep
from app.pipeline.tasks.workflow import _maybe_complete_run
from tests.unit.test_workflow_engine_pg import (  # noqa: F401
    _completed_step,
    _pending_step,
    _sweep,
    graph,
    session_factory,
)


def _add_branch_block(session_factory, graph, source: str = "a") -> WorkflowBlockInstance:
    """source 블록에서 갈라지는 가지(c)를 하나 더 붙인다. c 는 아직 실행된 적이 없다."""
    db = session_factory()
    block = WorkflowBlockInstance(
        id=uuid4(), version_id=graph["version"].id, block_type="postprocess", config={},
    )
    db.add(block)
    db.flush()
    db.add(WorkflowEdge(
        id=uuid4(), version_id=graph["version"].id,
        from_block_id=graph["blocks"][source].id, to_block_id=block.id,
    ))
    db.commit()
    db.close()
    return block


def _merge_pending_with_counter(session_factory, graph, counter: int) -> None:
    step = _pending_step(session_factory, graph, "merge", created_ago=3600)
    db = session_factory()
    db.execute(update(WorkflowRunStep).where(WorkflowRunStep.id == step.id)
               .values(completed_incoming_edges=counter))
    db.commit()
    db.close()


def _merge_counter(session_factory, graph) -> int:
    db = session_factory()
    try:
        return db.scalar(select(WorkflowRunStep.completed_incoming_edges).where(
            WorkflowRunStep.run_id == graph["run"].id,
            WorkflowRunStep.block_instance_id == graph["blocks"]["merge"].id,
        ))
    finally:
        db.close()


def test_redispatch_only_advances_the_lost_branch_and_leaves_counted_merge_edges_alone(session_factory, graph):
    """a 의 완료는 이미 merge 에 1회 반영돼 있고(merge 는 b 를 더 기다린다), 다른 가지 c 만 유실됐다.
    a 의 모든 엣지를 다시 훑으면 merge 카운터가 2 가 돼 b 가 끝나기도 전에 merge 가 실행된다."""
    branch = _add_branch_block(session_factory, graph)
    _completed_step(session_factory, graph, "a", completed_ago=3600)
    _merge_pending_with_counter(session_factory, graph, counter=1)

    with patch("app.pipeline.tasks.workflow.run_workflow_step") as task:
        result = _sweep(session_factory)

    assert str(graph["run"].id) in result["redispatched_run_ids"]
    dispatched = [call.kwargs["args"][1] for call in task.apply_async.call_args_list]
    assert dispatched == [str(branch.id)]
    assert _merge_counter(session_factory, graph) == 1


def test_sweep_completes_a_run_whose_final_completion_was_lost(session_factory, graph):
    """모든 스텝이 COMPLETED 인데 마지막 스텝 직후 워커가 죽어 run 이 RUNNING 에 남은 경우."""
    for name in ("a", "b", "merge"):
        _completed_step(session_factory, graph, name, completed_ago=3600)

    with patch("app.pipeline.tasks.workflow._maybe_trigger_analysis"):
        result = _sweep(session_factory)

    db = session_factory()
    assert db.get(WorkflowRun, graph["run"].id).status == "COMPLETED"
    db.close()
    assert str(graph["run"].id) in result["redispatched_run_ids"]


def test_sweep_does_not_complete_a_recently_active_run(session_factory, graph):
    for name in ("a", "b", "merge"):
        _completed_step(session_factory, graph, name, completed_ago=5)

    with patch("app.pipeline.tasks.workflow._maybe_trigger_analysis"):
        _sweep(session_factory)

    db = session_factory()
    assert db.get(WorkflowRun, graph["run"].id).status == "RUNNING"
    db.close()


def test_one_failing_run_does_not_stop_the_sweep_of_other_runs(session_factory, graph):
    db = session_factory()
    other = WorkflowRun(id=uuid4(), version_id=graph["version"].id, status="RUNNING")
    db.add(other)
    db.commit()
    db.close()
    poisoned, healthy = str(graph["run"].id), str(other.id)

    def redispatch(_db, run):
        if str(run.id) == poisoned:
            raise RuntimeError("artifact 를 읽을 수 없습니다")
        return str(run.id) == healthy

    with patch("app.pipeline.tasks.workflow._redispatch_orphaned_run", side_effect=redispatch):
        result = _sweep(session_factory)

    assert healthy in result["redispatched_run_ids"]
    assert poisoned not in result["redispatched_run_ids"]


def test_maybe_complete_run_is_a_no_op_when_another_worker_already_completed_it(session_factory, graph):
    """두 워커가 모두 RUNNING 으로 읽은 뒤 완료하면 AUTO_ANALYSIS run 이 둘 생긴다. 상태 전이는
    `WHERE status='RUNNING'` 조건부 UPDATE 로 한 번만 일어나야 한다."""
    original_get = Session.get

    def get_then_lose_the_race(self, entity, ident, *args, **kwargs):
        obj = original_get(self, entity, ident, *args, **kwargs)
        if entity is WorkflowRun:
            other = session_factory()
            other.execute(update(WorkflowRun).where(WorkflowRun.id == ident)
                          .values(status="COMPLETED", completed_at=datetime.utcnow()))
            other.commit()
            other.close()
        return obj

    db = session_factory()
    with patch.object(Session, "get", get_then_lose_the_race), \
            patch("app.pipeline.tasks.workflow._maybe_trigger_analysis") as trigger:
        _maybe_complete_run(db, str(graph["run"].id))
    db.close()

    trigger.assert_not_called()
