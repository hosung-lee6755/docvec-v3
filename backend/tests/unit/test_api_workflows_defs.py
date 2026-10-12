"""워크플로우 정의/버전/접근/복제 엔드포인트 테스트 — 실제 Postgres(SAVEPOINT 롤백).

대상: workflows/definitions.py, versions.py, access.py, cloning.py.
엔드포인트 함수를 직접 호출하며 404/403/409/400 분기와 DB 부수효과를 검증한다.
"""
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.v1.endpoints.workflows import definitions as defs
from app.api.v1.endpoints.workflows import versions as vers
from app.api.v1.endpoints.workflows.access import (
    check_workflow_access,
    get_version_or_404,
    get_workflow_or_404,
)
from app.api.v1.endpoints.workflows.schemas import (
    BlockIn,
    EdgeIn,
    GraphUpdate,
    WorkflowCreate,
    WorkflowDuplicate,
    WorkflowStatusUpdate,
)
from app.db.models.workflow import WorkflowBlockInstance, WorkflowDefinition, WorkflowEdge, WorkflowVersion
from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep
from tests.unit.api_pg_helpers import (  # noqa: F401
    add_member,
    db_session,
    make_block,
    make_collection,
    make_edge,
    make_project,
    make_user,
    make_valid_graph,
    make_version,
    make_workflow,
)


def U(value) -> UUID:
    return UUID(str(value))


async def _count(db, model, *where) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(*where))


@pytest.fixture
async def world(db_session):
    """소유자 + 프로젝트 + 워크플로우(v1 게시 안 됨) + 무관한 사용자."""
    owner = await make_user(db_session, "editor", "owner")
    stranger = await make_user(db_session, "viewer", "stranger")
    project = await make_project(db_session, owner, "P1")
    workflow = await make_workflow(db_session, owner, project, name="wf-1")
    version = await make_version(db_session, workflow, owner, 1)
    return dict(db=db_session, owner=owner, stranger=stranger, project=project,
                workflow=workflow, version=version)


# ---------- access.py ----------

