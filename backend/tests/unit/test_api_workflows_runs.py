"""워크플로우 실행(runs) 엔드포인트와 check_run_access 테스트 — 실제 Postgres(SAVEPOINT 롤백).

Celery 디스패치(`apply_async`/`delay`)는 가짜로 대체한다. 모델·GPU·네트워크는 쓰지 않는다.
"""
import json
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.v1.endpoints.workflows import runs as runs_api
from app.api.v1.endpoints.workflows.access import check_run_access
from app.api.v1.endpoints.workflows.schemas import RunCreate
from app.db.models.document import Document
from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep
from tests.unit.api_pg_helpers import (  # noqa: F401
    add_member,
    db_session,
    make_block,
    make_collection,
    make_document,
    make_edge,
    make_project,
    make_user,
    make_valid_graph,
    make_version,
    make_workflow,
)


def U(value) -> UUID:
    return UUID(str(value))


async def _make_run(db, version, status="COMPLETED", **fields) -> WorkflowRun:
    run = WorkflowRun(id=str(uuid4()), version_id=str(version.id), status=status, **fields)
    db.add(run)
    await db.flush()
    return run


async def _count(db, model, *where) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(*where))


@pytest.fixture
async def world(db_session):
    owner = await make_user(db_session, "editor", "owner")
    stranger = await make_user(db_session, "viewer", "stranger")
    project = await make_project(db_session, owner)
    workflow = await make_workflow(db_session, owner, project)
    version = await make_version(db_session, workflow, owner, 1, published=True)
    source, sink = await make_valid_graph(db_session, version)
    collection = await make_collection(db_session, owner, project)
    return dict(db=db_session, owner=owner, stranger=stranger, project=project, workflow=workflow,
                version=version, source=source, sink=sink, collection=collection)


@pytest.fixture
def dispatched():
    """run_workflow_step.apply_async / resume_workflow_run.delay 호출을 기록한다."""
    from app.pipeline.tasks import workflow as tasks

    with patch.object(tasks.run_workflow_step, "apply_async") as apply_async, \
            patch.object(tasks.resume_workflow_run, "delay") as delay:
        yield MagicMock(apply_async=apply_async, delay=delay)


# ---------- run_workflow ----------

@pytest.mark.asyncio
async def test_run_workflow_for_document_creates_queued_run_and_dispatches_entry_block(world, dispatched):
    db = world["db"]
    doc = await make_document(db, world["owner"], world["collection"])

    result = await runs_api.run_workflow(
        U(world["workflow"].id), RunCreate(version_id=U(world["version"].id), document_id=U(doc.id)),
        db, world["owner"])

    assert result["count"] == 1
    assert result["items"][0].status == "QUEUED"
    run = (await db.scalars(select(WorkflowRun).where(WorkflowRun.version_id == world["version"].id))).one()
    assert str(run.document_id) == str(doc.id)
    # 진입 블록(input)만 디스패치, 큐는 normal, 타임아웃 기본 1800초
    dispatched.apply_async.assert_called_once()
    kwargs = dispatched.apply_async.call_args.kwargs
    assert kwargs["args"] == [str(run.id), str(world["source"].id)]
    assert kwargs["queue"] == "normal" and kwargs["time_limit"] == 1800


@pytest.mark.asyncio
async def test_run_workflow_points_the_document_at_the_new_run(world, dispatched):
    """수동 실행도 업로드·재처리처럼 문서의 active_run_id를 새 run으로 옮겨야 한다. 그대로 두면
    품질 보고서, 검토/실패 대기열, 부분 재처리가 이미 청크가 지워진 옛 run을 기준으로 삼는다."""
    db = world["db"]
    doc = await make_document(db, world["owner"], world["collection"])
    old = await _make_run(db, world["version"], status="COMPLETED", document_id=str(doc.id))
    doc.active_run_id = old.id
    await db.flush()

    result = await runs_api.run_workflow(
        U(world["workflow"].id), RunCreate(version_id=U(world["version"].id), document_id=U(doc.id)),
        db, world["owner"])

    await db.refresh(doc)
    assert str(doc.active_run_id) == str(result["items"][0].id)


@pytest.mark.asyncio
async def test_run_workflow_rejects_a_document_that_is_still_processing(world, dispatched):
    db = world["db"]
    doc = await make_document(db, world["owner"], world["collection"])
    live = await _make_run(db, world["version"], status="RUNNING", document_id=str(doc.id))
    doc.active_run_id = live.id
    await db.flush()

    with pytest.raises(HTTPException) as exc:
        await runs_api.run_workflow(
            U(world["workflow"].id), RunCreate(version_id=U(world["version"].id), document_id=U(doc.id)),
            db, world["owner"])

    assert exc.value.status_code == 409
    assert "처리 중" in exc.value.detail
    dispatched.apply_async.assert_not_called()


