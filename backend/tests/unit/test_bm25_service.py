from app.services.bm25_service import bm25_rerank


def test_bm25_rerank_returns_empty_for_no_candidates():
    assert bm25_rerank("query", []) == []


def test_bm25_rerank_boosts_keyword_match_over_pure_vector_score():
    # 3+ candidates avoid a degenerate BM25 IDF edge case where a term present
    # in exactly half of a 2-doc corpus yields idf == 0 for every document.
    candidates = [
        {"text": "the quick brown fox jumps over the lazy dog", "score": 0.5},
        {"text": "completely unrelated content about weather patterns", "score": 0.6},
        {"text": "another unrelated document about finance and taxes", "score": 0.9},
    ]

    results = bm25_rerank("quick brown fox", candidates)

    assert results[0]["text"].startswith("the quick brown fox")
    assert "bm25_score" in results[0]
    assert "final_score" in results[0]


def test_bm25_rerank_sorts_by_final_score_descending():
    candidates = [
        {"text": "alpha beta gamma", "score": 0.1},
        {"text": "alpha beta gamma delta", "score": 0.1},
    ]

    results = bm25_rerank("alpha beta gamma delta", candidates)

    scores = [r["final_score"] for r in results]
    assert scores == sorted(scores, reverse=True)
