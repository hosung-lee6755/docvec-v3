"""다른 프로젝트의 컬렉션으로 옮긴 문서의 재처리(2026-11-20 사용자 결정).

프로젝트 워크플로우는 같은 프로젝트의 컬렉션과 문서에만 쓴다. 문서를 다른 프로젝트의 컬렉션으로 옮긴 뒤
"처음부터 다시 처리"하면 예전 프로젝트의 워크플로우가 아니라, 지금 컬렉션의 기본 워크플로우(없으면 표준
전처리)로 처리한다. 예전 실행의 단계를 이어 쓰는 블록부터 재처리는 예전 워크플로우를 그대로 써야 하므로 막는다.
"""
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.db.models.workflow_run import WorkflowRun
from app.services import reprocess_service as rs
from tests.unit.api_pg_helpers import (  # noqa: F401
    db_session,
    make_block,
    make_collection,
    make_document,
    make_project,
    make_user,
    make_version,
    make_workflow,
)


async def _published(db, owner, project, name):
    workflow = await make_workflow(db, owner, project, kind="PREPROCESS", name=name)
    version = await make_version(db, workflow, owner, 1, published=True)
    block = await make_block(db, version, "file_validate", label=f"{name}-entry")
    return version, block


@pytest.fixture
async def moved(db_session):
    db = db_session
    owner = await make_user(db, "editor", "owner")
    old_project = await make_project(db, owner, "옛 프로젝트")
    new_project = await make_project(db, owner, "새 프로젝트")
    old_version, old_block = await _published(db, owner, old_project, "old")
    system_version, _ = await _published(db, owner, None, "system")
    collection = await make_collection(db, owner, new_project, name="new-home")
    doc = await make_document(db, owner, collection)
    run = WorkflowRun(
        id=uuid4(), version_id=old_version.id, document_id=doc.id, status="COMPLETED", trigger="UPLOAD",
    )
    db.add(run)
    await db.flush()
    doc.active_run_id = run.id
    await db.flush()
    return dict(db=db, doc=doc, old_block=old_block, system_version=system_version)


@pytest.mark.asyncio
async def test_full_reprocess_of_a_moved_document_uses_the_current_collections_workflow(moved):
    with patch("app.pipeline.tasks.workflow.run_workflow_step.apply_async"):
        run = await rs.start_reprocess_on_latest_version(moved["db"], moved["doc"], reason="이동 뒤 재처리")

    assert str(run.version_id) == str(moved["system_version"].id)
    assert str(run.collection_id) == str(moved["doc"].collection_id)


@pytest.mark.asyncio
async def test_partial_reprocess_with_another_projects_workflow_is_refused(moved):
    with patch("app.pipeline.tasks.workflow.run_workflow_step.apply_async"), \
            pytest.raises(rs.ReprocessError) as exc:
        await rs.start_partial_reprocess(moved["db"], moved["doc"], moved["old_block"], reason=None)

    assert "옛 프로젝트" in str(exc.value)
