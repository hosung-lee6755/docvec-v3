from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.schemas.search import SearchRequest
from app.services import search_service


def _make_hit(chunk_id: str, score: float, document_id: str, text: str) -> dict:
    return {
        "id": chunk_id,
        "score": score,
        "payload": {"document_id": document_id, "text": text},
    }


@pytest.mark.asyncio
async def test_perform_search_vector_mode_returns_results_and_logs_history():
    user_id = uuid4()
    document_id = str(uuid4())
    db = AsyncMock()
    db.add = MagicMock()  # AsyncSession.add() is sync; avoid an unawaited-coroutine warning

    with (
        patch("app.services.search_service.get_embedding_provider") as mock_provider,
        patch("app.services.search_service.qdrant_service") as mock_qdrant,
    ):
        mock_provider.return_value.embed.return_value = [[0.1, 0.2, 0.3]]
        mock_qdrant.search.return_value = [
            _make_hit("chunk-1", 0.9, document_id, "hello world"),
        ]

        results = await search_service.perform_search(
            db, user_id, SearchRequest(query="hello", limit=5, mode="vector")
        )

    assert len(results) == 1
    assert results[0].chunk_id == "chunk-1"
    assert results[0].bm25_score is None
    db.add.assert_called_once()
    logged = db.add.call_args[0][0]
    assert logged.query == "hello"
    assert logged.search_mode == "vector"
    assert logged.result_count == 1
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_perform_search_hybrid_mode_reranks_and_trims_to_limit():
    user_id = uuid4()
    document_id = str(uuid4())
    db = AsyncMock()
    db.add = MagicMock()  # AsyncSession.add() is sync; avoid an unawaited-coroutine warning

    with (
        patch("app.services.search_service.get_embedding_provider") as mock_provider,
        patch("app.services.search_service.qdrant_service") as mock_qdrant,
    ):
        mock_provider.return_value.embed.return_value = [[0.1, 0.2, 0.3]]
        mock_qdrant.search.return_value = [
            _make_hit(f"chunk-{i}", 0.5, document_id, f"content number {i}")
            for i in range(8)
        ]

        results = await search_service.perform_search(
            db, user_id, SearchRequest(query="content number 3", limit=3, mode="hybrid")
        )

    assert len(results) == 3
    assert all(r.final_score is not None for r in results)
    called_limit = mock_qdrant.search.call_args.kwargs["limit"]
    assert called_limit == 3 * search_service._HYBRID_CANDIDATE_MULTIPLIER


@pytest.mark.asyncio
async def test_list_search_history_queries_by_user_id():
    user_id = uuid4()
    db = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.scalars.return_value.all.return_value = []
    db.execute.return_value = scalar_result

    result = await search_service.list_search_history(db, user_id, limit=10)

    assert result == []
    db.execute.assert_awaited_once()
