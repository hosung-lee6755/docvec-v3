"""Unit coverage for the golden-query evaluation logic in
app.api.v1.endpoints.golden_queries — this is the precision/recall math and
chunk-to-distinct-document dedup behind the 2c sales-readiness benchmark, and
had zero automated tests before this."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.golden_queries import _DOC_DEDUP_MULTIPLIER, run_golden_eval
from app.schemas.golden_query import GoldenEvalRunRequest


class _AllowAll:
    def __contains__(self, _item) -> bool:
        return True


@pytest.fixture(autouse=True)
def _stub_access_policy():
    """권한 판정은 test_access_policy*.py가 검증한다 — 여기선 precision/recall 계산만 본다."""
    with (
        patch("app.services.access_policy.build_access_context", new=AsyncMock(return_value=MagicMock())),
        patch("app.services.access_policy.qdrant_access_filter", return_value=None),
        patch("app.services.access_policy.load_document_facts", new=AsyncMock(return_value=[])),
        patch("app.services.access_policy.visible_document_ids", return_value=_AllowAll()),
    ):
        yield


def _hit(document_id: str) -> dict:
    return {"payload": {"document_id": document_id}}


def _golden_query(expected_ids: list[str], query: str = "q1"):
    return MagicMock(id=uuid4(), query=query, expected_document_ids=expected_ids)


@pytest.mark.asyncio
async def test_run_golden_eval_computes_precision_and_recall():
    doc_a, doc_b, doc_c = "doc-a", "doc-b", "doc-c"
    gq = _golden_query(expected_ids=[doc_a, doc_b])
    db = AsyncMock()
    db.add = MagicMock()
    db.scalars.return_value = MagicMock(all=MagicMock(return_value=[gq]))

    # Ranked hits: doc_a, doc_c, doc_a again (dup), doc_b — with top_k=2 the
    # dedup loop should stop after 2 DISTINCT documents: [doc_a, doc_c].
    hits = [_hit(doc_a), _hit(doc_c), _hit(doc_a), _hit(doc_b)]

    with (
        patch("app.api.v1.endpoints.golden_queries.check_collection_access", new=AsyncMock()),
        patch("app.api.v1.endpoints.golden_queries._embed_query", return_value=[0.1, 0.2]),
        patch("app.services.qdrant_service.qdrant_service.search", return_value=hits) as mock_search,
    ):
        result = await run_golden_eval(
            uuid4(), GoldenEvalRunRequest(top_k=2), db, MagicMock()
        )

    assert result.mean_precision == pytest.approx(0.5)
    assert result.mean_recall == pytest.approx(0.5)
    assert mock_search.call_args.kwargs["limit"] == 2 * _DOC_DEDUP_MULTIPLIER
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_run_golden_eval_dedups_repeated_chunks_from_same_document():
    doc_a = "doc-a"
    gq = _golden_query(expected_ids=[doc_a])
    db = AsyncMock()
    db.add = MagicMock()
    db.scalars.return_value = MagicMock(all=MagicMock(return_value=[gq]))

    # Five chunks, all from the same document — top_k=1 must still resolve to
    # exactly one distinct retrieved document, not stop after one raw hit.
    hits = [_hit(doc_a) for _ in range(5)]

    with (
        patch("app.api.v1.endpoints.golden_queries.check_collection_access", new=AsyncMock()),
        patch("app.api.v1.endpoints.golden_queries._embed_query", return_value=[0.1]),
        patch("app.services.qdrant_service.qdrant_service.search", return_value=hits),
    ):
        result = await run_golden_eval(
            uuid4(), GoldenEvalRunRequest(top_k=1), db, MagicMock()
        )

    assert result.mean_precision == pytest.approx(1.0)
    assert result.mean_recall == pytest.approx(1.0)
    assert result.results[0]["retrieved_document_ids"] == [doc_a]


@pytest.mark.asyncio
async def test_run_golden_eval_rejects_empty_golden_query_set():
    db = AsyncMock()
    db.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))

    with patch("app.api.v1.endpoints.golden_queries.check_collection_access", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await run_golden_eval(uuid4(), GoldenEvalRunRequest(top_k=5), db, MagicMock())

    assert exc_info.value.status_code == 400