@pytest.mark.asyncio
async def test_run_workflow_for_collection_skips_documents_that_are_still_processing(world, dispatched):
    db = world["db"]
    idle = await make_document(db, world["owner"], world["collection"], parsed_text="a")
    busy = await make_document(db, world["owner"], world["collection"], parsed_text="b")
    live = await _make_run(db, world["version"], status="WAITING_REVIEW", document_id=str(busy.id))
    busy.active_run_id = live.id
    await db.flush()

    result = await runs_api.run_workflow(
        U(world["workflow"].id),
        RunCreate(version_id=U(world["version"].id), collection_id=U(world["collection"].id)),
        db, world["owner"])

    assert result["count"] == 1
    assert result["skipped_in_progress"] == 1
    await db.refresh(busy)
    assert str(busy.active_run_id) == str(live.id)
    await db.refresh(idle)
    assert str(idle.active_run_id) == str(result["items"][0].id)


@pytest.mark.asyncio
async def test_run_workflow_uses_block_timeout_config(world, dispatched):
    db = world["db"]
    world["source"].config = {"timeoutSeconds": 42}
    await db.flush()
    doc = await make_document(db, world["owner"], world["collection"])

    await runs_api.run_workflow(
        U(world["workflow"].id), RunCreate(version_id=U(world["version"].id), document_id=U(doc.id)),
        db, world["owner"])

    assert dispatched.apply_async.call_args.kwargs["time_limit"] == 42


@pytest.mark.asyncio
async def test_run_workflow_for_collection_fans_out_only_parsed_documents(world, dispatched):
    db = world["db"]
    await make_document(db, world["owner"], world["collection"], parsed_text="a")
    await make_document(db, world["owner"], world["collection"], parsed_text="b")
    await make_document(db, world["owner"], world["collection"], parsed_text=None)

    result = await runs_api.run_workflow(
        U(world["workflow"].id),
        RunCreate(version_id=U(world["version"].id), collection_id=U(world["collection"].id)),
        db, world["owner"])

    assert result["count"] == 2
    assert dispatched.apply_async.call_count == 2


@pytest.mark.asyncio
async def test_run_workflow_collection_without_parsed_documents_is_409(world, dispatched):
    await make_document(world["db"], world["owner"], world["collection"], parsed_text=None)
    with pytest.raises(HTTPException) as exc:
        await runs_api.run_workflow(
            U(world["workflow"].id),
            RunCreate(version_id=U(world["version"].id), collection_id=U(world["collection"].id)),
            world["db"], world["owner"])
    assert exc.value.status_code == 409
    dispatched.apply_async.assert_not_called()


@pytest.mark.asyncio
async def test_run_workflow_rejects_unpublished_version(world, dispatched):
    draft = await make_version(world["db"], world["workflow"], world["owner"], 2)
    with pytest.raises(HTTPException) as exc:
        await runs_api.run_workflow(
            U(world["workflow"].id), RunCreate(version_id=U(draft.id), document_id=uuid4()),
            world["db"], world["owner"])
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_run_workflow_requires_a_target(world, dispatched):
    with pytest.raises(HTTPException) as exc:
        await runs_api.run_workflow(
            U(world["workflow"].id), RunCreate(version_id=U(world["version"].id)),
            world["db"], world["owner"])
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_run_workflow_rejects_invalid_graph(world, dispatched):
    db = world["db"]
    broken = await make_version(db, world["workflow"], world["owner"], 2, published=True)  # 블록 없음
    with pytest.raises(HTTPException) as exc:
        await runs_api.run_workflow(
            U(world["workflow"].id), RunCreate(version_id=U(broken.id), document_id=uuid4()),
            db, world["owner"])
    assert exc.value.status_code == 409
    assert exc.value.detail["errors"]


@pytest.mark.asyncio
async def test_run_workflow_denies_stranger(world, dispatched):
    with pytest.raises(HTTPException) as exc:
        await runs_api.run_workflow(
            U(world["workflow"].id),
            RunCreate(version_id=U(world["version"].id), document_id=uuid4()),
            world["db"], world["stranger"])
    assert exc.value.status_code == 403


# ---------- list_runs ----------

@pytest.mark.asyncio
async def test_list_runs_returns_version_number_and_document_filename(world):
    db = world["db"]
    doc = await make_document(db, world["owner"], world["collection"], original_filename="보고서.pdf")
    await _make_run(db, world["version"], document_id=doc.id)
    await _make_run(db, world["version"], collection_id=world["collection"].id)

    result = await runs_api.list_runs(U(world["workflow"].id), db, world["owner"])

    items = result["items"]
    assert len(items) == 2
    assert {i["version_number"] for i in items} == {1}
    assert {i["document_filename"] for i in items} == {"보고서.pdf", None}


