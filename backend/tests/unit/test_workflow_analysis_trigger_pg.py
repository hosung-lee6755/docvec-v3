"""전처리 완료 후 자동 분석 run 시작(_maybe_trigger_analysis) — 실제 Postgres.

documents.active_run_id → workflow_runs.id 와 workflow_runs.document_id → documents.id 는
외래키가 순환이라, 새 run을 flush하기 전에 문서의 active_run_id를 바꾸면 SQLAlchemy 작업 단위가
documents UPDATE를 workflow_runs INSERT보다 먼저 내보내 fk_documents_active_run_id 위반이 난다
(컬렉션에 기본 분석 워크플로우를 지정한 업로드 15건 중 12건이 이 경로로 FAILED가 됐다).
MagicMock 세션으로는 이 순서 문제를 재현할 수 없어 실제 DB로 고정한다.
"""
from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.collection import Collection
from app.db.models.document import Document
from app.db.models.user import User
from app.db.models.workflow import WorkflowBlockInstance, WorkflowDefinition, WorkflowVersion
from app.db.models.workflow_run import WorkflowRun
from app.pipeline.tasks.workflow import STANDARD_ANALYSIS_WORKFLOW_ID, _maybe_trigger_analysis
from tests.conftest import TEST_DATABASE_URL

SYNC_URL = TEST_DATABASE_URL.replace("+asyncpg", "+psycopg2")


@pytest.fixture(scope="module")
def session_factory():
    engine = create_engine(SYNC_URL)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def scenario(session_factory):
    """PREPROCESS run이 끝난 문서 + 기본 분석 워크플로우(v1, 입력 블록 하나)가 지정된 컬렉션."""
    db: Session = session_factory()
    user = User(
        id=uuid4(), email=f"{uuid4()}@example.com", username="analysis-trigger-test",
        hashed_password="!", role="viewer", is_active=True,
    )
    db.add(user)
    db.flush()
    preprocess = WorkflowDefinition(id=uuid4(), name="pre", kind="PREPROCESS", created_by=user.id)
    analysis = WorkflowDefinition(id=uuid4(), name="ana", kind="ANALYSIS", created_by=user.id)
    db.add_all([preprocess, analysis])
    db.flush()
    pre_version = WorkflowVersion(id=uuid4(), workflow_id=preprocess.id, version_number=1, created_by=user.id)
    ana_version = WorkflowVersion(id=uuid4(), workflow_id=analysis.id, version_number=1, created_by=user.id)
    db.add_all([pre_version, ana_version])
    db.flush()
    entry = WorkflowBlockInstance(id=uuid4(), version_id=ana_version.id, block_type="input", config={})
    collection = Collection(
        id=uuid4(), name="c", qdrant_collection_name=f"c_{uuid4().hex}", created_by=user.id,
        default_analysis_workflow_id=analysis.id, default_analysis_workflow_version=1,
    )
    db.add_all([entry, collection])
    db.flush()
    document = Document(
        id=uuid4(), filename="a.pdf", original_filename="a.pdf", file_size=1,
        mime_type="application/pdf", file_hash="h" * 64, minio_key=f"{uuid4()}/a.pdf",
        status="INDEXED", created_by=user.id, collection_id=collection.id,
    )
    db.add(document)
    db.flush()
    pre_run = WorkflowRun(id=uuid4(), version_id=pre_version.id, document_id=document.id, status="COMPLETED")
    db.add(pre_run)
    db.flush()
    document.active_run_id = pre_run.id
    db.commit()
    ctx = {"document": document, "pre_run": pre_run, "entry": entry}
    yield ctx
    cleanup: Session = session_factory()
    cleanup.execute(Document.__table__.update().where(Document.id == document.id).values(active_run_id=None))
    cleanup.query(WorkflowRun).filter(WorkflowRun.document_id == document.id).delete()
    cleanup.query(Document).filter(Document.id == document.id).delete()
    cleanup.query(Collection).filter(Collection.id == collection.id).delete()
    cleanup.query(WorkflowBlockInstance).filter(WorkflowBlockInstance.id == entry.id).delete()
    cleanup.query(WorkflowVersion).filter(WorkflowVersion.id.in_([pre_version.id, ana_version.id])).delete()
    cleanup.query(WorkflowDefinition).filter(WorkflowDefinition.id.in_([preprocess.id, analysis.id])).delete()
    cleanup.query(User).filter(User.id == user.id).delete()
    cleanup.commit()
    cleanup.close()


def test_analysis_run_is_persisted_before_document_points_to_it(session_factory, scenario):
    with patch("app.pipeline.tasks.workflow.run_workflow_step") as task:
        db = session_factory()
        # 진행 중에 외래키 위반이 나면 여기서 IntegrityError가 올라온다.
        _maybe_trigger_analysis(db, scenario["pre_run"])
        db.close()

    check = session_factory()
    try:
        document = check.get(Document, scenario["document"].id)
        analysis_runs = list(check.scalars(select(WorkflowRun).where(
            WorkflowRun.document_id == document.id, WorkflowRun.trigger == "AUTO_ANALYSIS",
        )))
        assert len(analysis_runs) == 1
        assert document.active_run_id == analysis_runs[0].id
        assert document.status == "ANALYZING"
    finally:
        check.close()
    assert task.apply_async.call_count == 1
    assert task.apply_async.call_args.kwargs["args"] == [str(analysis_runs[0].id), str(scenario["entry"].id)]


