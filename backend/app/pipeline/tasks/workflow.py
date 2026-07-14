"""DAG executor for user-defined workflows (app/db/models/workflow.py).

Unlike the fixed document pipeline (tasks/pipeline.py, a static Celery
chain()), a workflow graph can branch (조건분기) and merge (병합), so it is
walked one block at a time: each completed block resolves its own outgoing
WorkflowEdges and enqueues whatever comes next, rather than being composed
into one static chain up front.
"""
from datetime import datetime

from app.pipeline.blocks.base import BlockContext
from app.pipeline.blocks.registry import BLOCK_REGISTRY
from app.pipeline.celery_app import celery_app


def _evaluate_condition(condition: dict | None, output: dict) -> bool:
    if condition is None:
        return True
    return output.get(condition.get("output_field")) == condition.get("equals")


@celery_app.task(name="tasks.run_workflow_step", queue="normal", bind=True, max_retries=3)
def run_workflow_step(self, run_id: str, block_instance_id: str) -> dict:
    from app.db.models.workflow import WorkflowBlockInstance, WorkflowEdge
    from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep
    from app.db.session import get_sync_db

    db = get_sync_db()
    try:
        run = db.get(WorkflowRun, run_id)
        block = db.get(WorkflowBlockInstance, block_instance_id)
        if run is None or block is None:
            return {"status": "NOT_FOUND"}

        if run.status == "QUEUED":
            run.status = "RUNNING"
            run.started_at = datetime.utcnow()
            db.commit()

        step = db.query(WorkflowRunStep).filter(
            WorkflowRunStep.run_id == run_id,
            WorkflowRunStep.block_instance_id == block_instance_id,
        ).first()
        if step is None:
            step = WorkflowRunStep(run_id=run_id, block_instance_id=block_instance_id, status="PENDING")
            db.add(step)
            db.commit()
            db.refresh(step)

        incoming_edges = db.query(WorkflowEdge).filter(
            WorkflowEdge.to_block_id == block_instance_id
        ).all()
        upstream_steps = db.query(WorkflowRunStep).filter(
            WorkflowRunStep.run_id == run_id,
            WorkflowRunStep.block_instance_id.in_([e.from_block_id for e in incoming_edges]),
        ).all()
        upstream_outputs = {
            str(s.block_instance_id): (s.output or {}) for s in upstream_steps
        }

        step.status = "RUNNING"
        step.started_at = datetime.utcnow()
        db.commit()

        block_cls = BLOCK_REGISTRY[block.block_type]
        result = block_cls().run(BlockContext(
            run_id=run_id,
            block_instance_id=block_instance_id,
            upstream_outputs=upstream_outputs,
            config=block.config or {},
            document_id=str(run.document_id) if run.document_id else None,
            collection_id=str(run.collection_id) if run.collection_id else None,
        ))

        step.status = "COMPLETED"
        step.output = result.output
        step.completed_at = datetime.utcnow()
        db.commit()

        _advance(db, run_id, block, result.output)
        return {"status": "COMPLETED", "output": result.output}

    except Exception as exc:
        step = db.query(WorkflowRunStep).filter(
            WorkflowRunStep.run_id == run_id,
            WorkflowRunStep.block_instance_id == block_instance_id,
        ).first()
        if step is not None:
            step.status = "FAILED"
            step.error_message = str(exc)[:500]
            step.completed_at = datetime.utcnow()
        run = db.get(WorkflowRun, run_id)
        if run is not None:
            run.status = "FAILED"
            run.error_message = str(exc)[:500]
            run.completed_at = datetime.utcnow()
        db.commit()
        raise


def _advance(db, run_id: str, block, output: dict) -> None:
    """Resolve `block`'s outgoing edges and enqueue whatever should run next,
    or complete the run if `block` was terminal."""
    from app.db.models.workflow import WorkflowBlockInstance, WorkflowEdge
    from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep

    outgoing = db.query(WorkflowEdge).filter(WorkflowEdge.from_block_id == block.id).all()
    taken_edges = [e for e in outgoing if _evaluate_condition(e.condition, output)]

    for edge in taken_edges:
        target = db.get(WorkflowBlockInstance, edge.to_block_id)
        if target.block_type == "merge":
            incoming_to_target = db.query(WorkflowEdge).filter(
                WorkflowEdge.to_block_id == target.id
            ).count()
            target_step = db.query(WorkflowRunStep).filter(
                WorkflowRunStep.run_id == run_id,
                WorkflowRunStep.block_instance_id == target.id,
            ).first()
            if target_step is None:
                target_step = WorkflowRunStep(
                    run_id=run_id, block_instance_id=target.id, status="PENDING"
                )
                db.add(target_step)
            # `or 0`: the column default only lands on flush, so a freshly
            # constructed step still has None here.
            target_step.completed_incoming_edges = (target_step.completed_incoming_edges or 0) + 1
            db.commit()
            if target_step.completed_incoming_edges >= incoming_to_target:
                run_workflow_step.delay(run_id, str(target.id))
        else:
            run_workflow_step.delay(run_id, str(target.id))

    if not taken_edges:
        # Terminal block for this branch. If no other step in the run is still
        # pending/running, the whole run is done.
        unfinished = db.query(WorkflowRunStep).filter(
            WorkflowRunStep.run_id == run_id,
            WorkflowRunStep.status.in_(["PENDING", "RUNNING"]),
        ).count()
        if unfinished == 0:
            run = db.get(WorkflowRun, run_id)
            run.status = "COMPLETED"
            run.completed_at = datetime.utcnow()
            db.commit()
