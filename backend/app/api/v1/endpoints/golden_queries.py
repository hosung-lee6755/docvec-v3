import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.api.v1.permissions import check_collection_access
from app.core.config import settings
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
)

router = APIRouter()

# Chunk-level over-fetch multiplier: qdrant_service.search returns chunks, and
# the same document can supply several of the top hits, so document-level
# top_k needs a wider chunk pool to actually surface top_k DISTINCT documents.
_DOC_DEDUP_MULTIPLIER = 5


@router.post("/collections/{collection_id}/golden-queries", response_model=GoldenQueryResponse)
async def create_golden_query(
    collection_id: UUID,
    data: GoldenQueryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await check_collection_access(db, collection_id, current_user, min_role="editor")
    gq = GoldenQuery(
        collection_id=str(collection_id),
        query=data.query,
        expected_document_ids=[str(d) for d in data.expected_document_ids],
        created_by=str(current_user.id),
    )
    db.add(gq)
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


@router.delete("/collections/{collection_id}/golden-queries/{query_id}", status_code=204)
async def delete_golden_query(
    collection_id: UUID,
    query_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await check_collection_access(db, collection_id, current_user, min_role="editor")
    gq = await db.scalar(
        select(GoldenQuery).where(
            GoldenQuery.id == str(query_id), GoldenQuery.collection_id == str(collection_id)
        )
    )
    if not gq:
        raise HTTPException(status_code=404, detail="Golden query not found")
    await db.delete(gq)
    await db.commit()


def _embed_query(query: str) -> list[float]:
    # Same offload-to-thread pattern as search_service.perform_search — the
    # embedding model's inference is synchronous/CPU-or-GPU-bound and must not
    # block the event loop.
    from app.services.embedding import get_embedding_provider

    return get_embedding_provider().embed([query])[0]


@router.post("/collections/{collection_id}/golden-eval-runs", response_model=GoldenEvalRunResponse)
async def run_golden_eval(
    collection_id: UUID,
    data: GoldenEvalRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Runs every golden query in the collection through the same vector
    search used by chat/search retrieval, scoring each against its
    expected_document_ids by precision/recall at top_k (document-level, not
    chunk-level). Runs inline rather than as a background job — a golden set
    is small (a handful to dozens of queries) so this stays well within
    request timeout, and the per-run result needs to come back synchronously
    for the UI to show right away."""
    from app.services.qdrant_service import qdrant_service

    await check_collection_access(db, collection_id, current_user, min_role="viewer")

    golden_queries = (
        await db.scalars(
            select(GoldenQuery).where(GoldenQuery.collection_id == str(collection_id))
        )
    ).all()
    if not golden_queries:
        raise HTTPException(
            status_code=400, detail="평가할 골든 쿼리가 없습니다. 먼저 골든 쿼리를 추가하세요."
        )

    results = []
    precision_sum = 0.0
    recall_sum = 0.0
    for gq in golden_queries:
        vector = await asyncio.to_thread(_embed_query, gq.query)
        hits = qdrant_service.search(
            collection=settings.qdrant_collection_name,
            vector=vector,
            limit=data.top_k * _DOC_DEDUP_MULTIPLIER,
            collection_id=str(collection_id),
        )

        retrieved_ids: list[str] = []
        for h in hits:
            doc_id = h["payload"].get("document_id")
            if doc_id and doc_id not in retrieved_ids:
                retrieved_ids.append(doc_id)
            if len(retrieved_ids) >= data.top_k:
                break

        expected_set = set(gq.expected_document_ids)
        retrieved_set = set(retrieved_ids)
        overlap = len(expected_set & retrieved_set)
        precision = overlap / len(retrieved_set) if retrieved_set else 0.0
        recall = overlap / len(expected_set) if expected_set else 0.0
        precision_sum += precision
        recall_sum += recall

        results.append({
            "golden_query_id": str(gq.id),
            "query": gq.query,
            "expected_document_ids": gq.expected_document_ids,
            "retrieved_document_ids": retrieved_ids,
            "precision": precision,
            "recall": recall,
        })

    run = GoldenEvalRun(
        collection_id=str(collection_id),
        created_by=str(current_user.id),
        top_k=data.top_k,
        mean_precision=precision_sum / len(golden_queries),
        mean_recall=recall_sum / len(golden_queries),
        results=results,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
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
            .limit(20)
        )
    ).all()
    return {"items": rows}
