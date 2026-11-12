"""골든쿼리와 평가 실행 API. 평가는 워커에서 채팅과 같은 검색 경로로 돈다(services/golden_eval.py)."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.api.v1.permissions import check_collection_access
from app.db.models.document import Document
from app.db.models.golden_eval_run import GoldenEvalRun
from app.db.models.golden_query import GoldenQuery
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.golden_query import (
    GoldenEvalRunListResponse,
    GoldenEvalRunRequest,
    GoldenEvalRunResponse,
    GoldenQueryCreate,
    GoldenQueryListResponse,
    GoldenQueryResponse,
    GoldenQueryUpdate,
)
from app.services.access_policy import build_access_context, load_document_facts, visible_document_ids
from app.services.audit import log_audit
from app.services.golden_eval import RUN_DONE, TRIGGER_MANUAL, enqueue_run, new_run

router = APIRouter()

_RUN_LIST_LIMIT = 20
# 컬렉션당 골든 쿼리 상한. 평가 한 번이 질의 수만큼 검색을 돌리므로 묶어 둔다
MAX_GOLDEN_QUERIES_PER_COLLECTION = 100
_MASKED_SCORES = {"precision": None, "recall": None, "hit": None, "reciprocal_rank": None,
                  "first_hit_rank": None, "masked": True}


async def _visible_ids(db: AsyncSession, user: User, document_ids: set[str]) -> tuple[set[str], set[str]]:
    """(있는 문서 id, 그중 요청자가 볼 수 있는 id)."""
    if not document_ids:
        return set(), set()
    facts = await load_document_facts(db, sorted(document_ids))
    ctx = await build_access_context(db, user)
    return set(facts), {str(i) for i in visible_document_ids(ctx, facts)}


async def _check_expected_documents(
    db: AsyncSession, collection_id: UUID, document_ids: list[UUID], user: User
) -> None:
    """기대 문서는 이 컬렉션에 있고 요청자가 볼 수 있는 문서여야 한다. 다른 컬렉션이나 볼 수 없는
    문서 id로 존재 여부를 떠보는 일을 막으려고 두 경우 모두 같은 메시지를 쓴다."""
    wanted = {str(d) for d in document_ids}
    found = {
        str(i) for i in (
            await db.scalars(
                select(Document.id).where(Document.id.in_(wanted), Document.collection_id == str(collection_id))
            )
        ).all()
    }
    _, visible = await _visible_ids(db, user, found)
    if found != wanted or visible != wanted:
        raise HTTPException(status_code=400, detail="기대 문서는 이 컬렉션에서 볼 수 있는 문서여야 합니다")


def _mask_result(row: dict, existing: set[str], visible: set[str]) -> dict:
    """요청자가 볼 수 없는 문서 id는 지우고, 기대 문서 중 볼 수 없는 것이 있으면 점수도 가린다.
    적중 여부와 순위만으로도 숨은 문서가 검색되는지 알 수 있기 때문이다."""
    expected = [str(i) for i in row.get("expected_document_ids") or []]
    hidden_expected = any(i in existing and i not in visible for i in expected)
    masked = {
        **row,
        "expected_document_ids": [i for i in expected if i in visible],
        "retrieved_document_ids": [str(i) for i in row.get("retrieved_document_ids") or [] if str(i) in visible],
    }
    return {**masked, **_MASKED_SCORES} if hidden_expected else masked


async def _masked_runs(db: AsyncSession, user: User, runs: list[GoldenEvalRun]) -> list[dict]:
    """평가 결과를 요청자 권한으로 가려 돌려준다. 자동 평가는 컬렉션 소유자 권한으로 돌기 때문에
    저장된 결과에는 열람자가 볼 수 없는 문서가 섞여 있을 수 있다."""
    ids: set[str] = set()
    for run in runs:
        for row in run.results or []:
            ids.update(str(i) for i in row.get("expected_document_ids") or [])
            ids.update(str(i) for i in row.get("retrieved_document_ids") or [])
    existing, visible = await _visible_ids(db, user, ids)
    out = []
    for run in runs:
        data = GoldenEvalRunResponse.model_validate(run).model_dump()
        if run.results is not None:
            rows = [_mask_result(dict(r), existing, visible) for r in run.results]
            data["results"] = rows
            if data.get("regression"):
                masked_ids = {str(r["golden_query_id"]) for r in rows if r.get("masked")}
                detail = dict(data["regression"])
                detail["lost_queries"] = [
                    q for q in detail.get("lost_queries") or [] if str(q.get("golden_query_id")) not in masked_ids
                ]
                data["regression"] = detail
        out.append(data)
    return out


async def _golden_query_or_404(db: AsyncSession, collection_id: UUID, query_id: UUID) -> GoldenQuery:
    gq = await db.scalar(
        select(GoldenQuery).where(GoldenQuery.id == str(query_id), GoldenQuery.collection_id == str(collection_id))
    )
    if not gq:
        raise HTTPException(status_code=404, detail="Golden query not found")
    return gq


@router.post("/collections/{collection_id}/golden-queries", response_model=GoldenQueryResponse)
async def create_golden_query(
    collection_id: UUID,
    data: GoldenQueryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await check_collection_access(db, collection_id, current_user, min_role="editor")
    count = await db.scalar(
        select(func.count()).select_from(GoldenQuery).where(GoldenQuery.collection_id == str(collection_id))
    )
    if (count or 0) >= MAX_GOLDEN_QUERIES_PER_COLLECTION:
        raise HTTPException(
            status_code=409, detail=f"골든 쿼리는 컬렉션당 {MAX_GOLDEN_QUERIES_PER_COLLECTION}개까지 만들 수 있습니다"
        )
    await _check_expected_documents(db, collection_id, data.expected_document_ids, current_user)
    gq = GoldenQuery(
        collection_id=str(collection_id),
        query=data.query,
        expected_document_ids=[str(d) for d in data.expected_document_ids],
        created_by=str(current_user.id),
    )
    db.add(gq)
    await db.flush()
    log_audit(db, str(current_user.id), "golden_query.create", "collection", str(collection_id),
              detail={"golden_query_id": str(gq.id)})
    await db.commit()
    await db.refresh(gq)
    return gq


@router.get("/collections/{collection_id}/golden-queries", response_model=GoldenQueryListResponse)
async def list_golden_queries(
    collection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await check_collection_access(db, collection_id, current_user, min_role="viewer")
    rows = (
        await db.scalars(
            select(GoldenQuery)
            .where(GoldenQuery.collection_id == str(collection_id))
            .order_by(GoldenQuery.created_at.desc())
        )
    ).all()
    return {"items": rows}


@router.patch("/collections/{collection_id}/golden-queries/{query_id}", response_model=GoldenQueryResponse)
async def update_golden_query(
    collection_id: UUID,
    query_id: UUID,
    data: GoldenQueryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """질의나 기대 문서를 고친다(v3 마일스톤 7). 이미 끝난 평가 결과는 그대로 둔다."""
    await check_collection_access(db, collection_id, current_user, min_role="editor")
    gq = await _golden_query_or_404(db, collection_id, query_id)
    if data.query is not None:
        gq.query = data.query
    if data.expected_document_ids is not None:
        await _check_expected_documents(db, collection_id, data.expected_document_ids, current_user)
        gq.expected_document_ids = [str(d) for d in data.expected_document_ids]
    log_audit(db, str(current_user.id), "golden_query.update", "collection", str(collection_id),
              detail={"golden_query_id": str(gq.id)})
    await db.commit()
    await db.refresh(gq)
    return gq


@router.delete("/collections/{collection_id}/golden-queries/{query_id}", status_code=204)
async def delete_golden_query(
    collection_id: UUID,
    query_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await check_collection_access(db, collection_id, current_user, min_role="editor")
    gq = await _golden_query_or_404(db, collection_id, query_id)
    await db.delete(gq)
    log_audit(db, str(current_user.id), "golden_query.delete", "collection", str(collection_id),
              detail={"golden_query_id": str(query_id)})
    await db.commit()


@router.post("/collections/{collection_id}/golden-eval-runs", response_model=GoldenEvalRunResponse)
async def run_golden_eval(
    collection_id: UUID,
    data: GoldenEvalRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """평가를 예약하고 바로 돌려준다(status=QUEUED). 결과는 실행 목록이나 단건 조회로 확인한다.
    평가는 요청자의 권한으로 검색한다. 질의 수만큼 검색을 돌리는 작업이라 편집 권한이 필요하다."""
    from app.core.rate_limit import enforce_user_rate_limit
    from app.services.search_settings import DEFAULT_SEARCH_SETTINGS, stored_collection_search_settings

    enforce_user_rate_limit(str(current_user.id), "golden_eval", limit=5, window_seconds=60)
    await check_collection_access(db, collection_id, current_user, min_role="editor")
    has_queries = await db.scalar(
        select(GoldenQuery.id).where(GoldenQuery.collection_id == str(collection_id)).limit(1)
    )
    if not has_queries:
        raise HTTPException(status_code=400, detail="평가할 골든 쿼리가 없습니다. 먼저 골든 쿼리를 추가하세요.")
    stored = await stored_collection_search_settings(db, str(collection_id))
    top_k = data.top_k or (stored or DEFAULT_SEARCH_SETTINGS).top_k
    run = new_run(str(collection_id), str(current_user.id), top_k, TRIGGER_MANUAL)
    db.add(run)
    await db.commit()
    await db.refresh(run)
    enqueue_run(str(run.id))
    return run


@router.get("/collections/{collection_id}/golden-eval-runs", response_model=GoldenEvalRunListResponse)
async def list_golden_eval_runs(
    collection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await check_collection_access(db, collection_id, current_user, min_role="viewer")
    rows = (
        await db.scalars(
            select(GoldenEvalRun)
            .where(GoldenEvalRun.collection_id == str(collection_id))
            .order_by(GoldenEvalRun.created_at.desc())
            .limit(_RUN_LIST_LIMIT)
        )
    ).all()
    return {"items": await _masked_runs(db, current_user, list(rows))}


async def _run_or_404(db: AsyncSession, collection_id: UUID, run_id: UUID) -> GoldenEvalRun:
    run = await db.scalar(
        select(GoldenEvalRun).where(
            GoldenEvalRun.id == str(run_id), GoldenEvalRun.collection_id == str(collection_id)
        )
    )
    if not run:
        raise HTTPException(status_code=404, detail="Golden eval run not found")
    return run


@router.get("/collections/{collection_id}/golden-eval-runs/{run_id}", response_model=GoldenEvalRunResponse)
async def get_golden_eval_run(
    collection_id: UUID,
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await check_collection_access(db, collection_id, current_user, min_role="viewer")
    run = await _run_or_404(db, collection_id, run_id)
    return (await _masked_runs(db, current_user, [run]))[0]


@router.post(
    "/collections/{collection_id}/golden-eval-runs/{run_id}/baseline", response_model=GoldenEvalRunResponse
)
async def set_golden_baseline(
    collection_id: UUID,
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """이 실행을 회귀 비교의 기준으로 삼는다. 끝난(DONE) 실행만 기준이 될 수 있다."""
    await check_collection_access(db, collection_id, current_user, min_role="editor")
    run = await _run_or_404(db, collection_id, run_id)
    if run.status != RUN_DONE:
        raise HTTPException(status_code=409, detail="끝난 평가만 기준으로 삼을 수 있습니다")
    await db.execute(
        update(GoldenEvalRun)
        .where(GoldenEvalRun.collection_id == str(collection_id), GoldenEvalRun.id != run.id)
        .values(is_baseline=False)
        .execution_options(synchronize_session=False)
    )
    run.is_baseline = True
    log_audit(
        db, str(current_user.id), "golden_eval.set_baseline", "collection", str(collection_id),
        detail={"run_id": str(run.id)},
    )
    await db.commit()
    await db.refresh(run)
    return (await _masked_runs(db, current_user, [run]))[0]
