from app.pipeline.blocks.extraction_blocks import _detect_language


def test_dominant_hangul_text_detected_as_ko():
    text = "이것은 한글로 작성된 문서입니다. 페이지 전체가 한글 문장으로 구성되어 있습니다."

    assert _detect_language(text) == "ko"


def test_dominant_latin_text_detected_as_en():
    text = "This document is written entirely in English prose across the page."

    assert _detect_language(text) == "en"


def test_empty_text_returns_none():
    assert _detect_language("") is None


def test_no_hangul_or_latin_characters_returns_none():
    assert _detect_language("123 456 789 !@# %^&") is None


def test_korean_document_with_many_english_terms_is_still_korean():
    # AIDE 제안서처럼 CAN Data·ADAS 같은 영문 용어가 많아도 한글이 40% 이상이면 한국어 문서다.
    text = "AI 기반 사고 예방 플랫폼 구축 제안서 CAN Data ADAS AI DashCAM DMS GPS 및 운행 데이터 통합 분석"

    assert _detect_language(text) == "ko"


def test_mostly_english_with_a_little_korean_is_ambiguous():
    text = "Quarterly platform review 가나다라마바사아자차"

    assert _detect_language(text) is None
