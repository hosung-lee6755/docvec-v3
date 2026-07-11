"""Coverage for app.services.mmr_service.mmr_rerank — the greedy Maximal
Marginal Relevance selector used by search_service when request.diversify is
set, to avoid returning several near-duplicate chunks of the same passage."""

from app.services.mmr_service import mmr_rerank


def _cand(chunk_id: str, score: float, vector: list[float]) -> dict:
    return {"chunk_id": chunk_id, "score": score, "vector": vector}


def test_mmr_rerank_returns_empty_for_no_candidates():
    assert mmr_rerank([], k=3) == []


def test_mmr_rerank_returns_all_when_pool_smaller_than_k():
    candidates = [_cand("a", 0.9, [1.0, 0.0]), _cand("b", 0.5, [0.0, 1.0])]

    result = mmr_rerank(candidates, k=5)

    assert len(result) == 2


def test_mmr_rerank_pure_relevance_at_lambda_one_matches_score_order():
    candidates = [
        _cand("low", 0.3, [1.0, 0.0]),
        _cand("high", 0.9, [1.0, 0.0]),
        _cand("mid", 0.6, [0.0, 1.0]),
    ]

    result = mmr_rerank(candidates, k=3, lambda_param=1.0)

    assert [c["chunk_id"] for c in result] == ["high", "mid", "low"]


def test_mmr_rerank_penalizes_near_duplicate_over_diverse_alternative():
    # "dup" is a near-identical vector to "top" and scores almost as well;
    # "diverse" is orthogonal to both and scores lower. A low lambda (heavy
    # diversity weighting) should prefer "diverse" as the second pick over
    # the redundant "dup".
    candidates = [
        _cand("top", 0.95, [1.0, 0.0]),
        _cand("dup", 0.94, [0.99, 0.01]),
        _cand("diverse", 0.60, [0.0, 1.0]),
    ]

    result = mmr_rerank(candidates, k=2, lambda_param=0.3)

    assert result[0]["chunk_id"] == "top"
    assert result[1]["chunk_id"] == "diverse"


def test_mmr_rerank_treats_missing_vector_as_non_redundant():
    candidates = [
        _cand("a", 0.9, [1.0, 0.0]),
        {"chunk_id": "b", "score": 0.8, "vector": None},
    ]

    result = mmr_rerank(candidates, k=2, lambda_param=0.1)

    assert {c["chunk_id"] for c in result} == {"a", "b"}
