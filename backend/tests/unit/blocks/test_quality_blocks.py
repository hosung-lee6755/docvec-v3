from app.pipeline.blocks.quality_blocks import (
    _compute_failed_pages,
    _decide_review,
    _determine_status,
    _implicit_table_ratio,
    _toc_heading_match_ratio,
)


def test_compute_failed_pages_flags_only_pages_below_threshold():
    ocr_page_confidence = [
        {"page_number": 1, "confidence": 0.9, "word_count": 50},
        {"page_number": 2, "confidence": 0.3, "word_count": 40},
        {"page_number": 3, "confidence": 0.4, "word_count": 30},
    ]

    assert _compute_failed_pages(ocr_page_confidence, min_confidence=0.5) == [2, 3]


def test_compute_failed_pages_ignores_entries_with_no_confidence():
    ocr_page_confidence = [{"page_number": 1, "confidence": None, "word_count": 0}]

    assert _compute_failed_pages(ocr_page_confidence, min_confidence=0.5) == []


def test_compute_failed_pages_returns_empty_when_absent():
    assert _compute_failed_pages(None, min_confidence=0.5) == []


def test_implicit_table_ratio_computes_fraction_of_implicit_tables():
    tables = [
        {"detected_as": "ruled"},
        {"detected_as": "implicit_alignment"},
        {"detected_as": "implicit_alignment"},
        {"detected_as": "ruled"},
    ]

    assert _implicit_table_ratio(tables) == 0.5


def test_implicit_table_ratio_is_zero_when_no_tables():
    assert _implicit_table_ratio([]) == 0.0
    assert _implicit_table_ratio(None) == 0.0


def test_toc_heading_match_ratio_matches_after_stripping_numbering_and_leader():
    toc_texts = ["1장 서론 ..................... 3", "2장 배경 ..................... 8"]
    heading_texts = ["1. 서론", "이건 매칭 안 되는 다른 제목"]

    ratio = _toc_heading_match_ratio(toc_texts, heading_texts)

    assert ratio == 0.5


def test_toc_heading_match_ratio_is_none_when_no_toc_entries():
    assert _toc_heading_match_ratio([], ["1. 서론"]) is None


def test_toc_heading_match_ratio_is_zero_when_no_headings_match_at_all():
    toc_texts = ["1장 서론 ..................... 3"]

    assert _toc_heading_match_ratio(toc_texts, []) == 0.0


# 9항목 펀치리스트 #1 — "검토 없이 진행" 선택 시 review_policy가 무시되고
# 계속 WAITING_REVIEW로 가던 버그의 회귀 테스트.


def test_skip_review_bypasses_warning_review_on_warning_policy():
    status, requires_review = _decide_review("SUCCESS_WITH_WARNING", "review_on_warning", skip_review=True)

    assert requires_review is False
    assert status == "SUCCESS_WITH_WARNING"


def test_skip_review_bypasses_always_review_policy_on_success():
    status, requires_review = _decide_review("SUCCESS", "always_review", skip_review=True)

    assert requires_review is False
    assert status == "SUCCESS"


def test_skip_review_still_forces_review_on_failure():
    status, requires_review = _decide_review("FAILURE", "auto_pass", skip_review=True)

    assert requires_review is True
    assert status == "FAILURE"


def test_skip_review_still_forces_review_on_partial_failure():
    status, requires_review = _decide_review("PARTIAL_FAILURE", "auto_pass", skip_review=True)

    assert requires_review is True
    assert status == "PARTIAL_FAILURE"


def test_without_skip_review_warning_still_forces_review_on_warning_policy():
    status, requires_review = _decide_review("SUCCESS_WITH_WARNING", "review_on_warning", skip_review=False)

    assert requires_review is True
    assert status == "REVIEW_REQUIRED"


def test_without_skip_review_auto_pass_policy_never_forces_review_on_warning():
    status, requires_review = _decide_review("SUCCESS_WITH_WARNING", "auto_pass", skip_review=False)

    assert requires_review is False
    assert status == "SUCCESS_WITH_WARNING"


# 청크 0개가 overall_score 평균에 희석돼 SUCCESS_WITH_WARNING으로 조용히
# 넘어가던 버그의 회귀 테스트 — 2026-07-28 test_data E2E 검증, 서울시 도시
# 범죄 취약지 분석 PDF에서 실제 재현(표 셀이 전부 빈칸이라 parsed_text가
# 표 문법만으로 min_extraction_chars를 넘겨 textExtraction=100을 받았음).


def test_determine_status_forces_failure_when_no_chunks_even_with_high_overall_score():
    status = _determine_status(
        chunk_count=0, overall_score=64.0, fail_below_score=30.0,
        failed_pages=[], total_ocr_pages=0, has_warnings=True,
    )

    assert status == "FAILURE"


def test_determine_status_success_with_warning_when_chunks_exist_but_warnings_present():
    status = _determine_status(
        chunk_count=10, overall_score=64.0, fail_below_score=30.0,
        failed_pages=[], total_ocr_pages=0, has_warnings=True,
    )

    assert status == "SUCCESS_WITH_WARNING"


def test_determine_status_success_when_chunks_exist_and_no_warnings():
    status = _determine_status(
        chunk_count=10, overall_score=100.0, fail_below_score=30.0,
        failed_pages=[], total_ocr_pages=0, has_warnings=False,
    )

    assert status == "SUCCESS"


def test_determine_status_failure_below_score_threshold_even_with_chunks():
    status = _determine_status(
        chunk_count=10, overall_score=10.0, fail_below_score=30.0,
        failed_pages=[], total_ocr_pages=0, has_warnings=True,
    )

    assert status == "FAILURE"


def test_determine_status_partial_failure_when_some_pages_below_ocr_threshold():
    status = _determine_status(
        chunk_count=10, overall_score=80.0, fail_below_score=30.0,
        failed_pages=[2, 3], total_ocr_pages=10, has_warnings=True,
    )

    assert status == "PARTIAL_FAILURE"
