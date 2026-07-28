from app.pipeline.blocks.output_blocks import _match_chunk_keywords


def test_matches_keywords_present_in_chunk_text():
    chunk_text = "이 문서는 에너지 진단 결과와 온실가스 배출량을 다룬다."
    document_keywords = ["에너지 진단", "온실가스", "무관한키워드"]

    result = _match_chunk_keywords(chunk_text, document_keywords)

    assert result == ["에너지 진단", "온실가스"]


def test_no_matches_returns_empty_list():
    chunk_text = "전혀 관련 없는 내용입니다."
    document_keywords = ["에너지 진단", "온실가스"]

    assert _match_chunk_keywords(chunk_text, document_keywords) == []


def test_matching_is_case_insensitive():
    chunk_text = "This section covers ENERGY AUDIT results."
    document_keywords = ["energy audit"]

    assert _match_chunk_keywords(chunk_text, document_keywords) == ["energy audit"]


def test_empty_keyword_list_returns_empty():
    assert _match_chunk_keywords("아무 텍스트", []) == []
