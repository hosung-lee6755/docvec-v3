"""문서 상세 탭(구조/청크/정제/사전/PII)이 보여줄 run 해석 — 실제 DB.

컬렉션에 기본 분석 워크플로우가 있으면 전처리가 끝난 뒤 문서의 active_run_id가 분석 run으로
옮겨간다(진행 중인 run을 추적하기 위한 불변식). 그런데 노드/청크/정제/PII 같은 전처리 산출물은
전처리 run에만 있어서, active_run_id를 그대로 쓰면 분석이 끝나자마자 모든 탭이 비어 보였다
(청크 0개, 구조 노드 0개 — test_data 15건 E2E 화면 검토에서 발견).
"""
from datetime import datetime, timedelta
from uuid import uuid4

from app.api.v1.endpoints.documents.processing import _resolve_display_run_id
from app.db.models.workflow import WorkflowDefinition, WorkflowVersion
from app.db.models.workflow_run import WorkflowRun
from tests.unit.test_documents_storage_release import OWNER_ID, _doc, db_session  # noqa: F401


async def _version(db, kind: str) -> WorkflowVersion:
    definition = WorkflowDefinition(id=uuid4(), name=kind, kind=kind, created_by=OWNER_ID)
    db.add(definition)
    await db.flush()
    version = WorkflowVersion(id=uuid4(), workflow_id=definition.id, version_number=1, created_by=OWNER_ID)
    db.add(version)
    await db.flush()
    return version


async def _run(db, doc, version, trigger: str, minutes_ago: int) -> WorkflowRun:
    run = WorkflowRun(
        id=uuid4(), version_id=version.id, document_id=doc.id, status="COMPLETED", trigger=trigger,
        created_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
    )
    db.add(run)
    await db.flush()
    return run


async def test_analysis_active_run_resolves_to_the_preprocess_run(db_session):  # noqa: F811
    doc = _doc("k1")
    db_session.add(doc)
    await db_session.flush()
    pre, ana = await _version(db_session, "PREPROCESS"), await _version(db_session, "ANALYSIS")
    preprocess_run = await _run(db_session, doc, pre, "UPLOAD", minutes_ago=10)
    analysis_run = await _run(db_session, doc, ana, "AUTO_ANALYSIS", minutes_ago=5)
    doc.active_run_id = analysis_run.id
    await db_session.flush()

    assert await _resolve_display_run_id(db_session, doc) == str(preprocess_run.id)


async def test_active_preprocess_run_is_used_as_is(db_session):  # noqa: F811
    doc = _doc("k2")
    db_session.add(doc)
    await db_session.flush()
    pre = await _version(db_session, "PREPROCESS")
    older = await _run(db_session, doc, pre, "UPLOAD", minutes_ago=10)
    newer = await _run(db_session, doc, pre, "REPROCESS", minutes_ago=5)
    doc.active_run_id = older.id  # 활성 run이 전처리 run이면 최신 여부와 상관없이 그대로 따른다
    await db_session.flush()

    assert await _resolve_display_run_id(db_session, doc) == str(older.id)
    assert str(newer.id) != str(older.id)


async def test_latest_preprocess_run_is_used_when_nothing_is_active(db_session):  # noqa: F811
    doc = _doc("k3")
    db_session.add(doc)
    await db_session.flush()
    pre, ana = await _version(db_session, "PREPROCESS"), await _version(db_session, "ANALYSIS")
    await _run(db_session, doc, pre, "UPLOAD", minutes_ago=10)
    latest_pre = await _run(db_session, doc, pre, "REPROCESS", minutes_ago=6)
    await _run(db_session, doc, ana, "AUTO_ANALYSIS", minutes_ago=2)

    assert await _resolve_display_run_id(db_session, doc) == str(latest_pre.id)


async def test_falls_back_to_the_active_run_when_the_document_has_no_preprocess_run(db_session):  # noqa: F811
    doc = _doc("k4")
    db_session.add(doc)
    await db_session.flush()
    ana = await _version(db_session, "ANALYSIS")
    only_run = await _run(db_session, doc, ana, "UPLOAD", minutes_ago=3)
    doc.active_run_id = only_run.id
    await db_session.flush()

    assert await _resolve_display_run_id(db_session, doc) == str(only_run.id)


async def test_returns_none_when_the_document_has_no_runs(db_session):  # noqa: F811
    doc = _doc("k5")
    db_session.add(doc)
    await db_session.flush()

    assert await _resolve_display_run_id(db_session, doc) is None