@pytest.fixture
def standard_analysis(session_factory, scenario):
    """시스템 표준 분석 워크플로우(프로젝트 없음, ANALYSIS, 게시된 v1, 입력 블록 하나). 컬렉션에는 분석 워크플로우가 없다."""
    db: Session = session_factory()
    user_id = scenario["document"].created_by
    workflow = WorkflowDefinition(
        id=STANDARD_ANALYSIS_WORKFLOW_ID, name="표준 분석", kind="ANALYSIS", created_by=user_id, project_id=None,
    )
    db.add(workflow)
    db.flush()
    version = WorkflowVersion(
        id=uuid4(), workflow_id=workflow.id, version_number=1, created_by=user_id, published_at=datetime.utcnow(),
    )
    db.add(version)
    db.flush()
    entry = WorkflowBlockInstance(id=uuid4(), version_id=version.id, block_type="input", config={})
    db.add(entry)
    db.query(Collection).filter(Collection.id == scenario["document"].collection_id).update(
        {"default_analysis_workflow_id": None, "default_analysis_workflow_version": None})
    db.commit()
    db.close()
    yield {"version": version, "entry": entry}
    cleanup: Session = session_factory()
    cleanup.execute(Document.__table__.update().where(Document.id == scenario["document"].id).values(active_run_id=None))
    cleanup.query(WorkflowRun).filter(WorkflowRun.version_id == version.id).delete()
    cleanup.query(WorkflowBlockInstance).filter(WorkflowBlockInstance.id == entry.id).delete()
    cleanup.query(WorkflowVersion).filter(WorkflowVersion.id == version.id).delete()
    cleanup.query(WorkflowDefinition).filter(WorkflowDefinition.id == workflow.id).delete()
    cleanup.commit()
    cleanup.close()


def test_collection_without_analysis_workflow_runs_the_standard_analysis_workflow(
    session_factory, scenario, standard_analysis,
):
    """분석 워크플로우가 없는 컬렉션은 시스템 표준 분석 워크플로우로 분석 실행을 만든다(2026-11-20).
    예전에는 워크플로우 밖에서 요약·메타데이터 작업을 직접 보내 처리 이력에 남지 않았고, 컬렉션 화면의
    "지정하면 요약·키워드가 생긴다"는 안내와도 어긋났다."""
    with patch("app.pipeline.tasks.summary.generate_summary") as summary, \
            patch("app.pipeline.tasks.metadata.extract_metadata") as metadata, \
            patch("app.pipeline.tasks.workflow.run_workflow_step") as step:
        db = session_factory()
        _maybe_trigger_analysis(db, scenario["pre_run"])
        db.close()

    check = session_factory()
    try:
        runs = list(check.scalars(select(WorkflowRun).where(
            WorkflowRun.document_id == scenario["document"].id, WorkflowRun.trigger == "AUTO_ANALYSIS",
        )))
    finally:
        check.close()
    assert [r.version_id for r in runs] == [standard_analysis["version"].id]
    assert step.apply_async.call_args.kwargs["args"] == [str(runs[0].id), str(standard_analysis["entry"].id)]
    summary.delay.assert_not_called()
    metadata.delay.assert_not_called()


def test_without_any_analysis_workflow_nothing_runs(session_factory, scenario):
    """표준 분석 워크플로우도 없으면(시드 전 DB) 분석을 하지 않는다. 워크플로우 밖의 작업을 몰래 보내지 않는다."""
    setup = session_factory()
    setup.query(Collection).filter(Collection.id == scenario["document"].collection_id).update(
        {"default_analysis_workflow_id": None, "default_analysis_workflow_version": None})
    setup.commit()
    setup.close()

    with patch("app.pipeline.tasks.summary.generate_summary") as summary, \
            patch("app.pipeline.tasks.metadata.extract_metadata") as metadata, \
            patch("app.pipeline.tasks.workflow.run_workflow_step") as step:
        db = session_factory()
        _maybe_trigger_analysis(db, scenario["pre_run"])
        db.close()

    summary.delay.assert_not_called()
    metadata.delay.assert_not_called()
    step.apply_async.assert_not_called()


def test_analysis_workflow_collection_does_not_dispatch_default_tasks(session_factory, scenario):
    with patch("app.pipeline.tasks.summary.generate_summary") as summary, \
            patch("app.pipeline.tasks.metadata.extract_metadata") as metadata, \
            patch("app.pipeline.tasks.workflow.run_workflow_step"):
        db = session_factory()
        _maybe_trigger_analysis(db, scenario["pre_run"])
        db.close()

    summary.delay.assert_not_called()
    metadata.delay.assert_not_called()


