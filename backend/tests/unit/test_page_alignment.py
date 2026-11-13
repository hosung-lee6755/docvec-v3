"""청크 위치(정제·치환·마스킹 뒤 텍스트 기준)를 원문 쪽 번호로 되돌린다.

chunk_split은 text_clean·사전·개인정보 블록을 거친 텍스트를 자른다. 공백 정리만으로도 길이가 줄어
원문(parsed_text) 기준 page_map을 그대로 쓰면 뒤쪽 청크일수록 쪽이 앞당겨진다.
"""
from app.pipeline.page_alignment import PageLocator


def _doc(pages: list[str]) -> tuple[str, list[list[int]]]:
    text = ""
    page_map = []
    for no, body in enumerate(pages, start=1):
        if text:
            text += "\n\n"
        text += body
        page_map.append([len(text), no])
    return text, page_map


def test_whitespace_collapse_does_not_shift_pages():
    parsed, page_map = _doc([
        "첫   쪽\t본문   " * 20,
        "둘째    쪽 본문    " * 20,
        "셋째 쪽   마지막 본문" * 20,
    ])
    normalized = " ".join(parsed.split())
    locator = PageLocator(parsed, page_map, normalized)

    start = normalized.index("셋째")
    assert locator.page_for(start) == 3
    assert locator.page_for(normalized.index("둘째")) == 2
    assert locator.page_for(0) == 1


def test_replaced_terms_and_masks_still_find_the_page():
    parsed, page_map = _doc([
        "사업 개요와 ICT 추진 배경을 설명합니다. " * 10,
        "담당자 연락처 010-1234-5678 로 문의합니다. 신청 기간은 2026년 4월 27일입니다. " * 10,
    ])
    normalized = parsed.replace("ICT", "정보통신기술").replace("010-1234-5678", "[전화번호]")
    locator = PageLocator(parsed, page_map, normalized)

    assert locator.page_for(normalized.index("담당자")) == 2
    assert locator.page_for(normalized.index("정보통신기술")) == 1


def test_unfindable_text_falls_back_to_length_ratio():
    parsed, page_map = _doc(["가" * 100, "나" * 100])
    normalized = "다" * 202  # 아무것도 원문과 맞지 않는다
    locator = PageLocator(parsed, page_map, normalized)

    assert locator.page_for(10) == 1
    assert locator.page_for(190) == 2


def test_without_page_map_returns_none():
    locator = PageLocator("본문", None, "본문")
    assert locator.page_for(0) is None


def test_same_text_is_used_directly():
    parsed, page_map = _doc(["하나 " * 50, "둘 " * 50])
    locator = PageLocator(parsed, page_map, parsed)

    assert locator.page_for(parsed.index("둘")) == 2



def test_offset_mapper_moves_original_positions_into_the_normalized_text():
    from app.pipeline.page_alignment import OffsetMapper

    parsed = "1. 사업 개요\n\n이 사업은   공장 자동화를 지원합니다.\n\n2. 지원 내용\n\nICT 장비를 지원합니다."
    normalized = " ".join(parsed.split()).replace("ICT", "정보통신기술")
    mapper = OffsetMapper(parsed, normalized)

    for phrase, target in [("이 사업은", "이 사업은"), ("2. 지원", "2. 지원"), ("ICT 장비", "정보통신기술 장비")]:
        assert mapper.map(parsed.index(phrase)) == normalized.index(target)