@pytest.mark.asyncio
async def test_list_runs_empty_for_workflow_without_runs(world):
    result = await runs_api.list_runs(U(world["workflow"].id), world["db"], world["owner"])
    assert result == {"items": []}


# ---------- delete_run ----------

@pytest.mark.asyncio
async def test_delete_run_removes_run_and_steps(world):
    db = world["db"]
    run = await _make_run(db, world["version"], "COMPLETED")
    db.add(WorkflowRunStep(run_id=run.id, block_instance_id=world["source"].id, status="COMPLETED"))
    await db.flush()

    result = await runs_api.delete_run(U(run.id), db, world["owner"])

    assert result == {"deleted": True}
    assert await _count(db, WorkflowRun, WorkflowRun.id == run.id) == 0
    assert await _count(db, WorkflowRunStep, WorkflowRunStep.run_id == run.id) == 0


@pytest.mark.parametrize("status", ["QUEUED", "RUNNING"])
@pytest.mark.asyncio
async def test_delete_run_protects_active_runs(world, status):
    run = await _make_run(world["db"], world["version"], status)
    with pytest.raises(HTTPException) as exc:
        await runs_api.delete_run(U(run.id), world["db"], world["owner"])
    assert exc.value.status_code == 409
    assert await _count(world["db"], WorkflowRun, WorkflowRun.id == run.id) == 1


@pytest.mark.asyncio
async def test_delete_run_404_for_unknown_run(world):
    with pytest.raises(HTTPException) as exc:
        await runs_api.delete_run(uuid4(), world["db"], world["owner"])
    assert exc.value.status_code == 404


# ---------- resume / cancel ----------

@pytest.mark.asyncio
async def test_resume_run_queues_task_when_waiting_review(world, dispatched):
    run = await _make_run(world["db"], world["version"], "WAITING_REVIEW")
    result = await runs_api.resume_run(U(run.id), world["db"], world["owner"])
    assert result == {"status": "RESUME_QUEUED"}
    dispatched.delay.assert_called_once_with(str(U(run.id)))


@pytest.mark.asyncio
async def test_resume_run_rejects_other_status(world, dispatched):
    run = await _make_run(world["db"], world["version"], "COMPLETED")
    with pytest.raises(HTTPException) as exc:
        await runs_api.resume_run(U(run.id), world["db"], world["owner"])
    assert exc.value.status_code == 409
    dispatched.delay.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_run_marks_run_cancelled_and_document_failed(world):
    db = world["db"]
    doc = await make_document(db, world["owner"], world["collection"], status="ANALYZING")
    run = await _make_run(db, world["version"], "WAITING_REVIEW", document_id=doc.id)

    result = await runs_api.cancel_run(U(run.id), db, world["owner"])

    assert result == {"status": "CANCELLED"}
    saved_run = await db.scalar(select(WorkflowRun).where(WorkflowRun.id == run.id))
    saved_doc = await db.scalar(select(Document).where(Document.id == doc.id))
    assert saved_run.status == "CANCELLED" and saved_run.completed_at is not None
    assert saved_doc.status == "FAILED" and "반려" in saved_doc.error_message


@pytest.mark.asyncio
async def test_cancel_run_without_document_only_cancels_run(world):
    run = await _make_run(world["db"], world["version"], "RUNNING")
    assert await runs_api.cancel_run(U(run.id), world["db"], world["owner"]) == {"status": "CANCELLED"}


@pytest.mark.asyncio
async def test_cancel_run_rejects_finished_run(world):
    run = await _make_run(world["db"], world["version"], "COMPLETED")
    with pytest.raises(HTTPException) as exc:
        await runs_api.cancel_run(U(run.id), world["db"], world["owner"])
    assert exc.value.status_code == 409


# ---------- export / get ----------

@pytest.mark.asyncio
async def test_export_run_returns_json_attachment_with_output_block_result(world):
    db = world["db"]
    run = await _make_run(db, world["version"], "COMPLETED", document_id=None)
    db.add(WorkflowRunStep(run_id=run.id, block_instance_id=world["source"].id,
                           status="COMPLETED", output={"text": "in"}))
    db.add(WorkflowRunStep(run_id=run.id, block_instance_id=world["sink"].id,
                           status="COMPLETED", output={"answer": 42}))
    unlabeled = await make_block(db, world["version"], "summarize")
    db.add(WorkflowRunStep(run_id=run.id, block_instance_id=unlabeled.id,
                           status="FAILED", error_message="x"))
    await db.flush()

    response = await runs_api.export_run(U(run.id), db, world["owner"])

    assert response.headers["content-disposition"] == f'attachment; filename="workflow-run-{U(run.id)}.json"'
    payload = json.loads(response.body)
    assert payload["result"] == {"answer": 42}  # COMPLETED output 블록 1개 → 단일 객체
    assert payload["workflow"] == "wf" and payload["version_number"] == 1
    assert {s["block"] for s in payload["steps"]} == {"in", "out", "summarize"}  # 라벨 없으면 타입명
    assert payload["document_id"] is None and payload["started_at"] is None