def test_analysis_without_summary_step_clears_the_old_summary(session_factory, scenario):
    """사용자 분석 워크플로우를 그대로 따른다(2026-11-20). 입력 블록뿐인 워크플로우는 요약, 태그, 분류를 만들지 않으므로
    예전 실행이 남긴 값을 비우고, 요약 검색 색인에서도 뺀다. 사용자가 단 태그는 건드리지 않는다."""
    setup = session_factory()
    setup.query(Document).filter(Document.id == scenario["document"].id).update({
        "summary": "예전 요약", "summary_status": "DONE", "suggested_tags": ["예전"], "metadata_status": "DONE",
        "category": "예전 분류", "tags": ["사용자 태그"],
    })
    setup.commit()
    setup.close()

    with patch("app.pipeline.tasks.workflow.run_workflow_step"), \
            patch("app.services.summary_index.delete_document_summary") as delete_summary:
        db = session_factory()
        _maybe_trigger_analysis(db, scenario["pre_run"])
        db.close()

    check = session_factory()
    try:
        document = check.get(Document, scenario["document"].id)
        assert document.summary is None
        assert document.summary_status == "SKIPPED"
        assert document.suggested_tags is None
        assert document.metadata_status == "SKIPPED"
        assert document.category is None
        assert document.tags == ["사용자 태그"]
    finally:
        check.close()
    delete_summary.assert_called_once_with(str(scenario["document"].id))


def _document_analysis(session_factory, scenario, project_id=None):
    """문서에 직접 고른 분석 워크플로우(게시된 v1, 입력 블록 하나)를 붙인다."""
    db: Session = session_factory()
    user_id = scenario["document"].created_by
    workflow = WorkflowDefinition(id=uuid4(), name="문서 분석", kind="ANALYSIS", created_by=user_id, project_id=project_id)
    db.add(workflow)
    db.flush()
    version = WorkflowVersion(
        id=uuid4(), workflow_id=workflow.id, version_number=1, created_by=user_id, published_at=datetime.utcnow(),
    )
    db.add(version)
    db.flush()
    db.add(WorkflowBlockInstance(id=uuid4(), version_id=version.id, block_type="input", config={}))
    db.query(Document).filter(Document.id == scenario["document"].id).update({"analysis_workflow_id": workflow.id})
    db.commit()
    db.close()
    return workflow, version


def _cleanup_document_analysis(session_factory, scenario, workflow, version):
    cleanup: Session = session_factory()
    cleanup.execute(Document.__table__.update().where(Document.id == scenario["document"].id).values(
        active_run_id=None, analysis_workflow_id=None))
    cleanup.query(WorkflowRun).filter(WorkflowRun.version_id == version.id).delete()
    cleanup.query(WorkflowBlockInstance).filter(WorkflowBlockInstance.version_id == version.id).delete()
    cleanup.query(WorkflowVersion).filter(WorkflowVersion.id == version.id).delete()
    cleanup.query(WorkflowDefinition).filter(WorkflowDefinition.id == workflow.id).delete()
    cleanup.commit()
    cleanup.close()


def _auto_analysis_versions(session_factory, document_id):
    check = session_factory()
    try:
        return [r.version_id for r in check.scalars(select(WorkflowRun).where(
            WorkflowRun.document_id == document_id, WorkflowRun.trigger == "AUTO_ANALYSIS"))]
    finally:
        check.close()


def test_analysis_workflow_chosen_for_the_document_comes_before_the_collection_default(session_factory, scenario):
    """업로드 때 문서에 고른 분석 워크플로우가 컬렉션 기본 분석보다 먼저다(2026-11-24). 문서에 남기므로 재처리 뒤에도 같다."""
    workflow, version = _document_analysis(session_factory, scenario)
    try:
        with patch("app.pipeline.tasks.workflow.run_workflow_step"):
            db = session_factory()
            _maybe_trigger_analysis(db, scenario["pre_run"])
            db.close()
        assert _auto_analysis_versions(session_factory, scenario["document"].id) == [version.id]
    finally:
        _cleanup_document_analysis(session_factory, scenario, workflow, version)


def test_document_choice_from_another_project_falls_back_to_the_collection_default(session_factory, scenario):
    """문서가 다른 프로젝트 컬렉션에 있게 되면 그 프로젝트 전용 분석 워크플로우는 쓰지 않고 컬렉션 기본을 쓴다."""
    from app.db.models.project import Project

    setup = session_factory()
    project = Project(id=uuid4(), name="옛 프로젝트", created_by=scenario["document"].created_by)
    setup.add(project)
    setup.commit()
    setup.close()
    workflow, version = _document_analysis(session_factory, scenario, project_id=project.id)
    try:
        with patch("app.pipeline.tasks.workflow.run_workflow_step"):
            db = session_factory()
            _maybe_trigger_analysis(db, scenario["pre_run"])
            db.close()
        versions = _auto_analysis_versions(session_factory, scenario["document"].id)
        assert len(versions) == 1 and versions[0] != version.id
    finally:
        _cleanup_document_analysis(session_factory, scenario, workflow, version)
        cleanup = session_factory()
        cleanup.query(Project).filter(Project.id == project.id).delete()
        cleanup.commit()
        cleanup.close()
