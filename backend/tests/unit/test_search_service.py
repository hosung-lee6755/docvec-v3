from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.schemas.search import SearchRequest
from app.services import search_service
from app.services.access_policy import AccessContext


class _AllowAll:
    def __contains__(self, _item) -> bool:
        return True


@pytest.fixture(autouse=True)
def _stub_access_policy():
    """이 파일은 DB를 목으로 쓰는 검색 파이프라인(임베딩·BM25·MMR·이력) 테스트다.
    v3 권한 판정 자체는 test_access_policy*.py, test_access_qdrant_filter.py,
    test_access_leak_matrix.py가 실제 DB·Qdrant로 검증하므로 여기서는 통과시킨다."""
    ctx = AccessContext.create("u", ["col-1"], "Internal")
    with (
        patch.object(search_service, "build_access_context", new=AsyncMock(return_value=ctx)),
        patch.object(search_service, "load_document_facts", new=AsyncMock(return_value={})),
        patch.object(search_service, "retrievable_document_ids", return_value=_AllowAll()),
        # 쪽별 OCR 신뢰도 조회(v3 마일스톤 6)는 실제 DB 테스트가 맡는다
        patch.object(search_service, "page_confidences", new=AsyncMock(return_value={})),
    ):
        yield


def _make_hit(chunk_id: str, score: float, document_id: str, text: str) -> dict:
    return {
        "id": chunk_id,
        "score": score,
        "payload": {"document_id": document_id, "text": text},
    }


@pytest.mark.asyncio
async def test_perform_search_vector_mode_returns_results_and_logs_history():
    user = MagicMock(id=uuid4())
    document_id = str(uuid4())
    db = AsyncMock()
    db.add = MagicMock()  # AsyncSession.add() is sync; avoid an unawaited-coroutine warning

    with (
        patch("app.services.search_service.get_embedding_provider") as mock_provider,
        patch("app.services.search_service.qdrant_service") as mock_qdrant,
        patch(
            "app.services.search_service.accessible_collection_ids",
            new=AsyncMock(return_value=["col-1"]),
        ),
    ):
        mock_provider.return_value.embed.return_value = [[0.1, 0.2, 0.3]]
        mock_qdrant.search.return_value = [
            _make_hit("chunk-1", 0.9, document_id, "hello world"),
        ]

        response = await search_service.perform_search(
            db, user, SearchRequest(query="hello", limit=5, mode="vector")
        )

    assert len(response.items) == 1
    assert response.items[0].chunk_id == "chunk-1"
    assert response.items[0].bm25_score is None
    assert response.expanded_query == "hello"
    assert response.added_terms == []
    db.add.assert_called_once()
    logged = db.add.call_args[0][0]
    assert logged.query == "hello"
    assert logged.search_mode == "vector"
    assert logged.result_count == 1
    assert logged.result_document_ids == [document_id]
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_perform_search_hybrid_mode_reranks_and_trims_to_limit():
    user = MagicMock(id=uuid4())
    document_id = str(uuid4())
    db = AsyncMock()
    db.add = MagicMock()  # AsyncSession.add() is sync; avoid an unawaited-coroutine warning

    with (
        patch("app.services.search_service.get_embedding_provider") as mock_provider,
        patch("app.services.search_service.qdrant_service") as mock_qdrant,
        patch(
            "app.services.search_service.accessible_collection_ids",
            new=AsyncMock(return_value=["col-1"]),
        ),
    ):
        mock_provider.return_value.embed.return_value = [[0.1, 0.2, 0.3]]
        mock_qdrant.search.return_value = [
            _make_hit(f"chunk-{i}", 0.5, document_id, f"content number {i}")
            for i in range(8)
        ]

        response = await search_service.perform_search(
            db, user, SearchRequest(query="content number 3", limit=3, mode="hybrid")
        )

    assert len(response.items) == 3
    assert all(r.final_score is not None for r in response.items)
    called_limit = mock_qdrant.search.call_args.kwargs["limit"]
    assert called_limit == 3 * search_service._HYBRID_CANDIDATE_MULTIPLIER


