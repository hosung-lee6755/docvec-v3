"""골든 평가 지표·회귀·워커 실행·예약(v3 마일스톤 7, services/golden_eval.py). 실행은 실제 Postgres."""
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.collection import Collection
from app.db.models.document import Document
from app.db.models.golden_eval_run import GoldenEvalRun
from app.db.models.golden_query import GoldenQuery
from app.db.models.user import User
from app.services import golden_eval as ge
from tests.conftest import TEST_DATABASE_URL

SYNC_URL = TEST_DATABASE_URL.replace("+asyncpg", "+psycopg2")


# ------------------------------------------------------------------ 지표(순수)

def test_score_query_matches_by_lineage_so_a_new_version_still_counts():
    lineage_of = {"v1": "L", "v2": "L", "x": "X"}

    out = ge.score_query(["v1"], ["v2", "x"], lineage_of)

    assert out == {"precision": 0.5, "recall": 1.0, "hit": True, "reciprocal_rank": 1.0, "first_hit_rank": 1}


def test_score_query_rank_and_empty_results():
    assert ge.score_query(["a"], ["b", "a"], {})["reciprocal_rank"] == pytest.approx(0.5)
    assert ge.score_query(["a"], [], {}) == {
        "precision": 0.0, "recall": 0.0, "hit": False, "reciprocal_rank": 0.0, "first_hit_rank": None,
    }


def test_score_query_counts_two_chunks_of_one_lineage_once():
    out = ge.score_query(["a", "b"], ["a1", "a2"], {"a1": "a", "a2": "a"})

    assert (out["precision"], out["recall"]) == (1.0, 0.5)


def test_summarize_means_and_empty():
    results = [
        {"precision": 1.0, "recall": 1.0, "hit": True, "reciprocal_rank": 1.0},
        {"precision": 0.0, "recall": 0.0, "hit": False, "reciprocal_rank": 0.0},
    ]
    assert ge.summarize(results) == {
        "mean_precision": 0.5, "mean_recall": 0.5, "mean_hit_rate": 0.5, "mean_mrr": 0.5,
    }
    assert ge.summarize([])["mean_hit_rate"] == 0.0


def _row(qid, hit, recall=None, rr=None, query="q"):
    return {"golden_query_id": qid, "query": query, "hit": hit,
            "recall": float(hit) if recall is None else recall, "reciprocal_rank": float(hit) if rr is None else rr}


def _baseline(results=None, **fields):
    rows = results if results is not None else [_row("q1", True), _row("q2", True)]
    return SimpleNamespace(id=uuid4(), results=rows, **fields)


def test_compare_flags_drop_beyond_tolerance_and_lists_lost_queries():
    results = [_row("q1", False, query="첫 질의"), _row("q2", True, query="둘째")]

    out = ge.compare_with_baseline(_baseline(), {}, results, tolerance=0.05)

    assert out["is_regression"] is True
    assert out["detail"]["regressed_metrics"] == ["mean_hit_rate", "mean_recall", "mean_mrr"]
    assert out["detail"]["lost_queries"] == [{"golden_query_id": "q1", "query": "첫 질의"}]
    assert out["detail"]["metrics"]["mean_hit_rate"]["delta"] == pytest.approx(-0.5)
    assert out["detail"]["compared_queries"] == 2


def test_compare_drop_equal_to_tolerance_is_not_a_regression():
    base = _baseline([_row("q1", True, recall=1.0, rr=1.0)])
    results = [_row("q1", True, recall=0.95, rr=0.95)]

    assert ge.compare_with_baseline(base, {}, results, tolerance=0.05)["is_regression"] is False


def test_compare_uses_only_queries_present_in_both_runs():
    """새로 추가한 질의가 놓치거나 기준에 있던 질의를 지워도 회귀로 보지 않는다."""
    base = _baseline([_row("q1", True), _row("gone", True)])
    results = [_row("q1", True), _row("new", False)]

    out = ge.compare_with_baseline(base, {}, results, tolerance=0.05)

    assert out["is_regression"] is False
    assert out["detail"]["compared_queries"] == 1
    assert out["detail"]["metrics"]["mean_hit_rate"] == {"baseline": 1.0, "current": 1.0, "delta": 0.0}


def test_compare_skips_metrics_missing_from_an_old_baseline():
    old = _baseline([{"golden_query_id": "q1", "query": "q", "recall": 0.5}])

    out = ge.compare_with_baseline(old, {}, [_row("q1", False, recall=0.5)], tolerance=0.05)

    assert set(out["detail"]["metrics"]) == {"mean_recall"}
    assert out["is_regression"] is False


# ------------------------------------------------------------ 실제 DB

@pytest.fixture(scope="module")
def session_factory():
    engine = create_engine(SYNC_URL)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def world(session_factory):
    db = session_factory()
    owner = User(id=uuid4(), email=f"{uuid4()}@example.com", username="owner", hashed_password="!",
                 role="viewer", is_active=True)
    db.add(owner)
    db.flush()
    coll = Collection(id=uuid4(), name="g", qdrant_collection_name=f"q-{uuid4()}", created_by=owner.id)
    db.add(coll)
    db.flush()

    def doc(**fields):
        d = Document(id=uuid4(), filename="a.txt", original_filename="a.txt", file_size=1, mime_type="text/plain",
                     file_hash="h" * 64, minio_key=f"{uuid4()}/a.txt", status="INDEXED", created_by=owner.id,
                     collection_id=coll.id, **fields)
        db.add(d)
        db.flush()
        return d

    v1 = doc(lifecycle_state="superseded")
    v2 = doc(lineage_id=v1.lineage_id, version_number=2)
    gq = GoldenQuery(id=uuid4(), collection_id=coll.id, query="매출 목표", expected_document_ids=[str(v1.id)],
                     created_by=owner.id)
    db.add(gq)
    db.commit()
    yield SimpleNamespace(db=db, owner=owner, coll=coll, v1=v1, v2=v2, gq=gq)
    db.close()


