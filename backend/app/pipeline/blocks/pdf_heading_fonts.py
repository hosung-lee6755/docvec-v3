"""Docling 제목 요소의 실제 글자 크기를 원본 PDF 텍스트 레이어에서 읽는다.

구조 보정(structure_refine)은 bbox 높이·너비로 글자 크기를 어림하는데, "□"처럼 폭이 넓은 기호가 섞이면 크게 잡힌다.
디지털협업공장 공고문(2026-11-20)에서 "1. 사업 개요"(10.7pt)가 11.0, 바로 아래 "□ 사업 개요"(10.7pt)가 13.0으로
어림돼 장 제목이 □ 제목보다 낮은 단계가 됐다. 텍스트 레이어가 있으면 그 크기를 쓴다.
"""
import logging
from collections import Counter

logger = logging.getLogger(__name__)

HEADING_ELEMENT_TYPES = frozenset({"title", "section_header", "section-header"})


def _top_left_clip(page, bbox):
    import fitz

    left, first_y, right, second_y = bbox
    if first_y > second_y:  # Docling 의 왼쪽 아래 원점 좌표
        first_y, second_y = page.rect.height - first_y, page.rect.height - second_y
    return fitz.Rect(min(left, right) - 1, first_y - 1, max(left, right) + 1, second_y + 1)


def dominant_span_size(page, bbox) -> float | None:
    """bbox 안 글자들이 가장 많이 쓴 글자 크기(소수 첫째 자리)."""
    counts: Counter = Counter()
    for block in page.get_text("dict", clip=_top_left_clip(page, bbox))["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                chars = len(span["text"].strip())
                if chars:
                    counts[round(span["size"], 1)] += chars
    return counts.most_common(1)[0][0] if counts else None


def heading_font_sizes(pdf_bytes: bytes, elements: list[dict]) -> dict[str, float]:
    """제목 요소 id → 실제 글자 크기. 원본을 못 읽거나 텍스트 레이어가 없으면 빈 사전(어림값을 쓴다)."""
    targets = [
        el for el in elements
        if el.get("type") in HEADING_ELEMENT_TYPES and el.get("bbox") and len(el["bbox"]) == 4 and el.get("page")
    ]
    if not targets or not pdf_bytes:
        return {}
    try:
        import fitz

        sizes: dict[str, float] = {}
        with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
            for el in targets:
                if 1 <= el["page"] <= len(pdf):
                    size = dominant_span_size(pdf[el["page"] - 1], el["bbox"])
                    if size:
                        sizes[el["id"]] = size
        return sizes
    except Exception:
        logger.warning("heading font sizes: failed to read the original PDF", exc_info=True)
        return {}
