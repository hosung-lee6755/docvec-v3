"""워크플로우 실행 API의 문서·컬렉션 접근 권한 (보안 리뷰 지적 사항).

워크플로우 편집 권한(프로젝트 editor)만 보고 실행 대상 문서/컬렉션의 접근 권한을 보지 않으면,
자기 워크플로우로 남의 문서를 실행해 `GET /runs/{id}`·`/export` 로 파싱 텍스트를 읽을 수 있다.
시스템 워크플로우의 실행 목록도 모든 사용자의 문서 파일명을 노출했다.
"""
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.v1.endpoints.workflows import runs as runs_api
from app.api.v1.endpoints.workflows.schemas import RunCreate
from app.db.models.document import Document
from app.db.models.workflow_run import WorkflowRun
from tests.unit.api_pg_helpers import (  # noqa: F401
    add_member,
    db_session,
    make_collection,
    make_document,
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


async def _run_count(db) -> int:
    return await db.scalar(select(func.count()).select_from(WorkflowRun))


@pytest.fixture
async def world(db_session):
    owner = await make_user(db_session, "editor", "owner")
    victim = await make_user(db_session, "viewer", "victim")
    project = await make_project(db_session, owner)
    workflow = await make_workflow(db_session, owner, project)
    version = await make_version(db_session, workflow, owner, 1, published=True)
    await make_valid_graph(db_session, version)
    own_collection = await make_collection(db_session, owner, project)
    # victim 의 개인 컬렉션: 프로젝트와 무관하고 owner 에게 공유되지 않았다.
    victim_collection = await make_collection(db_session, victim, None, name="private")
    victim_doc = await make_document(db_session, victim, victim_collection, parsed_text="비공개 본문")
    return dict(db=db_session, owner=owner, victim=victim, project=project, workflow=workflow,
                version=version, own_collection=own_collection, victim_collection=victim_collection,
                victim_doc=victim_doc)


@pytest.fixture
def dispatched():
    from app.pipeline.tasks import workflow as tasks

    with patch.object(tasks.run_workflow_step, "apply_async") as apply_async:
        yield MagicMock(apply_async=apply_async)


# ---------- POST /{workflow_id}/run ----------

@pytest.mark.asyncio
async def test_run_workflow_denies_another_users_document(world, dispatched):
    with pytest.raises(HTTPException) as exc:
        await runs_api.run_workflow(
            U(world["workflow"].id),
            RunCreate(version_id=U(world["version"].id), document_id=U(world["victim_doc"].id)),
            world["db"], world["owner"])

    assert exc.value.status_code == 403
    assert await _run_count(world["db"]) == 0
    dispatched.apply_async.assert_not_called()


@pytest.mark.asyncio
async def test_run_workflow_denies_another_users_collection(world, dispatched):
    with pytest.raises(HTTPException) as exc:
        await runs_api.run_workflow(
            U(world["workflow"].id),
            RunCreate(version_id=U(world["version"].id), collection_id=U(world["victim_collection"].id)),
            world["db"], world["owner"])

    assert exc.value.status_code == 403
    assert await _run_count(world["db"]) == 0
    dispatched.apply_async.assert_not_called()


@pytest.mark.asyncio
async def test_run_workflow_unknown_document_is_404_not_a_server_error(world, dispatched):
    with pytest.raises(HTTPException) as exc:
        await runs_api.run_workflow(
            U(world["workflow"].id),
            RunCreate(version_id=U(world["version"].id), document_id=uuid4()),
            world["db"], world["owner"])

    assert exc.value.status_code == 404
    dispatched.apply_async.assert_not_called()


@pytest.mark.asyncio
async def test_run_workflow_denies_a_member_only_collection_the_editor_is_not_in(world, dispatched):
    # 프로젝트 editor 라서 워크플로우는 실행할 수 있지만, 멤버 한정 컬렉션의 문서는 접근 권한이 없다.
    db = world["db"]
    editor = await make_user(db, "editor", "project-editor")
    await add_member(db, world["project"], editor, "editor", world["owner"])
    restricted = await make_collection(db, world["owner"], world["project"], name="hr", restrict_to_members=True)
    doc = await make_document(db, world["owner"], restricted, parsed_text="인사 자료")

    with pytest.raises(HTTPException) as exc:
        await runs_api.run_workflow(
            U(world["workflow"].id),
            RunCreate(version_id=U(world["version"].id), document_id=U(doc.id)),
            db, editor)

    assert exc.value.status_code == 403
    dispatched.apply_async.assert_not_called()


@pytest.mark.asyncio
async def test_run_workflow_allows_documents_other_members_uploaded_to_the_project(world, dispatched):
    db = world["db"]
    member = await make_user(db, "editor", "member")
    await add_member(db, world["project"], member, "editor", world["owner"])
    doc = await make_document(db, member, world["own_collection"], parsed_text="x")

    result = await runs_api.run_workflow(
        U(world["workflow"].id),
        RunCreate(version_id=U(world["version"].id), document_id=U(doc.id)),
        db, world["owner"])

    assert result["count"] == 1


# ---------- GET /{workflow_id}/runs (시스템 워크플로우) ----------

@pytest.fixture
async def system_world(world):
    db = world["db"]
    admin = await make_user(db, "admin", "admin")
    system_wf = await make_workflow(db, admin, None, kind="PREPROCESS", name="system")
    system_version = await make_version(db, system_wf, admin, 1, published=True)
    own_doc = await make_document(db, world["owner"], world["own_collection"], original_filename="mine.pdf")
    await _make_run(db, system_version, document_id=own_doc.id)
    await _make_run(db, system_version, document_id=world["victim_doc"].id)
    return dict(world, admin=admin, system_wf=system_wf)


@pytest.mark.asyncio
async def test_list_runs_of_system_workflow_hides_other_users_documents(system_world):
    result = await runs_api.list_runs(U(system_world["system_wf"].id), system_world["db"], system_world["owner"])

    assert [i["document_filename"] for i in result["items"]] == ["mine.pdf"]


@pytest.mark.asyncio
async def test_list_runs_of_system_workflow_shows_everything_to_admin(system_world):
    result = await runs_api.list_runs(U(system_world["system_wf"].id), system_world["db"], system_world["admin"])

    assert len(result["items"]) == 2


# ---------- POST /runs/{run_id}/cancel ----------

@pytest.mark.asyncio
async def test_cancel_run_does_not_overwrite_a_newer_runs_document_state(world):
    db = world["db"]
    doc = await make_document(db, world["owner"], world["own_collection"], status="ANALYZING")
    old_run = await _make_run(db, world["version"], "WAITING_REVIEW", document_id=doc.id)
    newer_run = await _make_run(db, world["version"], "RUNNING", document_id=doc.id)
    doc.active_run_id = newer_run.id
    await db.flush()

    await runs_api.cancel_run(U(old_run.id), db, world["owner"])

    saved = await db.scalar(select(Document).where(Document.id == doc.id))
    assert saved.status == "ANALYZING" and saved.error_message is None
    saved_old = await db.scalar(select(WorkflowRun).where(WorkflowRun.id == old_run.id))
    assert saved_old.status == "CANCELLED"
