"""워크플로 엔진(동기 세션) 동작 테스트 — 실제 Postgres.

MagicMock으로는 ON CONFLICT/원자적 UPDATE/조건부 UPDATE 같은 DB 의미를 검증할 수 없어
(회귀가 mock 때문에 가려졌다) 실제 DB에서 다음을 고정한다.
- 병합 블록: 업스트림이 동시에 도착해도 step 행은 하나, dispatch는 정확히 한 번.
- _fail_document: 문서가 다른 진행 중 run을 가리키면 아무것도 바꾸지 않고, stale이면 바로잡는다.
- sweeper: 타임아웃 초과 step/run/document를 FAILED로, 이미 끝난 step은 건드리지 않는다.
"""
import threading
from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.document import Document
from app.db.models.user import User
from app.db.models.workflow import (
    WorkflowBlockInstance,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowVersion,
)
from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep
from app.pipeline.tasks.workflow import (
    _advance,
    _fail_document,
    _maybe_complete_run,
    sweep_stuck_workflow_runs,
)
from tests.conftest import TEST_DATABASE_URL

SYNC_URL = TEST_DATABASE_URL.replace("+asyncpg", "+psycopg2")


@pytest.fixture(scope="module")
def session_factory():
    engine = create_engine(SYNC_URL)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def graph(session_factory):
    """user → workflow → version → blocks(a, b, merge) + edges(a→merge, b→merge) + run + document."""
    db: Session = session_factory()
    user = User(
        id=uuid4(), email=f"{uuid4()}@example.com", username="engine-test",
        hashed_password="!", role="viewer", is_active=True,
    )
    db.add(user)
    db.flush()
    definition = WorkflowDefinition(id=uuid4(), name="t", kind="PREPROCESS", created_by=user.id)
    db.add(definition)
    db.flush()
    version = WorkflowVersion(id=uuid4(), workflow_id=definition.id, version_number=1, created_by=user.id)
    db.add(version)
    db.flush()
    blocks = {
        name: WorkflowBlockInstance(id=uuid4(), version_id=version.id, block_type=block_type, config={})
        for name, block_type in (("a", "postprocess"), ("b", "postprocess"), ("merge", "merge"))
    }
    db.add_all(blocks.values())
    db.flush()
    edges = [
        WorkflowEdge(id=uuid4(), version_id=version.id, from_block_id=blocks[src].id, to_block_id=blocks["merge"].id)
        for src in ("a", "b")
    ]
    document = Document(
        id=uuid4(), filename="a.pdf", original_filename="a.pdf", file_size=1,
        mime_type="application/pdf", file_hash="h" * 64, minio_key=f"{uuid4()}/a.pdf",
        status="PARSING", created_by=user.id,
    )
    db.add_all(edges + [document])
    db.flush()
    run = WorkflowRun(id=uuid4(), version_id=version.id, document_id=document.id, status="RUNNING")
    db.add(run)
    db.commit()
    ctx = {"user": user, "version": version, "blocks": blocks, "document": document, "run": run}
    yield ctx
    cleanup: Session = session_factory()
    run_ids = list(cleanup.scalars(select(WorkflowRun.id).where(WorkflowRun.version_id == version.id)))
    cleanup.execute(Document.__table__.update().where(Document.id == document.id).values(active_run_id=None))
    for run_id in run_ids:
        cleanup.query(WorkflowRunStep).filter(WorkflowRunStep.run_id == run_id).delete()
    cleanup.query(WorkflowRun).filter(WorkflowRun.version_id == version.id).delete()
    cleanup.query(Document).filter(Document.id == document.id).delete()
    cleanup.query(WorkflowEdge).filter(WorkflowEdge.version_id == version.id).delete()
    cleanup.query(WorkflowBlockInstance).filter(WorkflowBlockInstance.version_id == version.id).delete()
    cleanup.query(WorkflowVersion).filter(WorkflowVersion.id == version.id).delete()
    cleanup.query(WorkflowDefinition).filter(WorkflowDefinition.id == definition.id).delete()
    cleanup.query(User).filter(User.id == user.id).delete()
    cleanup.commit()
    cleanup.close()


