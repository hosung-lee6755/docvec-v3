"""전처리 완료 후 자동 분석 run 시작(_maybe_trigger_analysis) — 실제 Postgres.

documents.active_run_id → workflow_runs.id 와 workflow_runs.document_id → documents.id 는
외래키가 순환이라, 새 run을 flush하기 전에 문서의 active_run_id를 바꾸면 SQLAlchemy 작업 단위가
documents UPDATE를 workflow_runs INSERT보다 먼저 내보내 fk_documents_active_run_id 위반이 난다
(컬렉션에 기본 분석 워크플로우를 지정한 업로드 15건 중 12건이 이 경로로 FAILED가 됐다).
MagicMock 세션으로는 이 순서 문제를 재현할 수 없어 실제 DB로 고정한다.
"""
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
from app.pipeline.tasks.workflow import _maybe_trigger_analysis
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