@pytest.mark.asyncio
async def test_perform_search_diversify_requests_vectors_and_larger_pool():
    user = MagicMock(id=uuid4())
    document_id = str(uuid4())
    db = AsyncMock()
    db.add = MagicMock()

    with (
        patch("app.services.search_service.get_embedding_provider") as mock_provider,
        patch("app.services.search_service.qdrant_service") as mock_qdrant,
        patch(
            "app.services.search_service.accessible_collection_ids",
            new=AsyncMock(return_value=["col-1"]),
        ),
    ):
        mock_provider.return_value.embed.return_value = [[0.1, 0.2, 0.3]]
        mock_qdrant.search.return_value = [
            {
                "id": f"chunk-{i}",
                "score": 0.9 - i * 0.05,
                "payload": {"document_id": document_id, "text": f"content {i}"},
                "vector": [float(i), 0.0],
            }
            for i in range(6)
        ]

        response = await search_service.perform_search(
            db, user, SearchRequest(query="content", limit=2, mode="vector", diversify=True)
        )

    assert len(response.items) == 2
    assert mock_qdrant.search.call_args.kwargs["with_vectors"] is True
    called_limit = mock_qdrant.search.call_args.kwargs["limit"]
    assert called_limit == 2 * search_service._MMR_CANDIDATE_MULTIPLIER


@pytest.mark.asyncio
async def test_perform_search_rewrites_query_with_dictionary_synonym():
    user = MagicMock(id=uuid4())
    document_id = str(uuid4())
    db = AsyncMock()
    db.add = MagicMock()

    with (
        patch("app.services.search_service.get_embedding_provider") as mock_provider,
        patch("app.services.search_service.qdrant_service") as mock_qdrant,
        patch(
            "app.services.search_service.accessible_collection_ids",
            new=AsyncMock(return_value=["col-1"]),
        ),
        patch(
            "app.services.search_service.expand_query",
            return_value=("AI 도입 전략 인공지능", ["인공지능"]),
        ) as mock_expand,
    ):
        mock_provider.return_value.embed.return_value = [[0.1, 0.2, 0.3]]
        mock_qdrant.search.return_value = [
            _make_hit("chunk-1", 0.9, document_id, "hello world"),
        ]

        response = await search_service.perform_search(
            db, user, SearchRequest(query="AI 도입 전략", limit=5, mode="vector")
        )

    mock_expand.assert_called_once_with("AI 도입 전략")
    assert mock_provider.return_value.embed.call_args[0][0] == ["AI 도입 전략 인공지능"]
    assert response.expanded_query == "AI 도입 전략 인공지능"
    assert response.added_terms == ["인공지능"]
    # SearchHistory still logs what the user actually typed, not the rewrite
    logged = db.add.call_args[0][0]
    assert logged.query == "AI 도입 전략"


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


# -- 컬렉션 검색 설정과 근거(v3 마일스톤 6) --------------------------------------