@pytest.mark.asyncio
async def test_get_workflow_or_404_raises_for_unknown_id(db_session):
    with pytest.raises(HTTPException) as exc:
        await get_workflow_or_404(db_session, uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_version_or_404_rejects_version_of_other_workflow(world):
    other = await make_workflow(world["db"], world["owner"], world["project"], name="other")
    with pytest.raises(HTTPException) as exc:
        await get_version_or_404(world["db"], other.id, world["version"].id)
    assert exc.value.status_code == 404

    found = await get_version_or_404(world["db"], world["workflow"].id, world["version"].id)
    assert found.id == world["version"].id


@pytest.mark.asyncio
async def test_check_workflow_access_system_workflow_viewer_ok_editor_needs_admin(db_session):
    owner = await make_user(db_session, "editor")
    admin = await make_user(db_session, "admin")
    system_wf = await make_workflow(db_session, owner, None, kind="PREPROCESS", name="sys")

    await check_workflow_access(db_session, system_wf, owner, "viewer")  # 모두 조회 가능
    with pytest.raises(HTTPException) as exc:
        await check_workflow_access(db_session, system_wf, owner, "editor")
    assert exc.value.status_code == 403
    await check_workflow_access(db_session, system_wf, admin, "editor")


@pytest.mark.asyncio
async def test_check_workflow_access_project_workflow_denies_stranger(world):
    with pytest.raises(HTTPException) as exc:
        await check_workflow_access(world["db"], world["workflow"], world["stranger"], "viewer")
    assert exc.value.status_code == 403


# ---------- definitions.py ----------

@pytest.mark.asyncio
async def test_list_block_types_includes_labels_and_schema():
    result = await defs.list_block_types(current_user=None)
    by_type = {i["block_type"]: i for i in result["items"]}
    assert "input" in by_type and "output" in by_type
    assert isinstance(by_type["input"]["config_schema"], dict)
    assert by_type["input"]["label"]


@pytest.mark.asyncio
async def test_create_workflow_creates_definition_and_first_version(world):
    db = world["db"]
    data = WorkflowCreate(project_id=U(world["project"].id), name="새 워크플로", kind="PREPROCESS")

    created = await defs.create_workflow(data, db, world["owner"])

    assert created.name == "새 워크플로" and created.kind == "PREPROCESS"
    versions = (await db.scalars(
        select(WorkflowVersion).where(WorkflowVersion.workflow_id == created.id))).all()
    assert [v.version_number for v in versions] == [1]
    assert versions[0].published_at is None


@pytest.mark.asyncio
async def test_create_workflow_requires_editor_role(world):
    db = world["db"]
    viewer = await make_user(db, "viewer")
    await add_member(db, world["project"], viewer, "viewer", world["owner"])
    data = WorkflowCreate(project_id=U(world["project"].id), name="x")

    with pytest.raises(HTTPException) as exc:
        await defs.create_workflow(data, db, viewer)
    assert exc.value.status_code == 403


def test_workflow_create_rejects_invalid_kind():
    with pytest.raises(ValueError):
        WorkflowCreate(project_id=uuid4(), name="x", kind="BOGUS")


@pytest.mark.asyncio
async def test_list_workflows_by_project_includes_system_default_and_metadata(world):
    db = world["db"]
    system_wf = await make_workflow(db, world["owner"], None, kind="PREPROCESS", name="sys-default")
    await make_version(db, system_wf, world["owner"], 1)
    await make_version(db, world["workflow"], world["owner"], 2)
    await make_collection(db, world["owner"], world["project"], default_workflow_id=world["workflow"].id)

    result = await defs.list_workflows(U(world["project"].id), None, db, world["owner"])

    items = {i.name: i for i in result["items"]}
    assert set(items) >= {"wf-1", "sys-default"}
    mine = items["wf-1"]
    assert mine.project_name == "P1" and mine.created_by_username == "owner"
    assert mine.is_system_default is False
    assert mine.latest_version_number == 2
    assert mine.default_for_collection_count == 1
    assert items["sys-default"].is_system_default is True
    assert items["sys-default"].project_name is None


@pytest.mark.asyncio
async def test_list_workflows_without_project_scopes_to_accessible_projects(world):
    db = world["db"]
    foreign_project = await make_project(db, world["stranger"], "foreign")
    await make_workflow(db, world["stranger"], foreign_project, name="foreign-wf")

    result = await defs.list_workflows(None, None, db, world["owner"])

    names = {i.name for i in result["items"]}
    assert "wf-1" in names and "foreign-wf" not in names


@pytest.mark.asyncio
async def test_list_workflows_filters_by_kind(world):
    db = world["db"]
    await make_workflow(db, world["owner"], world["project"], kind="PREPROCESS", name="pre-wf")

    result = await defs.list_workflows(U(world["project"].id), "PREPROCESS", db, world["owner"])

    assert {i.kind for i in result["items"]} == {"PREPROCESS"}
    assert "wf-1" not in {i.name for i in result["items"]}


@pytest.mark.asyncio
async def test_list_workflows_denies_non_member_project(world):
    with pytest.raises(HTTPException) as exc:
        await defs.list_workflows(U(world["project"].id), None, world["db"], world["stranger"])
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_get_workflow_returns_workflow_and_404s(world):
    got = await defs.get_workflow(U(world["workflow"].id), world["db"], world["owner"])
    assert str(got.id) == str(world["workflow"].id)
    with pytest.raises(HTTPException) as exc:
        await defs.get_workflow(uuid4(), world["db"], world["owner"])
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_workflow_status_changes_status_and_trims_name(world):
    data = WorkflowStatusUpdate(status="ACTIVE", name="  새 이름  ")
    updated = await defs.update_workflow_status(U(world["workflow"].id), data, world["db"], world["owner"])
    assert updated.status == "ACTIVE" and updated.name == "새 이름"


@pytest.mark.asyncio
async def test_update_workflow_status_rejects_invalid_status(world):
    with pytest.raises(HTTPException) as exc:
        await defs.update_workflow_status(
            U(world["workflow"].id), WorkflowStatusUpdate(status="NOPE"), world["db"], world["owner"])
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_update_workflow_status_blocks_deactivating_system_default(db_session):
    admin = await make_user(db_session, "admin")
    system_wf = await make_workflow(db_session, admin, None, kind="PREPROCESS")
    with pytest.raises(HTTPException) as exc:
        await defs.update_workflow_status(
            U(system_wf.id), WorkflowStatusUpdate(status="INACTIVE"), db_session, admin)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_duplicate_workflow_copies_latest_graph_into_target_project(world):
    db = world["db"]
    await make_version(db, world["workflow"], world["owner"], 2)
    latest = (await db.scalars(select(WorkflowVersion).where(
        WorkflowVersion.workflow_id == world["workflow"].id,
        WorkflowVersion.version_number == 2))).one()
    await make_valid_graph(db, latest)
    target = await make_project(db, world["owner"], "target")

    copy = await defs.duplicate_workflow(
        U(world["workflow"].id), WorkflowDuplicate(project_id=U(target.id)), db, world["owner"])

    assert copy.name == "wf-1 사본" and str(copy.project_id) == str(target.id)
    new_version = (await db.scalars(
        select(WorkflowVersion).where(WorkflowVersion.workflow_id == copy.id))).one()
    assert new_version.version_number == 1
    blocks = (await db.scalars(select(WorkflowBlockInstance).where(
        WorkflowBlockInstance.version_id == new_version.id))).all()
    edges = (await db.scalars(select(WorkflowEdge).where(
        WorkflowEdge.version_id == new_version.id))).all()
    assert sorted(b.block_type for b in blocks) == ["input", "output"]
    assert len(edges) == 1
    assert {str(edges[0].from_block_id), str(edges[0].to_block_id)} == {str(b.id) for b in blocks}


@pytest.mark.asyncio
async def test_duplicate_workflow_requires_editor_on_target_project(world):
    db = world["db"]
    foreign = await make_project(db, world["stranger"], "foreign")
    with pytest.raises(HTTPException) as exc:
        await defs.duplicate_workflow(
            U(world["workflow"].id), WorkflowDuplicate(project_id=U(foreign.id)), db, world["owner"])
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_delete_workflow_removes_versions_blocks_edges_runs_and_steps(world):
    db = world["db"]
    source, _sink = await make_valid_graph(db, world["version"])
    run = WorkflowRun(id=str(uuid4()), version_id=str(world["version"].id), status="COMPLETED")
    db.add(run)
    await db.flush()
    db.add(WorkflowRunStep(run_id=run.id, block_instance_id=source.id, status="COMPLETED"))
    await db.flush()

    result = await defs.delete_workflow(U(world["workflow"].id), db, world["owner"])

    assert result == {"deleted": True}
    wid = world["workflow"].id
    assert await _count(db, WorkflowDefinition, WorkflowDefinition.id == wid) == 0
    assert await _count(db, WorkflowVersion, WorkflowVersion.workflow_id == wid) == 0
    assert await _count(db, WorkflowRun, WorkflowRun.id == run.id) == 0
    assert await _count(db, WorkflowBlockInstance, WorkflowBlockInstance.id == source.id) == 0


@pytest.mark.asyncio
async def test_delete_workflow_without_versions_deletes_definition(world):
    db = world["db"]
    lone = await make_workflow(db, world["owner"], world["project"], name="lone")
    assert await defs.delete_workflow(U(lone.id), db, world["owner"]) == {"deleted": True}
    assert await _count(db, WorkflowDefinition, WorkflowDefinition.id == lone.id) == 0


@pytest.mark.asyncio
async def test_delete_workflow_rejects_system_default(db_session):
    admin = await make_user(db_session, "admin")
    system_wf = await make_workflow(db_session, admin, None, kind="PREPROCESS")
    with pytest.raises(HTTPException) as exc:
        await defs.delete_workflow(U(system_wf.id), db_session, admin)
    assert exc.value.status_code == 409


# ---------- versions.py ----------

@pytest.mark.asyncio
async def test_list_versions_orders_newest_first(world):
    db = world["db"]
    await make_version(db, world["workflow"], world["owner"], 2)
    result = await vers.list_versions(U(world["workflow"].id), db, world["owner"])
    assert [v.version_number for v in result["items"]] == [2, 1]


@pytest.mark.asyncio
async def test_create_draft_version_increments_number_and_clones_graph(world):
    db = world["db"]
    await make_valid_graph(db, world["version"])

    draft = await vers.create_draft_version(U(world["workflow"].id), db, world["owner"])

    assert draft.version_number == 2 and draft.published_at is None
    cloned = (await db.scalars(select(WorkflowBlockInstance).where(
        WorkflowBlockInstance.version_id == draft.id))).all()
    assert sorted(b.label for b in cloned) == ["in", "out"]
    assert await _count(db, WorkflowEdge, WorkflowEdge.version_id == draft.id) == 1


@pytest.mark.asyncio
async def test_create_draft_version_for_workflow_without_versions_starts_at_one(world):
    db = world["db"]
    lone = await make_workflow(db, world["owner"], world["project"], name="lone")
    draft = await vers.create_draft_version(U(lone.id), db, world["owner"])
    assert draft.version_number == 1


@pytest.mark.asyncio
async def test_delete_version_blocks_last_remaining_version(world):
    with pytest.raises(HTTPException) as exc:
        await vers.delete_version(
            U(world["workflow"].id), U(world["version"].id), world["db"], world["owner"])
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_delete_version_removes_children_and_runs(world):
    db = world["db"]
    second = await make_version(db, world["workflow"], world["owner"], 2)
    source, _ = await make_valid_graph(db, second)
    run = WorkflowRun(id=str(uuid4()), version_id=str(second.id), status="FAILED")
    db.add(run)
    await db.flush()
    db.add(WorkflowRunStep(run_id=run.id, block_instance_id=source.id, status="FAILED"))
    await db.flush()

    result = await vers.delete_version(U(world["workflow"].id), U(second.id), db, world["owner"])

    assert result == {"deleted": True}
    assert await _count(db, WorkflowVersion, WorkflowVersion.id == second.id) == 0
    assert await _count(db, WorkflowRun, WorkflowRun.id == run.id) == 0
    assert await _count(db, WorkflowBlockInstance, WorkflowBlockInstance.version_id == second.id) == 0
    assert await _count(db, WorkflowVersion, WorkflowVersion.id == world["version"].id) == 1


@pytest.mark.asyncio
async def test_get_graph_returns_blocks_and_edges(world):
    db = world["db"]
    source, sink = await make_valid_graph(db, world["version"])

    graph = await vers.get_graph(U(world["workflow"].id), U(world["version"].id), db, world["owner"])

    assert {b["block_type"] for b in graph["blocks"]} == {"input", "output"}
    assert graph["blocks"][0]["position"] == {"x": 1, "y": 2}
    assert [(str(e["from_block_id"]), str(e["to_block_id"])) for e in graph["edges"]] == [
        (str(source.id), str(sink.id))]


@pytest.mark.asyncio
async def test_get_graph_404_for_unknown_version(world):
    with pytest.raises(HTTPException) as exc:
        await vers.get_graph(U(world["workflow"].id), uuid4(), world["db"], world["owner"])
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_graph_replaces_graph_and_remaps_client_ids(world):
    db = world["db"]
    await make_valid_graph(db, world["version"])  # 기존 그래프는 통째로 교체되어야 한다
    client_in, client_out = str(uuid4()), str(uuid4())
    data = GraphUpdate(
        blocks=[BlockIn(id=client_in, block_type="input", label="A"),
                BlockIn(id=client_out, block_type="output", label="B")],
        edges=[EdgeIn(from_block_id=client_in, to_block_id=client_out, condition={"k": 1})],
    )

    result = await vers.update_graph(
        U(world["workflow"].id), U(world["version"].id), data, db, world["owner"])

    assert result == {"saved": True, "validation_errors": []}
    blocks = (await db.scalars(select(WorkflowBlockInstance).where(
        WorkflowBlockInstance.version_id == world["version"].id))).all()
    assert sorted(b.label for b in blocks) == ["A", "B"]
    edge = (await db.scalars(select(WorkflowEdge).where(
        WorkflowEdge.version_id == world["version"].id))).one()
    assert edge.condition == {"k": 1}
    assert {str(edge.from_block_id), str(edge.to_block_id)} == {str(b.id) for b in blocks}


@pytest.mark.asyncio
async def test_update_graph_reports_validation_errors_for_empty_graph(world):
    result = await vers.update_graph(
        U(world["workflow"].id), U(world["version"].id), GraphUpdate(blocks=[], edges=[]),
        world["db"], world["owner"])
    assert result["saved"] is True
    assert result["validation_errors"][0]["block_id"] is None


@pytest.mark.asyncio
async def test_publish_version_marks_published_and_activates_workflow(world):
    db = world["db"]
    await make_valid_graph(db, world["version"])

    result = await vers.publish_version(
        U(world["workflow"].id), U(world["version"].id), db, world["owner"])

    assert result["version_number"] == 1
    # 엔드포인트는 UUID 키로 로드한 별도 인스턴스를 바꾸므로 DB에서 다시 읽는다.
    version = await db.scalar(select(WorkflowVersion).where(WorkflowVersion.id == world["version"].id))
    workflow = await db.scalar(
        select(WorkflowDefinition).where(WorkflowDefinition.id == world["workflow"].id))
    assert version.published_at is not None
    assert workflow.status == "ACTIVE"


@pytest.mark.asyncio
async def test_publish_version_rejects_invalid_graph_with_errors(world):
    with pytest.raises(HTTPException) as exc:
        await vers.publish_version(
            U(world["workflow"].id), U(world["version"].id), world["db"], world["owner"])
    assert exc.value.status_code == 409
    assert exc.value.detail["errors"]
    assert world["version"].published_at is None


@pytest.mark.asyncio
async def test_version_mutations_forbidden_for_viewer_member(world):
    db = world["db"]
    viewer = await make_user(db, "viewer")
    await add_member(db, world["project"], viewer, "viewer", world["owner"])
    with pytest.raises(HTTPException) as exc:
        await vers.create_draft_version(U(world["workflow"].id), db, viewer)
    assert exc.value.status_code == 403
    # 조회는 가능
    result = await vers.list_versions(U(world["workflow"].id), db, viewer)
    assert len(result["items"]) == 1