def _merge_steps(session_factory, run_id, merge_id) -> list[WorkflowRunStep]:
    db = session_factory()
    try:
        return list(db.scalars(select(WorkflowRunStep).where(
            WorkflowRunStep.run_id == run_id, WorkflowRunStep.block_instance_id == merge_id,
        )))
    finally:
        db.close()


def test_merge_waits_for_all_upstreams_then_dispatches_once(session_factory, graph):
    run_id, blocks = str(graph["run"].id), graph["blocks"]
    with patch("app.pipeline.tasks.workflow.run_workflow_step") as task:
        db = session_factory()
        _advance(db, run_id, blocks["a"], {})
        assert task.apply_async.call_count == 0
        _advance(db, run_id, blocks["b"], {})
        db.close()

    assert task.apply_async.call_count == 1
    assert task.apply_async.call_args.kwargs["args"] == [run_id, str(blocks["merge"].id)]
    (step,) = _merge_steps(session_factory, graph["run"].id, blocks["merge"].id)
    assert step.completed_incoming_edges == 2


def test_concurrent_upstreams_create_one_merge_step_and_dispatch_once(session_factory, graph):
    run_id, blocks = str(graph["run"].id), graph["blocks"]
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def arrive(upstream):
        db = session_factory()
        try:
            barrier.wait(timeout=10)
            _advance(db, run_id, upstream, {})
        except BaseException as exc:  # noqa: BLE001 — 스레드 오류를 메인 스레드에서 단언한다
            errors.append(exc)
        finally:
            db.close()

    with patch("app.pipeline.tasks.workflow.run_workflow_step") as task:
        threads = [threading.Thread(target=arrive, args=(blocks[name],)) for name in ("a", "b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

    assert errors == []
    assert task.apply_async.call_count == 1
    (step,) = _merge_steps(session_factory, graph["run"].id, blocks["merge"].id)
    assert step.completed_incoming_edges == 2


def _second_run(session_factory, graph, status: str) -> WorkflowRun:
    db = session_factory()
    other = WorkflowRun(id=uuid4(), version_id=graph["version"].id, document_id=graph["document"].id, status=status)
    db.add(other)
    db.commit()
    db.close()
    return other


def _set_active(session_factory, document_id, run_id) -> None:
    db = session_factory()
    db.execute(Document.__table__.update().where(Document.id == document_id).values(active_run_id=run_id))
    db.commit()
    db.close()


def _document(session_factory, document_id) -> Document:
    db = session_factory()
    try:
        return db.get(Document, document_id)
    finally:
        db.close()


def test_fail_document_does_not_touch_document_while_newer_run_is_live(session_factory, graph):
    newer = _second_run(session_factory, graph, "RUNNING")
    _set_active(session_factory, graph["document"].id, newer.id)

    db = session_factory()
    _fail_document(db, db.get(WorkflowRun, graph["run"].id), "옛 run 실패")
    db.commit()
    db.close()

    doc = _document(session_factory, graph["document"].id)
    assert doc.status == "PARSING"
    assert doc.error_message is None
    assert str(doc.active_run_id) == str(newer.id)


def test_fail_document_repoints_when_active_run_pointer_is_stale(session_factory, graph):
    finished = _second_run(session_factory, graph, "COMPLETED")
    _set_active(session_factory, graph["document"].id, finished.id)

    db = session_factory()
    _fail_document(db, db.get(WorkflowRun, graph["run"].id), "실패")
    db.commit()
    db.close()

    doc = _document(session_factory, graph["document"].id)
    assert doc.status == "FAILED"
    assert doc.error_message == "실패"
    assert str(doc.active_run_id) == str(graph["run"].id)


def _running_step(session_factory, graph, started_ago: int) -> WorkflowRunStep:
    db = session_factory()
    step = WorkflowRunStep(
        id=uuid4(), run_id=graph["run"].id, block_instance_id=graph["blocks"]["a"].id,
        status="RUNNING", started_at=datetime.utcnow() - timedelta(seconds=started_ago),
    )
    db.add(step)
    db.commit()
    db.close()
    return step


def _sweep(session_factory):
    with patch("app.db.session.get_sync_db", side_effect=lambda: session_factory()):
        return sweep_stuck_workflow_runs()


def test_sweep_fails_step_run_and_document_past_timeout(session_factory, graph):
    step = _running_step(session_factory, graph, started_ago=100_000)
    _set_active(session_factory, graph["document"].id, graph["run"].id)

    result = _sweep(session_factory)

    assert str(graph["run"].id) in result["swept_run_ids"]
    db = session_factory()
    assert db.get(WorkflowRunStep, step.id).status == "FAILED"
    assert db.get(WorkflowRunStep, step.id).error_code == "TIMEOUT_EXCEEDED"
    assert db.get(WorkflowRun, graph["run"].id).status == "FAILED"
    assert db.get(Document, graph["document"].id).status == "FAILED"
    db.close()


def test_sweep_leaves_recent_running_step_alone(session_factory, graph):
    step = _running_step(session_factory, graph, started_ago=5)

    result = _sweep(session_factory)

    assert str(graph["run"].id) not in result["swept_run_ids"]
    db = session_factory()
    assert db.get(WorkflowRunStep, step.id).status == "RUNNING"
    assert db.get(WorkflowRun, graph["run"].id).status == "RUNNING"
    db.close()


def _completed_step(session_factory, graph, name: str, completed_ago: int) -> WorkflowRunStep:
    db = session_factory()
    now = datetime.utcnow()
    step = WorkflowRunStep(
        id=uuid4(), run_id=graph["run"].id, block_instance_id=graph["blocks"][name].id,
        status="COMPLETED", output={},
        created_at=now - timedelta(seconds=completed_ago + 10),
        started_at=now - timedelta(seconds=completed_ago + 5),
        completed_at=now - timedelta(seconds=completed_ago),
    )
    db.add(step)
    db.commit()
    db.close()
    return step


def test_sweep_redispatches_run_whose_next_step_was_lost(session_factory, graph):
    """워커가 재시작되며 다음 스텝 메시지가 유실되면 스텝 행이 아예 없어 RUNNING 스텝 기반
    판정에 안 걸린다 — 한참 활동이 없으면 완료된 스텝에서 다시 이어 붙인다."""
    _completed_step(session_factory, graph, "a", completed_ago=3600)
    _completed_step(session_factory, graph, "b", completed_ago=3600)

    with patch("app.pipeline.tasks.workflow.run_workflow_step") as task:
        result = _sweep(session_factory)

    assert str(graph["run"].id) in result["redispatched_run_ids"]
    assert task.apply_async.call_count == 1
    assert task.apply_async.call_args.kwargs["args"] == [str(graph["run"].id), str(graph["blocks"]["merge"].id)]


def test_sweep_does_not_redispatch_recently_active_run(session_factory, graph):
    """다음 스텝이 큐에서 순서를 기다리는 중일 수 있으므로 최근 활동한 run은 건드리지 않는다."""
    _completed_step(session_factory, graph, "a", completed_ago=5)
    _completed_step(session_factory, graph, "b", completed_ago=5)

    with patch("app.pipeline.tasks.workflow.run_workflow_step") as task:
        result = _sweep(session_factory)

    assert str(graph["run"].id) not in result["redispatched_run_ids"]
    assert task.apply_async.call_count == 0


def test_sweep_does_not_redispatch_run_with_a_step_in_flight(session_factory, graph):
    _completed_step(session_factory, graph, "b", completed_ago=3600)
    _running_step(session_factory, graph, started_ago=5)

    with patch("app.pipeline.tasks.workflow.run_workflow_step") as task:
        result = _sweep(session_factory)

    assert str(graph["run"].id) not in result["redispatched_run_ids"]
    assert task.apply_async.call_count == 0


def _pending_step(session_factory, graph, name: str, created_ago: int) -> WorkflowRunStep:
    db = session_factory()
    step = WorkflowRunStep(
        id=uuid4(), run_id=graph["run"].id, block_instance_id=graph["blocks"][name].id,
        status="PENDING", created_at=datetime.utcnow() - timedelta(seconds=created_ago),
    )
    db.add(step)
    db.commit()
    db.close()
    return step


def test_sweep_redispatches_a_stale_pending_step_whose_message_was_lost_again(session_factory, graph):
    """재디스패치한 메시지까지 워커 재시작으로 유실되면 PENDING 스텝만 남는다 — 오래된 PENDING도 다시 낸다."""
    step = _pending_step(session_factory, graph, "a", created_ago=3600)

    with patch("app.pipeline.tasks.workflow.run_workflow_step") as task:
        result = _sweep(session_factory)

    assert str(graph["run"].id) in result["redispatched_run_ids"]
    assert task.apply_async.call_args.kwargs["args"] == [str(graph["run"].id), str(graph["blocks"]["a"].id)]
    db = session_factory()
    assert (datetime.utcnow() - db.get(WorkflowRunStep, step.id).created_at.replace(tzinfo=None)).total_seconds() < 120
    db.close()


def test_sweep_does_not_redispatch_a_fresh_pending_step(session_factory, graph):
    _pending_step(session_factory, graph, "a", created_ago=5)

    with patch("app.pipeline.tasks.workflow.run_workflow_step") as task:
        result = _sweep(session_factory)

    assert str(graph["run"].id) not in result["redispatched_run_ids"]
    assert task.apply_async.call_count == 0


def test_sweep_does_not_redispatch_a_pending_merge_step(session_factory, graph):
    """merge의 PENDING은 다른 업스트림을 기다리는 정상 상태라 오래돼도 단독으로 다시 내지 않는다."""
    _pending_step(session_factory, graph, "merge", created_ago=3600)

    with patch("app.pipeline.tasks.workflow.run_workflow_step") as task:
        result = _sweep(session_factory)

    assert str(graph["run"].id) not in result["redispatched_run_ids"]
    assert task.apply_async.call_count == 0


def test_completing_a_run_clears_the_stale_error_message_on_the_document(session_factory, graph):
    """실패 후 재처리가 성공해 INDEXED가 됐는데 이전 실패 사유가 문서에 남아 있으면 안 된다."""
    db = session_factory()
    db.execute(Document.__table__.update().where(Document.id == graph["document"].id)
               .values(status="FAILED", error_message="이전 실패", active_run_id=graph["run"].id))
    db.commit()
    db.close()

    db = session_factory()
    with patch("app.pipeline.tasks.workflow._maybe_trigger_analysis"):
        _maybe_complete_run(db, str(graph["run"].id))
    db.close()

    doc = _document(session_factory, graph["document"].id)
    assert doc.status == "INDEXED"
    assert doc.error_message is None


def test_sweep_does_not_overwrite_step_that_finished_meanwhile(session_factory, graph):
    """sweeper가 step을 읽은 뒤 다른 워커가 COMPLETED로 만들면(조건부 UPDATE) 덮어쓰지 않는다."""
    step = _running_step(session_factory, graph, started_ago=100_000)
    original_get = Session.get

    def finish_then_get(self, entity, ident, *args, **kwargs):
        if entity is WorkflowBlockInstance:
            other = session_factory()
            other.execute(WorkflowRunStep.__table__.update()
                          .where(WorkflowRunStep.id == step.id).values(status="COMPLETED"))
            other.commit()
            other.close()
        return original_get(self, entity, ident, *args, **kwargs)

    with patch.object(Session, "get", finish_then_get):
        result = _sweep(session_factory)

    assert str(graph["run"].id) not in result["swept_run_ids"]
    db = session_factory()
    assert db.get(WorkflowRunStep, step.id).status == "COMPLETED"
    assert db.get(WorkflowRun, graph["run"].id).status == "RUNNING"
    db.close()


# ---- run_workflow_step: 실패 처리 / 세션 반납 / 종결 run -------------------------------------


class _BoomBlock:
    block_version = "1.0.0"

    def run(self, context):
        raise RuntimeError("boom")


def _add_block(session_factory, graph, block_type: str) -> WorkflowBlockInstance:
    db = session_factory()
    block = WorkflowBlockInstance(id=uuid4(), version_id=graph["version"].id, block_type=block_type, config={})
    db.add(block)
    db.commit()
    db.close()
    return block


def _execute_step(session_factory, graph, block) -> tuple[object, list[Session]]:
    from app.pipeline.tasks.workflow import run_workflow_step

    opened: list[Session] = []

    def factory() -> Session:
        session = session_factory()
        opened.append(session)
        return session

    with patch("app.db.session.get_sync_db", side_effect=factory):
        result = run_workflow_step.apply(args=[str(graph["run"].id), str(block.id)], throw=False)
    return result, opened


def test_unexpected_block_error_fails_step_run_and_document_and_releases_session(
    session_factory, graph, monkeypatch
):
    monkeypatch.setitem(__import__("app.pipeline.blocks.registry", fromlist=["BLOCK_REGISTRY"]).BLOCK_REGISTRY,
                        "boom", _BoomBlock)
    block = _add_block(session_factory, graph, "boom")
    _set_active(session_factory, graph["document"].id, graph["run"].id)

    result, opened = _execute_step(session_factory, graph, block)

    assert result.failed()
    db = session_factory()
    step = db.scalars(select(WorkflowRunStep).where(WorkflowRunStep.block_instance_id == block.id)).one()
    assert step.status == "FAILED" and "boom" in step.error_message
    assert db.get(WorkflowRun, graph["run"].id).status == "FAILED"
    assert db.get(Document, graph["document"].id).status == "FAILED"
    db.close()
    assert opened and all(not s.in_transaction() for s in opened), "세션이 반납되지 않았다"


def test_step_is_skipped_when_run_already_failed(session_factory, graph):
    db = session_factory()
    db.execute(WorkflowRun.__table__.update().where(WorkflowRun.id == graph["run"].id).values(status="FAILED"))
    db.commit()
    db.close()

    result, _ = _execute_step(session_factory, graph, graph["blocks"]["a"])

    assert result.result == {"status": "SKIPPED"}
    assert _merge_steps(session_factory, graph["run"].id, graph["blocks"]["a"].id) == []


# ---- chunk_split: 재분할은 삭제+삽입이 한 트랜잭션 --------------------------------------------


def _old_chunk(session_factory, graph) -> str:
    from app.db.models.document_chunk import DocumentChunk

    db = session_factory()
    chunk = DocumentChunk(
        id=uuid4(), document_id=graph["document"].id, run_id=graph["run"].id,
        chunk_order=0, chunk_text="이전 실행 청크", original_text="이전 실행 청크",
    )
    db.add(chunk)
    db.commit()
    db.close()
    return str(chunk.id)


def _chunk_ids(session_factory, document_id) -> list[str]:
    from app.db.models.document_chunk import DocumentChunk

    db = session_factory()
    try:
        return [str(i) for i in db.scalars(select(DocumentChunk.id).where(DocumentChunk.document_id == document_id))]
    finally:
        db.close()


def _run_chunk_split(session_factory, graph):
    from app.pipeline.blocks.base import BlockContext
    from app.pipeline.blocks.storage_blocks import ChunkSplitBlock

    db = session_factory()
    db.execute(Document.__table__.update().where(Document.id == graph["document"].id)
               .values(parsed_text="가나다라마바사. " * 40))
    db.commit()
    db.close()
    context = BlockContext(
        run_id=str(graph["run"].id), block_instance_id=str(graph["blocks"]["a"].id),
        document_id=str(graph["document"].id), config={"strategy": "fixed"},
    )
    with patch("app.db.session.get_sync_db", side_effect=lambda: session_factory()):
        return ChunkSplitBlock().run(context)


def test_chunk_split_replaces_previous_chunks(session_factory, graph):
    old = _old_chunk(session_factory, graph)

    result = _run_chunk_split(session_factory, graph)

    after = _chunk_ids(session_factory, graph["document"].id)
    assert result.output["chunk_count"] >= 1
    assert old not in after
    assert set(result.output["chunk_ids"]) <= set(after)


def test_chunk_split_failure_keeps_previous_chunks(session_factory, graph):
    old = _old_chunk(session_factory, graph)

    with patch("app.pipeline.blocks.chunk_strategies._estimate_token_count", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            _run_chunk_split(session_factory, graph)

    assert _chunk_ids(session_factory, graph["document"].id) == [old]


# ---- 캐시 키: 원본 체크섬이 바뀌면 캐시를 재사용하지 않는다 -----------------------------------


def test_cache_key_changes_when_file_content_changes():
    from app.pipeline.tasks.workflow import _compute_cache_key

    def key(file_hash):
        return _compute_cache_key("doc", "input", "text_extract", "1.0.0", {}, file_hash=file_hash)

    assert key("a" * 64) == key("a" * 64)
    assert key("a" * 64) != key("b" * 64)


# ---- text_extract: 세션이 깨진 채 실패해도 원래 오류가 보존되고 임시파일이 남지 않는다 ---------


def test_text_extract_failure_with_poisoned_session_reports_original_error(session_factory, graph):
    import glob
    import tempfile
    from pathlib import Path

    from sqlalchemy import text

    from app.db.models.processing_job import ProcessingJob
    from app.pipeline.blocks.base import BlockContext, BlockExecutionError
    from app.pipeline.blocks.extraction_blocks import TextExtractBlock

    def poison_session(db, doc):
        # 실패한 SQL 때문에 세션이 PendingRollback 상태가 된 상황을 재현한다.
        db.execute(text("select 1/0"))

    class FakeAdapter:
        def extract(self, path, options):  # pragma: no cover — 도달 전에 실패한다
            raise AssertionError

    before = set(glob.glob(str(Path(tempfile.gettempdir()) / "*.pdf")))
    context = BlockContext(
        run_id=str(graph["run"].id), block_instance_id=str(graph["blocks"]["a"].id),
        document_id=str(graph["document"].id), config={},
    )
    try:
        with patch("app.db.session.get_sync_db", side_effect=lambda: session_factory()), \
             patch("app.services.storage.storage_service.download_file", return_value=b"%PDF-1.4"), \
             patch("app.pipeline.adapters.get_adapter", return_value=FakeAdapter()), \
             patch("app.pipeline.tasks.process._resolve_vision_credentials", side_effect=poison_session):
            with pytest.raises(BlockExecutionError) as caught:
                TextExtractBlock().run(context)

        assert caught.value.error_code == "TEXT_EXTRACTION_FAILED"
        assert "division by zero" in str(caught.value)
        db = session_factory()
        job = db.scalars(select(ProcessingJob).where(ProcessingJob.document_id == graph["document"].id)).one()
        assert job.status == "FAILED"
        db.close()
        assert set(glob.glob(str(Path(tempfile.gettempdir()) / "*.pdf"))) == before
    finally:
        cleanup = session_factory()
        cleanup.query(ProcessingJob).filter(ProcessingJob.document_id == graph["document"].id).delete()
        cleanup.commit()
        cleanup.close()


# ---- continue_processing: 새 벡터가 준비되기 전에는 기존 Qdrant 인덱스를 지우지 않는다 ---------


def test_continue_processing_keeps_existing_vectors_when_embedding_fails(session_factory, graph):
    from unittest.mock import MagicMock

    from app.db.models.processing_job import ProcessingJob
    from app.pipeline.tasks.process import continue_processing

    db = session_factory()
    db.execute(Document.__table__.update().where(Document.id == graph["document"].id)
               .values(parsed_text="가나다라마바사. " * 40))
    db.commit()
    db.close()
    qdrant = MagicMock()
    try:
        with patch("app.db.session.get_sync_db", side_effect=lambda: session_factory()), \
             patch("app.services.qdrant_service.qdrant_service", qdrant), \
             patch("app.services.embedding.get_embedding_provider", side_effect=RuntimeError("model down")):
            result = continue_processing.apply(args=[str(graph["document"].id)], throw=False)

        assert result.failed()
        qdrant.delete_by_document.assert_not_called()
        qdrant.upsert_points.assert_not_called()
    finally:
        cleanup = session_factory()
        cleanup.query(ProcessingJob).filter(ProcessingJob.document_id == graph["document"].id).delete()
        cleanup.commit()
        cleanup.close()
