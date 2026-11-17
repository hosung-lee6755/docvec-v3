"""키워드 색인용 sparse 벡터(2026-11-16, 전체 점검 1-1).

예전 "하이브리드" 검색은 벡터 검색이 뽑은 후보 안에서만 BM25 점수를 다시 매겼다. 조항 번호, 품번,
고유명사처럼 글자가 그대로 맞아야 하는 질의는 벡터 후보에 들지 못하면 찾을 수 없었다.

여기서는 청크를 형태소 토큰으로 나눠 sparse 벡터로 만든다. Qdrant의 키워드 전용 컬렉션에 저장하고
(qdrant_service의 lexical 컬렉션), 검색할 때 질의 토큰과 겹치는 청크를 벡터 후보에 더한다.

- 토큰은 BM25 재정렬과 같은 분석기(dictionary_service.tokenize_batch)를 쓴다. 불용어와 동의어 사전이
  색인 시점 기준으로 반영되므로, 사전을 크게 바꾼 뒤에는 scripts/backfill_lexical_index.py로 다시 만든다.
- 문서 쪽 값은 BM25의 단어 빈도 항이다. 드문 낱말에 주는 가중치(IDF)는 Qdrant가 컬렉션 통계로 곱한다.
- 낱말의 색인 번호는 CRC32다. 실행마다 같고, 서로 다른 낱말이 겹칠 확률은 낮다.
"""
from __future__ import annotations

import logging
import zlib
from collections import Counter

# BM25 표준값. 평균 길이는 청크 평균(약 150~400자)의 토큰 수에 맞춘 고정값이다.
# 컬렉션마다 실제 평균을 재지 않는 대신, 길이가 다른 청크 사이의 순서만 대략 맞춘다.
BM25_K1 = 1.2
BM25_B = 0.75
AVERAGE_TOKENS = 100.0
# 질의가 아주 길어도 색인 조회가 무거워지지 않게 한다
MAX_QUERY_TERMS = 64

SparseVector = tuple[list[int], list[float]]

logger = logging.getLogger(__name__)


def term_index(token: str) -> int:
    return zlib.crc32(token.lower().encode("utf-8"))


def _tokenize(texts: list[str]) -> list[list[str]]:
    from app.services.dictionary_service import tokenize_batch

    return tokenize_batch(texts)


def document_vector(tokens: list[str]) -> SparseVector:
    """청크 하나의 sparse 벡터. 토큰이 없으면 빈 벡터다."""
    if not tokens:
        return [], []
    length_norm = BM25_K1 * (1 - BM25_B + BM25_B * len(tokens) / AVERAGE_TOKENS)
    weights: dict[int, float] = {}
    for token, count in Counter(term_index(t) for t in tokens).items():
        weights[token] = count * (BM25_K1 + 1) / (count + length_norm)
    indices = sorted(weights)
    return indices, [weights[i] for i in indices]


def query_vector(tokens: list[str]) -> SparseVector:
    """질의의 sparse 벡터. 낱말마다 1이고, 같은 낱말은 한 번만 센다."""
    indices = sorted({term_index(t) for t in tokens})[:MAX_QUERY_TERMS]
    return indices, [1.0] * len(indices)


def document_vectors(texts: list[str]) -> list[SparseVector]:
    return [document_vector(tokens) for tokens in _tokenize(texts)]


def query_vector_for(text: str) -> SparseVector:
    return query_vector(_tokenize([text])[0]) if text.strip() else ([], [])


def hybrid_query_vector(text: str, mode: str) -> SparseVector | None:
    """하이브리드 검색일 때만 질의의 sparse 벡터를 만든다. 분석기가 실패하면 벡터 검색만 하도록 None을 준다."""
    if mode != "hybrid":
        return None
    try:
        return query_vector_for(text)
    except Exception:  # noqa: BLE001
        logger.exception("lexical query vector failed; searching with vectors only")
        return None