@pytest.mark.asyncio
async def test_export_run_without_output_steps_returns_empty_list_result(world):
    run = await _make_run(world["db"], world["version"], "FAILED")
    response = await runs_api.export_run(U(run.id), world["db"], world["owner"])
    payload = json.loads(response.body)
    assert payload["result"] == [] and payload["steps"] == []


@pytest.mark.asyncio
async def test_get_run_returns_run_and_step_display_with_labels(world):
    db = world["db"]
    unlabeled = await make_block(db, world["version"], "summarize")
    run = await _make_run(db, world["version"], "COMPLETED")
    db.add(WorkflowRunStep(run_id=run.id, block_instance_id=world["source"].id, status="COMPLETED",
                           output={"a": 1}, cached=True))
    db.add(WorkflowRunStep(run_id=run.id, block_instance_id=unlabeled.id, status="FAILED",
                           error_message="boom"))
    await db.flush()

    result = await runs_api.get_run(U(run.id), db, world["owner"])

    assert result["run"].status == "COMPLETED"
    steps = {s["block_type"]: s for s in result["steps"]}
    assert steps["input"]["label"] == "in" and steps["input"]["cached"] is True
    assert steps["summarize"]["label"]  # 라벨 없으면 블록 타입 한글명으로 대체
    assert steps["summarize"]["error_message"] == "boom"


@pytest.mark.asyncio
async def test_get_run_404_for_unknown_run(world):
    with pytest.raises(HTTPException) as exc:
        await runs_api.get_run(uuid4(), world["db"], world["owner"])
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_run_denied_for_non_member(world):
    run = await _make_run(world["db"], world["version"])
    with pytest.raises(HTTPException) as exc:
        await runs_api.get_run(U(run.id), world["db"], world["stranger"])
    assert exc.value.status_code == 403


# ---------- check_run_access (시스템 워크플로우: project_id=None) ----------

@pytest.fixture
async def system_world(db_session):
    owner = await make_user(db_session, "editor")
    stranger = await make_user(db_session, "viewer")
    workflow = await make_workflow(db_session, owner, None, kind="PREPROCESS", name="sys")
    version = await make_version(db_session, workflow, owner, 1, published=True)
    return dict(db=db_session, owner=owner, stranger=stranger, workflow=workflow, version=version)


@pytest.mark.asyncio
async def test_check_run_access_system_workflow_uses_document_access(system_world):
    w = system_world
    collection = await make_collection(w["db"], w["owner"])
    doc = await make_document(w["db"], w["owner"], collection)
    run = await _make_run(w["db"], w["version"], document_id=doc.id)

    await check_run_access(w["db"], w["workflow"], run, w["owner"], "editor")  # 문서 소유자
    with pytest.raises(HTTPException) as exc:
        await check_run_access(w["db"], w["workflow"], run, w["stranger"], "viewer")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_check_run_access_system_workflow_missing_document_is_404(system_world):
    w = system_world
    run = MagicMock(document_id=uuid4(), collection_id=None)
    with pytest.raises(HTTPException) as exc:
        await check_run_access(w["db"], w["workflow"], run, w["owner"], "viewer")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_check_run_access_system_workflow_falls_back_to_collection(system_world):
    w = system_world
    collection = await make_collection(w["db"], w["owner"])
    run = await _make_run(w["db"], w["version"], collection_id=collection.id)

    await check_run_access(w["db"], w["workflow"], run, w["owner"], "viewer")
    with pytest.raises(HTTPException) as exc:
        await check_run_access(w["db"], w["workflow"], run, w["stranger"], "viewer")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_run_whose_document_was_deleted_is_admin_only_and_hidden_from_others(system_world):
    # 문서를 지우면 실행의 document_id가 비어 대상이 남지 않는다. 관리자는 기록을 열 수 있어야 하고,
    # 다른 사용자에게는 기록이 있다는 사실도 드러내지 않는다(목록에서도 보이지 않는다).
    w = system_world
    admin = await make_user(w["db"], "admin")
    run = await _make_run(w["db"], w["version"])

    await check_run_access(w["db"], w["workflow"], run, admin, "viewer")
    with pytest.raises(HTTPException) as exc:
        await check_run_access(w["db"], w["workflow"], run, w["owner"], "viewer")
    assert exc.value.status_code == 404
