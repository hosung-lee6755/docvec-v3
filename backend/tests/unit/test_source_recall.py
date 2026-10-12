"""원본 PDF 텍스트 레이어 대비 추출 결과 재현율(source_recall) 검증."""
from app.pipeline.blocks.source_recall import (
    MIN_PAGE_NGRAMS,
    compute_source_recall,
    normalize_for_recall,
)

PAGE = "연간 점등시간은 3,200시간이며 전력 단가는 145.21원이다. 절감 전력은 정격 소비전력 기준이다."


def test_normalize_drops_whitespace_and_markdown_table_markup():
    assert normalize_for_recall("구분 | 장소\n|---|---|\n# 제목") == "구분장소제목"


def test_identical_text_has_full_recall():
    result = compute_source_recall([PAGE], PAGE)

    assert result.recall == 1.0
    assert result.measured_pages == 1
    assert result.low_pages == []


def test_markdown_table_cells_still_match_original_text_layer():
    original = "구분\n장소\n형식\n정격용량\n1\n공장동 1Bay\nLED\n150\n12\n9\n3,200\n일부 격등제어"
    parsed = "| 구분 | 장소 | 형식 | 정격용량 |\n|---|---|---|---|\n| 1 | 공장동 1Bay | LED | 150 |\n| 12 | 9 | 3,200 | 일부 격등제어 |"

    assert compute_source_recall([original], parsed).recall == 1.0


def test_table_cell_text_missing_from_parsed_lowers_recall_and_flags_page():
    # 실제 사례: 표 셀 텍스트가 빈 칸("| | 최대 0.5억원 | |")으로 추출됨
    original = "신청 예시 지원한도 중간1 동일수준 최초신청 기업 최대 2억원 기초수준 구축기업 최대 2억원"
    parsed = "| 신청 예시 | 지원한도 |\n|---|---|\n|  | 최대 2억원 |\n|  | 최대 2억원 |"

    result = compute_source_recall([original], parsed)

    assert result.recall is not None and result.recall < 0.6
    assert result.low_pages == [1]


def test_only_pages_with_enough_text_are_measured():
    result = compute_source_recall(["- 3 -", PAGE, ""], PAGE)

    assert result.total_pages == 3
    assert result.measured_pages == 1


def test_recall_is_none_when_original_has_no_text_layer():
    result = compute_source_recall(["", "  ", "1"], "OCR로 읽은 긴 본문 텍스트입니다 여러 문장")

    assert result.recall is None
    assert result.measured_pages == 0


def test_low_pages_are_reported_by_one_based_page_number():
    other = "전혀 다른 내용의 문장이며 충분히 길게 작성된 두 번째 페이지 본문입니다."
    result = compute_source_recall([PAGE, other], PAGE)

    assert result.low_pages == [2]
    assert MIN_PAGE_NGRAMS <= len(normalize_for_recall(PAGE))
