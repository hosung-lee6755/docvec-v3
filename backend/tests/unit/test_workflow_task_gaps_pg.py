"""워크플로 태스크 보강 테스트 — 실제 Postgres.

run_workflow_step의 성공/캐시 적중/검토 대기/재시도/영구 실패 경로, 산출물 오프로딩,
resume_workflow_run, 보조 함수(_update_document_status/_fail_document) 중
기존 테스트가 다루지 않던 분기를 고정한다. 블록 구현은 가짜 블록으로 대체한다."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.block_execution_cache import BlockExecutionCache
from app.db.models.document import Document
from app.db.models.user import User
from app.db.models.workflow import (
    WorkflowBlockInstance,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowVersion,
)
from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep
from app.pipeline.blocks.base import BlockExecutionError, BlockResult
from app.pipeline.blocks.registry import BLOCK_REGISTRY
from app.pipeline.tasks import workflow as wf
from tests.conftest import TEST_DATABASE_URL

SYNC_URL = TEST_DATABASE_URL.replace("+asyncpg", "+psycopg2")


@pytest.fixture(scope="module")
def session_factory():
    engine = create_engine(SYNC_URL)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def env(session_factory):
    """user/workflow/version/document + helpers to add blocks, edges and runs."""
    started = datetime.utcnow()
    db = session_factory()
    user = User(id=uuid4(), email=f"{uuid4()}@example.com", username="gap", hashed_password="!",
                role="viewer", is_active=True)
    db.add(user)
    db.flush()
    definition = WorkflowDefinition(id=uuid4(), name="gap", kind="PREPROCESS", created_by=user.id)
    db.add(definition)
    db.flush()
    version = WorkflowVersion(id=uuid4(), workflow_id=definition.id, version_number=1,
                              created_by=user.id)
    db.add(version)
    db.flush()
    document = Document(
        id=uuid4(), filename="a.pdf", original_filename="a.pdf", file_size=1,
        mime_type="application/pdf", file_hash="f" * 64, minio_key=f"{uuid4()}/a.pdf",
        status="PARSING", created_by=user.id,
    )
    db.add(document)
    db.commit()
    db.close()
    ctx = SimpleNamespace(factory=session_factory, user=user, version=version, document=document)

    def add_block(block_type, config=None):
        s = session_factory()
        block = WorkflowBlockInstance(id=uuid4(), version_id=version.id, block_type=block_type,
                                      config=config or {})
        s.add(block)
        s.commit()
        s.close()
        return block

    def add_edge(src, dst):
        s = session_factory()
        s.add(WorkflowEdge(id=uuid4(), version_id=version.id, from_block_id=src.id,
                           to_block_id=dst.id))
        s.commit()
        s.close()

    def add_run(status="QUEUED", active=True):
        s = session_factory()
        run = WorkflowRun(id=uuid4(), version_id=version.id, document_id=document.id,
                          status=status)
        s.add(run)
        s.commit()
        if active:
            s.execute(Document.__table__.update().where(Document.id == document.id)
                      .values(active_run_id=run.id))
            s.commit()
        s.close()
        return run

    def execute(run, block):
        with patch("app.db.session.get_sync_db", side_effect=lambda: session_factory()):
            return wf.run_workflow_step.apply(args=[str(run.id), str(block.id)], throw=False)

    def reload(model, pk):
        s = session_factory()
        try:
            return s.get(model, pk)
        finally:
            s.close()

    def steps(run):
        s = session_factory()
        try:
            return list(s.scalars(select(WorkflowRunStep).where(WorkflowRunStep.run_id == run.id)))
        finally:
            s.close()

    ctx.add_block, ctx.add_edge, ctx.add_run = add_block, add_edge, add_run
    ctx.execute, ctx.reload, ctx.steps = execute, reload, steps
    yield ctx

    c = session_factory()
    c.execute(Document.__table__.update().where(Document.id == document.id)
              .values(active_run_id=None))
    run_ids = list(c.scalars(select(WorkflowRun.id).where(WorkflowRun.version_id == version.id)))
    c.query(WorkflowRunStep).filter(WorkflowRunStep.run_id.in_(run_ids)).delete(
        synchronize_session=False)
    c.query(WorkflowRun).filter(WorkflowRun.version_id == version.id).delete()
    c.query(BlockExecutionCache).filter(BlockExecutionCache.created_at >= started).delete()
    c.query(Document).filter(Document.id == document.id).delete()
    c.query(WorkflowEdge).filter(WorkflowEdge.version_id == version.id).delete()
    c.query(WorkflowBlockInstance).filter(WorkflowBlockInstance.version_id == version.id).delete()
    c.query(WorkflowVersion).filter(WorkflowVersion.id == version.id).delete()
    c.query(WorkflowDefinition).filter(WorkflowDefinition.id == definition.id).delete()
    c.query(User).filter(User.id == user.id).delete()
    c.commit()
    c.close()


class FakeBlock:
    """Configurable stand-in registered under a block_type for one test."""

    block_version = "1.0.0"
    calls = 0
    result = BlockResult(output={"ok": True})
    error: Exception | None = None

    def run(self, context):
        type(self).calls += 1
        if type(self).error is not None:
            raise type(self).error
        return type(self).result


def _fake_block(monkeypatch, block_type, *, result=None, error=None):
    cls = type("Fake_" + block_type, (FakeBlock,), {
        "calls": 0,
        "result": result or BlockResult(output={"ok": True}),
        "error": error,
    })
    monkeypatch.setitem(BLOCK_REGISTRY, block_type, cls)
    return cls


# ------------------------------------------------- output storage (pure/mock)


def test_store_step_output_keeps_small_output_inline():
    step = SimpleNamespace(id="s1", output=None, artifact_key="stale", output_hash=None)

    out = wf._store_step_output("r1", step, {"a": 1})

    assert out == {"a": 1}
    assert step.output == {"a": 1}
    assert step.artifact_key is None
    assert step.output_hash == wf._hash_bytes(wf._serialize({"a": 1}))


def test_store_step_output_offloads_large_output_to_artifact_bucket():
    big = {"text": "x" * (wf._ARTIFACT_INLINE_THRESHOLD_BYTES + 10)}
    step = SimpleNamespace(id="s1", output=None, artifact_key=None, output_hash=None)
    storage = MagicMock()

    with patch("app.services.storage.storage_service", storage):
        out = wf._store_step_output("r1", step, big)

    assert out is big  # callers still get the full output, not the reduced reference
    key = "runs/r1/s1/output.json"
    storage.upload_file.assert_called_once()
    assert storage.upload_file.call_args.args[1] == key
    assert storage.upload_file.call_args.args[3] == "application/json"
    assert step.artifact_key == key
    assert step.output == {"artifact": key, "output_hash": step.output_hash, "_artifact_only": True}


def test_resolve_output_loads_artifact_only_outputs_and_passes_inline_through():
    storage = MagicMock()
    storage.download_file.return_value = b'{"big": 1}'
    reduced = {"artifact": "runs/r/s/output.json", "_artifact_only": True}

    with patch("app.services.storage.storage_service", storage):
        assert wf._resolve_output(reduced) == {"big": 1}
        assert wf._resolve_output({"inline": 1}) == {"inline": 1}
        assert wf._resolve_output(None) == {}
        assert wf._resolve_output({"_artifact_only": True}) == {"_artifact_only": True}

    storage.download_file.assert_called_once()


# --------------------------------------------------------- document status


def test_update_document_status_maps_block_type_to_document_status(env):
    run = env.add_run()
    db = env.factory()
    live_run = db.get(WorkflowRun, run.id)

    wf._update_document_status(db, live_run, "text_extract")
    assert db.get(Document, env.document.id).status == "PARSING"
    wf._update_document_status(db, live_run, "chunk_split")
    assert db.get(Document, env.document.id).status == "CHUNKING"
    db.close()


def test_update_document_status_ignores_unmapped_blocks_and_runs_without_document(env):
    db = MagicMock()

    wf._update_document_status(db, SimpleNamespace(document_id="d"), "summarize")
    wf._update_document_status(db, SimpleNamespace(document_id=None), "text_extract")

    db.get.assert_not_called()


def test_fail_document_is_noop_without_document_or_when_document_missing():
    db = MagicMock()
    wf._fail_document(db, SimpleNamespace(document_id=None, id="r"), "msg")
    db.get.assert_not_called()

    db.get.return_value = None
    wf._fail_document(db, SimpleNamespace(document_id="d", id="r"), "msg")  # must not raise


def test_fail_document_truncates_error_message_to_500_chars():
    doc = SimpleNamespace(active_run_id=None, status="PARSING", error_message=None)
    db = MagicMock()
    db.get.return_value = doc

    wf._fail_document(db, SimpleNamespace(document_id="d", id="r1"), "e" * 900)

    assert doc.status == "FAILED" and len(doc.error_message) == 500
    assert doc.active_run_id == "r1"


# ------------------------------------------------------ run_workflow_step


def test_step_not_found_for_unknown_run_or_block(env):
    block = env.add_block("okblock")

    result = env.execute(SimpleNamespace(id=uuid4()), block)

    assert result.result == {"status": "NOT_FOUND"}


def test_successful_terminal_block_completes_step_run_and_document(env, monkeypatch):
    cls = _fake_block(monkeypatch, "okblock", result=BlockResult(
        output={"n": 1}, warnings=["w"], metrics={"ms": 5}))
    block = env.add_block("okblock")
    run = env.add_run(status="QUEUED")

    result = env.execute(run, block)

    assert result.result == {"status": "COMPLETED", "output": {"n": 1}}
    (step,) = env.steps(run)
    assert step.status == "COMPLETED" and step.output == {"n": 1}
    assert step.warnings == ["w"] and step.metrics == {"ms": 5}
    assert step.started_at is not None and step.completed_at >= step.started_at
    assert step.cached in (False, None)
    finished = env.reload(WorkflowRun, run.id)
    assert finished.status == "COMPLETED" and finished.started_at is not None
    assert env.reload(Document, env.document.id).status == "INDEXED"
    assert cls.calls == 1


def test_step_dispatches_downstream_block_after_success(env, monkeypatch):
    _fake_block(monkeypatch, "okblock")
    a, b = env.add_block("okblock"), env.add_block("okblock")
    env.add_edge(a, b)
    run = env.add_run()

    with patch("app.pipeline.tasks.workflow.run_workflow_step.apply_async") as dispatch:
        env.execute(run, a)

    assert dispatch.call_args.kwargs["args"] == [str(run.id), str(b.id)]
    assert env.reload(WorkflowRun, run.id).status == "RUNNING"  # not complete: b pending


def test_large_block_output_is_offloaded_but_downstream_sees_full_output(env, monkeypatch):
    big = {"text": "y" * (wf._ARTIFACT_INLINE_THRESHOLD_BYTES + 100)}
    _fake_block(monkeypatch, "okblock", result=BlockResult(output=big))
    block = env.add_block("okblock")
    run = env.add_run()
    storage = MagicMock()

    with patch("app.services.storage.storage_service", storage):
        result = env.execute(run, block)

    assert result.result["output"] == big
    (step,) = env.steps(run)
    assert step.artifact_key == f"runs/{run.id}/{step.id}/output.json"
    assert step.output["_artifact_only"] is True
    storage.upload_file.assert_called_once()


def test_requires_review_pauses_run_and_document_without_advancing(env, monkeypatch):
    _fake_block(monkeypatch, "okblock", result=BlockResult(output={"q": 1}, requires_review=True))
    a, b = env.add_block("okblock"), env.add_block("okblock")
    env.add_edge(a, b)
    run = env.add_run()

    with patch("app.pipeline.tasks.workflow.run_workflow_step.apply_async") as dispatch:
        result = env.execute(run, a)

    assert result.result["status"] == "WAITING_REVIEW"
    dispatch.assert_not_called()
    assert env.reload(WorkflowRun, run.id).status == "WAITING_REVIEW"
    assert env.reload(Document, env.document.id).status == "WAITING_REVIEW"


def test_cache_safe_block_result_is_replayed_for_the_next_run_without_rerunning(env, monkeypatch):
    cls = _fake_block(monkeypatch, "file_validate", result=BlockResult(output={"valid": True}))
    block = env.add_block("file_validate")
    first, second = env.add_run(), env.add_run()

    env.execute(first, block)
    env.execute(second, block)

    assert cls.calls == 1  # second run served from block_execution_cache
    (step,) = env.steps(second)
    assert step.cached is True and step.status == "COMPLETED"
    assert step.output == {"valid": True}
    db = env.factory()
    (entry,) = [e for e in db.scalars(select(BlockExecutionCache))
                if e.output_summary == {"valid": True} and e.hit_count == 1]
    assert entry.last_hit_at is not None
    db.close()


def test_cached_requires_review_still_pauses_the_run(env, monkeypatch):
    _fake_block(monkeypatch, "file_validate",
                result=BlockResult(output={"needs": "review"}, requires_review=True))
    block = env.add_block("file_validate")
    first, second = env.add_run(), env.add_run()

    env.execute(first, block)
    result = env.execute(second, block)

    assert result.result["status"] == "WAITING_REVIEW"
    assert env.reload(WorkflowRun, second.id).status == "WAITING_REVIEW"


def test_permanent_block_error_fails_immediately_without_retry(env, monkeypatch):
    cls = _fake_block(monkeypatch, "okblock", error=BlockExecutionError(
        "지원하지 않는 형식", "FILE_UNSUPPORTED", permanent=True))
    block = env.add_block("okblock", {"retryCount": 5})
    run = env.add_run()

    result = env.execute(run, block)

    assert result.failed()
    assert cls.calls == 1
    (step,) = env.steps(run)
    assert step.status == "FAILED" and step.error_code == "FILE_UNSUPPORTED"
    assert step.error_message == "지원하지 않는 형식"
    failed = env.reload(WorkflowRun, run.id)
    assert failed.status == "FAILED" and failed.error_message == "지원하지 않는 형식"
    doc = env.reload(Document, env.document.id)
    assert doc.status == "FAILED" and doc.error_message == "지원하지 않는 형식"


def test_transient_block_error_retries_up_to_retry_count_then_fails(env, monkeypatch):
    cls = _fake_block(monkeypatch, "okblock", error=BlockExecutionError(
        "일시적 오류", "STORAGE_FAILED"))
    block = env.add_block("okblock", {"retryCount": 1})
    run = env.add_run()

    result = env.execute(run, block)

    assert result.failed()
    assert cls.calls == 2  # initial attempt + exactly one retry
    (step,) = env.steps(run)
    assert step.status == "FAILED" and step.error_code == "STORAGE_FAILED"
    assert step.completed_at is not None
    assert env.reload(WorkflowRun, run.id).status == "FAILED"


def test_zero_retry_count_fails_on_first_transient_error(env, monkeypatch):
    cls = _fake_block(monkeypatch, "okblock", error=BlockExecutionError("x", "OCR_FAILED"))
    block = env.add_block("okblock", {"retryCount": 0})
    run = env.add_run()

    env.execute(run, block)

    assert cls.calls == 1
    assert env.steps(run)[0].status == "FAILED"


def test_stale_failure_does_not_overwrite_document_owned_by_newer_run(env, monkeypatch):
    _fake_block(monkeypatch, "okblock", error=BlockExecutionError("old", "FILE_UNSUPPORTED", True))
    block = env.add_block("okblock")
    old = env.add_run(active=False)
    newer = env.add_run(status="RUNNING", active=True)  # document points at the live newer run

    env.execute(old, block)

    doc = env.reload(Document, env.document.id)
    assert str(doc.active_run_id) == str(newer.id)
    assert doc.status != "FAILED"
    assert env.reload(WorkflowRun, old.id).status == "FAILED"


def test_duplicate_dispatch_of_finished_step_returns_stored_output(env, monkeypatch):
    cls = _fake_block(monkeypatch, "okblock", result=BlockResult(output={"v": 2}))
    block = env.add_block("okblock")
    run = env.add_run()
    env.execute(run, block)

    again = env.execute(run, block)

    assert again.result == {"status": "COMPLETED", "output": {"v": 2}}
    assert cls.calls == 1


# --------------------------------------------------- resume_workflow_run


def _paused_run(env, monkeypatch):
    _fake_block(monkeypatch, "okblock")
    a, b = env.add_block("okblock"), env.add_block("okblock")
    env.add_edge(a, b)
    run = env.add_run(status="WAITING_REVIEW")
    s = env.factory()
    s.add(WorkflowRunStep(id=uuid4(), run_id=run.id, block_instance_id=a.id,
                          status="COMPLETED", output={"approved": True}))
    s.commit()
    s.close()
    return run, a, b


def _resume(env, run_id):
    with patch("app.db.session.get_sync_db", side_effect=lambda: env.factory()):
        return wf.resume_workflow_run.run(str(run_id))


def test_resume_continues_from_paused_block_and_marks_run_running(env, monkeypatch):
    run, _a, b = _paused_run(env, monkeypatch)

    with patch("app.pipeline.tasks.workflow.run_workflow_step.apply_async") as dispatch:
        result = _resume(env, run.id)

    assert result == {"status": "RESUMED"}
    assert dispatch.call_args.kwargs["args"] == [str(run.id), str(b.id)]
    assert env.reload(WorkflowRun, run.id).status == "RUNNING"


def test_resume_skips_runs_that_are_not_waiting_for_review(env):
    run = env.add_run(status="RUNNING")

    assert _resume(env, run.id) == {"status": "SKIPPED"}
    assert _resume(env, uuid4()) == {"status": "SKIPPED"}


def test_resume_reports_not_found_when_no_paused_step_exists(env):
    run = env.add_run(status="WAITING_REVIEW")  # no steps at all

    assert _resume(env, run.id) == {"status": "NOT_FOUND"}
    assert env.reload(WorkflowRun, run.id).status == "WAITING_REVIEW"


def test_find_paused_step_ignores_steps_whose_targets_already_exist(env, monkeypatch):
    run, a, b = _paused_run(env, monkeypatch)
    s = env.factory()
    s.add(WorkflowRunStep(id=uuid4(), run_id=run.id, block_instance_id=b.id, status="PENDING"))
    s.commit()

    assert wf._find_paused_step(s, str(run.id)) is None
    s.close()