@pytest.mark.asyncio
async def test_perform_search_follows_collection_settings_when_request_leaves_them_out():
    from app.services.search_settings import SearchSettings

    user = MagicMock(id=uuid4())
    document_id = str(uuid4())
    db = AsyncMock()
    db.add = MagicMock()
    collection_settings = SearchSettings(mode="hybrid", vector_weight=0.2, diversify=False, rerank=False)

    with (
        patch("app.services.search_service.get_embedding_provider") as mock_provider,
        patch("app.services.search_service.qdrant_service") as mock_qdrant,
        patch.object(search_service, "stored_collection_search_settings", new=AsyncMock(return_value=collection_settings)),
        patch.object(search_service, "page_confidences", new=AsyncMock(
            return_value={(document_id, 3): 0.2})),
    ):
        mock_provider.return_value.embed.return_value = [[0.1, 0.2, 0.3]]
        mock_qdrant.search.return_value = [
            {**_make_hit("c1", 0.5, document_id, "연차 휴가 규정"), "payload": {
                "document_id": document_id, "text": "연차 휴가 규정", "page_number": 3}},
        ]

        response = await search_service.perform_search(
            db, user, SearchRequest(query="연차 규정", limit=5, collection_id=uuid4())
        )

    item = response.items[0]
    # 하이브리드이고, 벡터 비중 0.2가 융합 점수에 쓰였다
    assert item.final_score == pytest.approx(0.2 * 0.5 + 0.8 * item.bm25_score)
    assert response.applied.mode == "hybrid" and response.applied.from_collection is True
    assert response.applied.rerank_in_chat is False
    assert "연차" in item.evidence["matched_terms"]
    assert item.evidence["low_ocr"] is True and item.evidence["ocr_confidence"] == 0.2
    assert db.add.call_args[0][0].search_mode == "hybrid"


@pytest.mark.asyncio
async def test_perform_search_request_overrides_collection_mode():
    user = MagicMock(id=uuid4())
    db = AsyncMock()
    db.add = MagicMock()

    with (
        patch("app.services.search_service.get_embedding_provider") as mock_provider,
        patch("app.services.search_service.qdrant_service") as mock_qdrant,
        patch("app.services.search_service.accessible_collection_ids", new=AsyncMock(return_value=["col-1"])),
    ):
        mock_provider.return_value.embed.return_value = [[0.1]]
        mock_qdrant.search.return_value = [_make_hit("c1", 0.9, str(uuid4()), "본문")]

        response = await search_service.perform_search(db, user, SearchRequest(query="q", mode="vector"))

    assert response.applied.mode == "vector" and response.applied.from_collection is False
    assert response.items[0].final_score is None



@pytest.mark.asyncio
async def test_perform_search_without_mode_or_saved_settings_stays_vector():
    # MCP나 스크립트처럼 방식을 빼먹은 호출은 마일스톤 6 이전처럼 의미 검색이다
    user = MagicMock(id=uuid4())
    db = AsyncMock()
    db.add = MagicMock()

    with (
        patch("app.services.search_service.get_embedding_provider") as mock_provider,
        patch("app.services.search_service.qdrant_service") as mock_qdrant,
        patch("app.services.search_service.accessible_collection_ids", new=AsyncMock(return_value=["col-1"])),
        patch.object(search_service, "stored_collection_search_settings", new=AsyncMock(return_value=None)),
    ):
        mock_provider.return_value.embed.return_value = [[0.1]]
        mock_qdrant.search.return_value = [_make_hit("c1", 0.9, str(uuid4()), "본문")]

        response = await search_service.perform_search(db, user, SearchRequest(query="q"))

    assert response.applied.mode == "vector" and response.applied.from_collection is False


@pytest.mark.asyncio
async def test_applied_settings_are_not_labelled_as_collection_settings_when_overridden():
    from app.services.search_settings import SearchSettings

    user = MagicMock(id=uuid4())
    db = AsyncMock()
    db.add = MagicMock()

    with (
        patch("app.services.search_service.get_embedding_provider") as mock_provider,
        patch("app.services.search_service.qdrant_service") as mock_qdrant,
        patch.object(search_service, "stored_collection_search_settings",
                     new=AsyncMock(return_value=SearchSettings(mode="hybrid"))),
    ):
        mock_provider.return_value.embed.return_value = [[0.1]]
        mock_qdrant.search.return_value = [_make_hit("c1", 0.9, str(uuid4()), "본문")]

        response = await search_service.perform_search(
            db, user, SearchRequest(query="q", mode="vector", collection_id=uuid4()))

    assert response.applied.mode == "vector" and response.applied.from_collection is False