def _queued(world) -> GoldenEvalRun:
    run = ge.new_run(str(world.coll.id), str(world.owner.id), 5, "manual")
    world.db.add(run)
    world.db.commit()
    return run


def _evaluate(world, run, chunks):
    with patch("app.pipeline.tasks.chat._retrieve_chunks", return_value=chunks) as retrieve:
        ge.evaluate_run_sync(world.db, str(run.id))
    return retrieve


def test_first_run_scores_by_lineage_and_becomes_baseline(world):
    run = _queued(world)

    retrieve = _evaluate(world, run, [{"document_id": str(world.v2.id)}, {"document_id": str(world.v2.id)}])

    world.db.refresh(run)
    assert (run.status, run.is_baseline, run.is_regression) == ("DONE", True, None)
    assert (run.mean_hit_rate, run.mean_recall, run.mean_mrr) == (1.0, 1.0, 1.0)
    assert run.results[0]["retrieved_document_ids"] == [str(world.v2.id)]
    assert run.search_settings["top_k"] == 5 and run.completed_at is not None
    # 채팅과 같은 검색 경로를 실행자 권한으로, 조회 통계는 남기지 않고 부른다
    args, kwargs = retrieve.call_args
    assert args[1:4] == (str(world.owner.id), "매출 목표", str(world.coll.id))
    assert kwargs == {"limit": 5, "record_stats": False}


def test_later_run_that_misses_is_a_regression_against_the_baseline(world):
    first = _queued(world)
    _evaluate(world, first, [{"document_id": str(world.v2.id)}])
    second = _queued(world)

    _evaluate(world, second, [])

    world.db.refresh(second)
    assert second.is_baseline is False and second.is_regression is True
    assert second.regression["baseline_run_id"] == str(first.id)
    assert second.regression["lost_queries"] == [{"golden_query_id": str(world.gq.id), "query": "매출 목표"}]


def test_retrieval_failure_marks_run_failed_with_reason(world):
    run = _queued(world)

    with patch("app.pipeline.tasks.chat._retrieve_chunks", side_effect=RuntimeError("qdrant down")):
        ge.evaluate_run_sync(world.db, str(run.id))

    world.db.refresh(run)
    assert run.status == "FAILED" and "qdrant down" in run.error_message


def test_only_queued_runs_are_evaluated(world):
    run = _queued(world)
    run.status = "DONE"
    world.db.commit()

    retrieve = _evaluate(world, run, [])

    retrieve.assert_not_called()


def test_schedule_creates_one_pending_auto_run_as_owner_and_debounces(world):
    with patch.object(ge, "enqueue_run") as enqueue:
        first = ge.schedule_golden_eval_sync(world.db, str(world.coll.id), "new_version")
        second = ge.schedule_golden_eval_sync(world.db, str(world.coll.id), "dictionary")

    assert first is not None and second is None
    run = world.db.get(GoldenEvalRun, first)
    assert (run.status, run.trigger, str(run.created_by)) == ("QUEUED", "new_version", str(world.owner.id))
    enqueue.assert_called_once()
    assert enqueue.call_args.args == (first, ge.settings.golden_auto_eval_delay_seconds)


def test_schedule_skips_collections_without_golden_queries(world):
    world.db.delete(world.gq)
    world.db.commit()

    with patch.object(ge, "enqueue_run") as enqueue:
        assert ge.schedule_golden_eval_sync(world.db, str(world.coll.id), "lifecycle") is None
    enqueue.assert_not_called()


def test_stale_runs_are_failed_and_stop_blocking_auto_scheduling(world):
    from datetime import datetime, timedelta

    old = ge.new_run(str(world.coll.id), str(world.owner.id), 5, "dictionary")
    old.created_at = datetime.utcnow() - timedelta(minutes=ge.STALE_RUN_MINUTES + 5)
    fresh = _queued(world)
    world.db.add(old)
    world.db.commit()

    with patch.object(ge, "enqueue_run"):
        # 오래된 대기 실행은 새 자동 예약을 막지 않는다
        assert ge.schedule_golden_eval_sync(world.db, str(world.coll.id), "lifecycle") is not None
    assert ge.fail_stale_runs_sync(world.db) == 1

    world.db.refresh(old)
    world.db.refresh(fresh)
    assert old.status == "FAILED" and old.error_message and old.completed_at is not None
    assert fresh.status == "QUEUED"


def test_pending_manual_run_does_not_block_auto_scheduling(world):
    _queued(world)

    with patch.object(ge, "enqueue_run"):
        assert ge.schedule_golden_eval_sync(world.db, str(world.coll.id), "search_settings") is not None
    pending = world.db.scalars(
        select(GoldenEvalRun).where(GoldenEvalRun.collection_id == world.coll.id, GoldenEvalRun.status == "QUEUED")
    ).all()
    assert len(pending) == 2
