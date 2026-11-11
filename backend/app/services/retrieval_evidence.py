"""검색 결과가 근거가 된 이유(v3 마일스톤 6).

채팅 인용과 검색 결과에 점수(벡터, 키워드, 융합, 재순위), 질문과 겹친 낱말, 그 쪽의 OCR 신뢰도를
붙인다. 점수는 검색 단계에서 이미 계산한 값이고, 여기서는 모으고 다듬기만 한다.
"""
from collections.abc import Iterable

from sqlalchemy import select

from app.core.config import settings

MAX_MATCHED_TERMS = 10
_SCORE_FIELDS = (("vector", "score"), ("bm25", "bm25_score"), ("fused", "final_score"), ("rerank", "rerank_score"))


def score_evidence(candidate: dict) -> dict:
    """검색 후보 dict에서 점수만 뽑는다. 계산하지 않은 단계(예: 재순위를 끈 경우)는 빠진다."""
    scores = {}
    for name, field in _SCORE_FIELDS:
        value = candidate.get(field)
        if isinstance(value, int | float):
            scores[name] = round(float(value), 4)
    return scores


def matched_terms(query: str, texts: list[str]) -> list[list[str]]:
    """본문마다 질문과 겹친 낱말(형태소 기준, 질문에 나온 순서, 최대 10개)."""
    if not texts:
        return []
    from app.services.dictionary_service import tokenize_batch

    tokenized = tokenize_batch([*texts, query])
    query_terms = list(dict.fromkeys(t for t in tokenized[-1] if len(t) > 1 or not t.isascii()))
    result = []
    for tokens in tokenized[:-1]:
        present = set(tokens)
        result.append([t for t in query_terms if t in present][:MAX_MATCHED_TERMS])
    return result


def _confidence_map(rows: Iterable) -> dict[tuple[str, int], float]:
    out: dict[tuple[str, int], float] = {}
    for doc_id, pages in rows:
        for entry in pages or []:
            page, confidence = entry.get("page_number"), entry.get("confidence")
            if isinstance(page, int) and isinstance(confidence, int | float):
                out[(str(doc_id), page)] = float(confidence)
    return out


def _confidence_stmt(document_ids: set[str]):
    from app.db.models.document import Document

    return select(Document.id, Document.ocr_page_confidence).where(
        Document.id.in_(document_ids), Document.ocr_page_confidence.is_not(None)
    )


def page_confidences_sync(db, document_ids: Iterable) -> dict[tuple[str, int], float]:
    ids = {str(d) for d in document_ids if d}
    return _confidence_map(db.execute(_confidence_stmt(ids)).all()) if ids else {}


async def page_confidences(db, document_ids: Iterable) -> dict[tuple[str, int], float]:
    ids = {str(d) for d in document_ids if d}
    return _confidence_map((await db.execute(_confidence_stmt(ids))).all()) if ids else {}


def ocr_evidence(confidences: dict[tuple[str, int], float], document_id, page_number) -> dict:
    """OCR로 읽은 쪽이면 그 쪽의 신뢰도와 기준 미달 여부. OCR을 하지 않은 쪽은 빈 dict다."""
    if document_id is None or not isinstance(page_number, int):
        return {}
    confidence = confidences.get((str(document_id), page_number))
    if confidence is None:
        return {}
    return {"ocr_confidence": round(confidence, 3), "low_ocr": confidence < settings.ocr_low_confidence}
