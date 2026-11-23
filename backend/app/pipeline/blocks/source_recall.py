"""원본 PDF 텍스트 레이어 대비 추출 결과 재현율 — 품질 검증(quality_check)의 실측 지표.

원본 PDF 각 페이지의 텍스트 레이어에서 5글자 조각(n-gram)을 뽑아, 그 조각이 추출 결과
(parsed_text)에 얼마나 들어 있는지를 센다. 표는 추출 시 마크다운(`|`, `---`)으로 바뀌므로
공백·표 구분자·마크다운 기호를 모두 지우고 비교한다 — 셀 텍스트가 빠지면 조각이 사라져 잡힌다.

한계: 텍스트 레이어가 없는 스캔 페이지는 정답이 없어 측정하지 않는다(OCR 정확도는 이 지표로 알 수 없다).
텍스트 레이어 자체가 틀린 PDF는 그 오류를 그대로 정답으로 삼는다.
"""
import re
from dataclasses import dataclass, field

NGRAM_SIZE = 5
# 페이지당 조각이 이보다 적으면(쪽번호만 있는 페이지 등) 비교하지 않는다.
MIN_PAGE_NGRAMS = 20
# 페이지 재현율이 이 값 미만이면 "누락 의심 페이지"로 따로 보고한다.
LOW_PAGE_RECALL = 0.6

_STRIP_RE = re.compile(r"[\s|]+|-{3,}|[#*`]")


@dataclass(frozen=True)
class SourceRecall:
    recall: float | None  # 측정 불가면 None
    measured_pages: int
    total_pages: int
    low_pages: list[int] = field(default_factory=list)  # 1-based 페이지 번호


def normalize_for_recall(text: str | None) -> str:
    return _STRIP_RE.sub("", text or "")


def _ngrams(text: str) -> set[str]:
    return {text[i:i + NGRAM_SIZE] for i in range(len(text) - NGRAM_SIZE + 1)}


def _best_page_grams(variants: tuple[str, ...], parsed: set[str]) -> tuple[set[str], int]:
    """한 쪽의 여러 읽기 순서 가운데 본문과 가장 잘 맞는 쪽의 (조각, 맞은 수)."""
    best: tuple[set[str], int] = (set(), 0)
    best_ratio = -1.0
    for text in variants:
        grams = _ngrams(normalize_for_recall(text))
        if not grams:
            continue
        hits = len(grams & parsed)
        if hits / len(grams) > best_ratio:
            best, best_ratio = (grams, hits), hits / len(grams)
    return best


def compute_source_recall(page_texts: list[str | tuple[str, ...]], parsed_text: str | None) -> SourceRecall:
    """page_texts: 원본 PDF 페이지별 텍스트 레이어. 문서 전체 재현율은 페이지별 조각 수로 가중한다.

    쪽마다 글을 여러 읽기 순서(예: PDF 저장 순서와 위치 정렬)로 줄 수 있다. 그러면 본문과 가장 잘 맞는 순서를
    쓴다. 저장 순서에서 기호가 줄 뒤로 밀린 PDF 는, 보이는 순서로 바로잡은 본문이 저장 순서 기준과만 견줘지면
    누락으로 잘못 잡혔다(세원화성 에너지진단보고서, 2026-11-20)."""
    parsed = _ngrams(normalize_for_recall(parsed_text))
    total_grams = hit_grams = measured = 0
    low_pages: list[int] = []
    for page_number, page_text in enumerate(page_texts, start=1):
        variants = page_text if isinstance(page_text, tuple) else (page_text,)
        grams, hits = _best_page_grams(variants, parsed)
        if len(grams) < MIN_PAGE_NGRAMS:
            continue
        measured += 1
        total_grams += len(grams)
        hit_grams += hits
        if hits / len(grams) < LOW_PAGE_RECALL:
            low_pages.append(page_number)
    recall = hit_grams / total_grams if total_grams else None
    return SourceRecall(recall=recall, measured_pages=measured, total_pages=len(page_texts), low_pages=low_pages)
