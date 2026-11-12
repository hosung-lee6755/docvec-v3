"""골든쿼리 평가(v3 마일스톤 7, .claude/plans/m7-data-lifecycle.plan.md).

평가는 채팅과 같은 검색 경로(pipeline.tasks.chat._retrieve_chunks)로 워커에서 돈다. 컬렉션 검색 설정,
재순위, 사전 확장, 권한 필터, 현재 버전 조건이 모두 같다. 실행자의 권한으로 검색하므로 결과에
실행자가 볼 수 없는 문서는 나오지 않는다. 자동 재평가는 컬렉션 소유자의 권한으로 돈다.

일치 판정은 문서 계보(lineage) 단위다. 기대 문서가 새 버전으로 바뀌어도 같은 문서로 본다.
질의마다 정밀도, 재현율, 적중 여부(hit@k), 역순위(첫 정답의 1/순위)를 내고 평균을 낸다.

회귀: 컬렉션의 기준 실행(is_baseline)과 비교해 적중률, 재현율, MRR 가운데 하나라도
settings.golden_regression_tolerance보다 크게 떨어지면 회귀다. 기준에서 맞혔는데 이번에 놓친 질의도
기록한다. 기준이 없으면 그 실행이 기준이 된다.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from sqlalchemy import exists, select

from app.core.config import settings
from app.db.models.collection import Collection
from app.db.models.document import Document
from app.db.models.golden_eval_run import GoldenEvalRun
from app.db.models.golden_query import GoldenQuery

logger = logging.getLogger(__name__)

RUN_QUEUED, RUN_RUNNING, RUN_DONE, RUN_FAILED = "QUEUED", "RUNNING", "DONE", "FAILED"
TRIGGER_MANUAL = "manual"
AUTO_TRIGGERS = ("search_settings", "dictionary", "new_version", "lifecycle", "document_deleted")
REGRESSION_METRICS = ("mean_hit_rate", "mean_recall", "mean_mrr")
# 허용치와 똑같이 떨어진 경우를 부동소수 오차(0.95 - 1.0 = -0.0500…04)로 회귀라 하지 않게 둔다
_FLOAT_SLACK = 1e-9
_ERROR_MAX_LEN = 500
# 이보다 오래 대기·실행 중인 평가는 워커가 죽었거나 메시지를 잃은 것으로 보고 실패로 정리한다
STALE_RUN_MINUTES = 30
# 회귀 지표와 질의별 값의 대응
_PER_QUERY_KEY = {"mean_hit_rate": "hit", "mean_recall": "recall", "mean_mrr": "reciprocal_rank"}


# ---------------------------------------------------------------------------
# 지표(순수 함수)
# ---------------------------------------------------------------------------

def _ordered_unique(values: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for v in values:
        if v and v not in seen:
            seen.append(v)
    return seen


def score_query(expected_ids: list, retrieved_ids: list[str], lineage_of: dict[str, str]) -> dict:
    """retrieved_ids는 순위 순서의 문서 id다. 같은 계보는 한 번만 센다."""
    expected = _ordered_unique(lineage_of.get(str(e), str(e)) for e in expected_ids)
    retrieved = _ordered_unique(lineage_of.get(str(r), str(r)) for r in retrieved_ids)
    expected_set = set(expected)
    overlap = expected_set & set(retrieved)
    rank = next((i + 1 for i, lineage in enumerate(retrieved) if lineage in expected_set), 0)
    return {
        "precision": len(overlap) / len(retrieved) if retrieved else 0.0,
        "recall": len(overlap) / len(expected) if expected else 0.0,
        "hit": rank > 0,
        "reciprocal_rank": 1.0 / rank if rank else 0.0,
        "first_hit_rank": rank or None,
    }


def summarize(results: list[dict]) -> dict:
    n = len(results)
    if not n:
        return {"mean_precision": 0.0, "mean_recall": 0.0, "mean_hit_rate": 0.0, "mean_mrr": 0.0}
    return {
        "mean_precision": sum(r["precision"] for r in results) / n,
        "mean_recall": sum(r["recall"] for r in results) / n,
        "mean_hit_rate": sum(1 for r in results if r["hit"]) / n,
        "mean_mrr": sum(r["reciprocal_rank"] for r in results) / n,
    }


def _mean_of(rows: list[dict], key: str) -> float | None:
    values = [r.get(key) for r in rows]
    if not values or any(v is None for v in values):
        return None
    return sum(float(v) for v in values) / len(values)


def compare_with_baseline(baseline: GoldenEvalRun, means: dict, results: list[dict], tolerance: float) -> dict:
    """기준 실행과 비교한다. 두 실행에 모두 있는 질의만 비교해, 질의를 추가·삭제·수정한 것이 회귀로
    보이지 않게 한다. 기준에 질의별 값이 없는 지표(마일스톤 7 이전 실행의 적중률, MRR)는 건너뛴다."""
    base_rows = {str(r.get("golden_query_id")): r for r in baseline.results or []}
    common = [r for r in results if str(r["golden_query_id"]) in base_rows]
    base_common = [base_rows[str(r["golden_query_id"])] for r in common]
    metrics: dict[str, dict] = {}
    regressed: list[str] = []
    for name in REGRESSION_METRICS:
        key = _PER_QUERY_KEY[name]
        base = _mean_of(base_common, key)
        current = _mean_of(common, key)
        if base is None or current is None:
            continue
        delta = current - base
        metrics[name] = {"baseline": base, "current": current, "delta": delta}
        if -delta > tolerance + _FLOAT_SLACK:
            regressed.append(name)
    baseline_hits = {str(r.get("golden_query_id")) for r in baseline.results or [] if r.get("hit")}
    lost = [
        {"golden_query_id": r["golden_query_id"], "query": r["query"]}
        for r in results
        if not r["hit"] and str(r["golden_query_id"]) in baseline_hits
    ]
    return {
        "is_regression": bool(regressed),
        "detail": {
            "baseline_run_id": str(baseline.id),
            "tolerance": tolerance,
            "metrics": metrics,
            "regressed_metrics": regressed,
            "lost_queries": lost,
            "compared_queries": len(common),
        },
    }


# ---------------------------------------------------------------------------
# 실행(워커, sync 세션)
# ---------------------------------------------------------------------------

def _lineage_map(db, document_ids: set[str]) -> dict[str, str]:
    if not document_ids:
        return {}
    rows = db.execute(
        select(Document.id, Document.lineage_id).where(Document.id.in_(sorted(document_ids)))
    ).all()
    return {str(doc_id): str(lineage) for doc_id, lineage in rows}


def _retrieved_document_ids(chunks: list[dict]) -> list[str]:
    return _ordered_unique(str(c.get("document_id")) for c in chunks if c.get("document_id"))


def evaluate_run_sync(db, run_id: str) -> GoldenEvalRun | None:
    """대기 중인 실행 하나를 끝까지 돌린다. 실패하면 FAILED와 사유를 남긴다."""
    from app.pipeline.tasks.chat import _retrieve_chunks
    from app.services.search_settings import collection_search_settings_sync

    run = db.get(GoldenEvalRun, run_id)
    if run is None or run.status != RUN_QUEUED:
        return run
    run.status = RUN_RUNNING
    db.commit()
    collection_id = str(run.collection_id)
    try:
        search = collection_search_settings_sync(db, collection_id)
        queries = db.scalars(select(GoldenQuery).where(GoldenQuery.collection_id == collection_id)).all()
        retrieved_by_query: dict[str, list[str]] = {}
        for gq in queries:
            chunks = _retrieve_chunks(
                db, str(run.created_by), gq.query, collection_id, limit=run.top_k, record_stats=False,
            )
            retrieved_by_query[str(gq.id)] = _retrieved_document_ids(chunks)
        all_ids = {str(d) for gq in queries for d in gq.expected_document_ids}
        all_ids |= {d for ids in retrieved_by_query.values() for d in ids}
        lineage_of = _lineage_map(db, all_ids)
        results = [
            {
                "golden_query_id": str(gq.id),
                "query": gq.query,
                "expected_document_ids": [str(d) for d in gq.expected_document_ids],
                "retrieved_document_ids": retrieved_by_query[str(gq.id)],
                **score_query(gq.expected_document_ids, retrieved_by_query[str(gq.id)], lineage_of),
            }
            for gq in queries
        ]
        _finish(db, run, results, summarize(results), search.model_dump())
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("golden eval failed: run=%s", run_id)
        run = db.get(GoldenEvalRun, run_id)
        run.status = RUN_FAILED
        run.error_message = f"{type(exc).__name__}: {exc}"[:_ERROR_MAX_LEN]
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
    return run


def _finish(db, run: GoldenEvalRun, results: list[dict], means: dict, search_settings: dict) -> None:
    run.results = results
    run.mean_precision = means["mean_precision"]
    run.mean_recall = means["mean_recall"]
    run.mean_hit_rate = means["mean_hit_rate"]
    run.mean_mrr = means["mean_mrr"]
    run.search_settings = search_settings
    baseline = db.scalar(
        select(GoldenEvalRun).where(
            GoldenEvalRun.collection_id == run.collection_id,
            GoldenEvalRun.is_baseline.is_(True),
            GoldenEvalRun.id != run.id,
        )
    )
    if baseline is None:
        run.is_baseline = True
        run.is_regression = None
        run.regression = None
    else:
        comparison = compare_with_baseline(baseline, means, results, settings.golden_regression_tolerance)
        run.is_regression = comparison["is_regression"]
        run.regression = comparison["detail"]
    run.status = RUN_DONE
    run.completed_at = datetime.now(timezone.utc)
    db.commit()


# ---------------------------------------------------------------------------
# 예약 — 골든쿼리가 있는 컬렉션만, 이미 대기 중인 자동 실행이 있으면 새로 만들지 않는다
# ---------------------------------------------------------------------------

def _has_queries_stmt(collection_id: str):
    return select(exists().where(GoldenQuery.collection_id == collection_id))


def _stale_cutoff() -> datetime:
    return (datetime.now(timezone.utc) - timedelta(minutes=STALE_RUN_MINUTES)).replace(tzinfo=None)


def _pending_auto_stmt(collection_id: str):
    # 오래된 대기 실행은 잃어버린 것으로 보고 새 예약을 막지 않는다
    return select(
        exists().where(
            GoldenEvalRun.collection_id == collection_id,
            GoldenEvalRun.status == RUN_QUEUED,
            GoldenEvalRun.trigger != TRIGGER_MANUAL,
            GoldenEvalRun.created_at > _stale_cutoff(),
        )
    )


def fail_stale_runs_sync(db) -> int:
    """오래 대기하거나 실행 중인 평가를 실패로 정리한다. 화면의 진행 표시(폴링)도 여기서 끝난다."""
    stale = db.scalars(
        select(GoldenEvalRun).where(
            GoldenEvalRun.status.in_([RUN_QUEUED, RUN_RUNNING]),
            GoldenEvalRun.created_at < _stale_cutoff(),
        )
    ).all()
    for run in stale:
        run.status = RUN_FAILED
        run.error_message = f"{STALE_RUN_MINUTES}분 안에 끝나지 않아 중단된 것으로 처리했습니다"
        run.completed_at = datetime.now(timezone.utc)
    if stale:
        db.commit()
    return len(stale)


def enqueue_run(run_id: str, countdown: int = 0) -> None:
    from app.pipeline.tasks.golden_eval import run_golden_eval

    run_golden_eval.apply_async(args=[run_id], countdown=countdown)


def new_run(collection_id: str, created_by: str, top_k: int, trigger: str) -> GoldenEvalRun:
    return GoldenEvalRun(
        collection_id=collection_id, created_by=created_by, top_k=top_k, status=RUN_QUEUED, trigger=trigger,
    )


def schedule_golden_eval_sync(db, collection_id: str, trigger: str) -> str | None:
    from app.services.search_settings import collection_search_settings_sync

    if not db.scalar(_has_queries_stmt(collection_id)) or db.scalar(_pending_auto_stmt(collection_id)):
        return None
    owner = db.scalar(select(Collection.created_by).where(Collection.id == collection_id))
    if owner is None:
        return None
    run = new_run(collection_id, str(owner), collection_search_settings_sync(db, collection_id).top_k, trigger)
    db.add(run)
    db.commit()
    enqueue_run(str(run.id), settings.golden_auto_eval_delay_seconds)
    return str(run.id)


async def schedule_golden_eval(db, collection_id: str, trigger: str) -> str | None:
    from app.services.search_settings import DEFAULT_SEARCH_SETTINGS, stored_collection_search_settings

    if not await db.scalar(_has_queries_stmt(collection_id)) or await db.scalar(_pending_auto_stmt(collection_id)):
        return None
    owner = await db.scalar(select(Collection.created_by).where(Collection.id == collection_id))
    if owner is None:
        return None
    stored = await stored_collection_search_settings(db, collection_id)
    run = new_run(collection_id, str(owner), (stored or DEFAULT_SEARCH_SETTINGS).top_k, trigger)
    db.add(run)
    await db.commit()
    enqueue_run(str(run.id), settings.golden_auto_eval_delay_seconds)
    return str(run.id)


async def schedule_for_all_collections(db, trigger: str) -> list[str]:
    """사전처럼 모든 컬렉션에 영향을 주는 변경용. 골든쿼리가 있는 컬렉션만 예약한다."""
    collection_ids = (await db.scalars(select(GoldenQuery.collection_id).distinct())).all()
    scheduled = []
    for cid in collection_ids:
        run_id = await schedule_golden_eval(db, str(cid), trigger)
        if run_id:
            scheduled.append(run_id)
    return scheduled
