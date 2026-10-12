"""대시보드 통계 엔드포인트 테스트 — 실제 Postgres(SAVEPOINT 롤백).

대상: app/api/v1/endpoints/stats.py (/stats 가시 범위·상태 집계, /stats/processing 24시간 처리 현황).
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.api.v1.endpoints import stats as api
from app.db.models.quality_report import QualityReport
from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep
from tests.unit.api_pg_helpers import (  # noqa: F401
    add_member,
    db_session,
    make_block,
    make_collection,
    make_document,
    make_project,
    make_user,
    make_valid_graph,
    make_version,
    make_workflow,
)

NOW = datetime.utcnow()


@pytest.fixture
async def world(db_session):
    owner = await make_user(db_session, "editor", "owner")
    other = await make_user(db_session, "viewer", "other")
    return dict(db=db_session, owner=owner, other=other)


# ---------- /stats ----------

@pytest.mark.asyncio
async def test_get_stats_counts_owned_and_shared_documents_by_status(world):
    db, owner, other = world["db"], world["owner"], world["other"]
    own_col = await make_collection(db, owner, None, name="own")
    await make_document(db, owner, own_col, status="INDEXED")
    await make_document(db, owner, own_col, status="EMBEDDING")
    await make_document(db, owner, own_col, status="ANALYZING")  # 처리 중으로 집계
    await make_document(db, owner, own_col, status="FAILED")
    # 남의 프로젝트 컬렉션 문서는 프로젝트 멤버일 때만 보인다
    project = await make_project(db, other, "shared")
    await add_member(db, project, owner, "viewer", other)
    shared_col = await make_collection(db, other, project, name="shared-col")
    await make_document(db, other, shared_col, status="INDEXED")
    private_col = await make_collection(db, other, None, name="private")
    await make_document(db, other, private_col, status="INDEXED")

    stats = await api.get_stats(db, owner)

    assert stats == {"total_documents": 5, "processing": 2, "indexed": 2, "collections": 2}


@pytest.mark.asyncio
async def test_get_stats_empty_for_user_without_data(world):
    stats = await api.get_stats(world["db"], world["other"])
    assert stats == {"total_documents": 0, "processing": 0, "indexed": 0, "collections": 0}


# ---------- /stats/processing ----------

async def _run(db, version, doc, status, trigger="UPLOAD", created=None, **fields) -> WorkflowRun:
    run = WorkflowRun(version_id=str(version.id), document_id=str(doc.id), status=status,
                      trigger=trigger, created_at=created or NOW, **fields)
    db.add(run)
    await db.flush()
    return run


@pytest.mark.asyncio
async def test_processing_stats_empty_state_has_zero_rates(world):
    result = await api.get_processing_stats(world["db"], world["owner"])
    assert result.processed_documents == 0 and result.failure_rate == 0.0 and result.reprocess_rate == 0.0
    assert result.avg_quality is None and result.avg_queue_seconds is None
    assert result.block_stats == [] and result.recent_failures == []


@pytest.mark.asyncio
async def test_processing_stats_aggregates_runs_quality_blocks_and_failures(world):
    db, owner = world["db"], world["owner"]
    wf = await make_workflow(db, owner, None, kind="ANALYSIS")
    version = await make_version(db, wf, owner, published=True)
    source, sink = await make_valid_graph(db, version)
    col = await make_collection(db, owner, None)
    doc_ok = await make_document(db, owner, col, filename="ok.txt")
    doc_bad = await make_document(db, owner, col, filename="bad.txt")
    await make_document(db, owner, col, status="WAITING_REVIEW")

    ok_run = await _run(db, version, doc_ok, "COMPLETED", started_at=NOW + timedelta(seconds=10))
    repro_run = await _run(db, version, doc_ok, "COMPLETED", trigger="REPROCESS")
    bad_run = await _run(db, version, doc_bad, "FAILED", error_message="boom")
    await _run(db, version, doc_bad, "COMPLETED", created=NOW - timedelta(days=3))  # 24시간 밖
    db.add(QualityReport(run_id=str(ok_run.id), document_id=str(doc_ok.id), overall_score=0.8, status="SUCCESS"))
    db.add(QualityReport(run_id=str(repro_run.id), document_id=str(doc_ok.id), overall_score=0.6, status="SUCCESS"))
    db.add(WorkflowRunStep(run_id=ok_run.id, block_instance_id=source.id, status="COMPLETED",
                           started_at=NOW, completed_at=NOW + timedelta(seconds=4)))
    db.add(WorkflowRunStep(run_id=bad_run.id, block_instance_id=source.id, status="FAILED",
                           started_at=NOW, completed_at=NOW - timedelta(seconds=9)))  # 음수 → 평균에서 제외
    db.add(WorkflowRunStep(run_id=bad_run.id, block_instance_id=sink.id, status="COMPLETED"))
    await db.flush()

    result = await api.get_processing_stats(db, owner)

    assert result.processed_documents == 1  # 24시간 내 COMPLETED 문서(중복 제거)
    assert result.failure_rate == pytest.approx(1 / 3)
    assert result.reprocess_rate == pytest.approx(1 / 3)
    assert result.avg_quality == pytest.approx(0.7)
    assert result.waiting_review_count == 1
    assert result.avg_queue_seconds == pytest.approx(10.0)
    blocks = {b.block_type: b for b in result.block_stats}
    assert blocks["input"].execution_count == 2 and blocks["input"].failure_rate == 0.5
    assert blocks["input"].avg_duration_seconds == pytest.approx(4.0)
    assert blocks["output"].avg_duration_seconds is None
    assert [(f.filename, f.error_message) for f in result.recent_failures] == [("bad.txt", "boom")]


@pytest.mark.asyncio
async def test_processing_stats_scoped_to_current_user(world):
    db, owner, other = world["db"], world["owner"], world["other"]
    wf = await make_workflow(db, owner, None)
    version = await make_version(db, wf, owner, published=True)
    doc = await make_document(db, owner, None)
    await _run(db, version, doc, "FAILED", error_message="x")

    mine = await api.get_processing_stats(db, owner)
    theirs = await api.get_processing_stats(db, other)

    assert mine.failure_rate == 1.0 and len(mine.recent_failures) == 1
    assert theirs.failure_rate == 0.0 and theirs.recent_failures == []
    assert (await db.scalar(select(WorkflowRun.id).limit(1))) is not None
