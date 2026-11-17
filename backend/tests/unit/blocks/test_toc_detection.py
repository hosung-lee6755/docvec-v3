"""목차 제목("목차", "차례")으로 목차를 찾는다 (2026-11-17 구조 인식 점검).

HTML 보고서와 HWPX 문서의 목차에는 쪽 번호가 없어 "제목 ..... 3" 꼴만 보던 규칙이 놓쳤다. 놓친 항목은
번호 때문에 제목으로 분류되어, 완료보고서는 제목 163개 가운데 106개가 본문 제목과 겹쳤다.
"""
from app.pipeline.blocks.structure_blocks import _build_blocks, _detect_toc_line_offsets
from app.pipeline.blocks.toc_detection import titled_toc_indices

MANUAL = [
    "AIDE 분석 시스템 관리자 매뉴얼목차",
    "0 이 매뉴얼 쓰는 법",
    "1 설치 전 준비",
    "1-1 서버 환경 확인",
    "2 운영DB 준비",
    "부록 A 명령 순서 한 장",
    "AIDE 분석 시스템 관리자 매뉴얼",
    "새 워크스테이션에 AIDE 분석 시스템을 설치하는 절차를 안내합니다. " * 3,
    "0 이 매뉴얼 쓰는 법",
    "본문 설명",
    "1 설치 전 준비",
    "1-1 서버 환경 확인",
    "2 운영DB 준비",
    "부록 A 명령 순서 한 장",
]


def test_entries_after_a_toc_title_that_reappear_in_the_body_are_the_toc():
    assert titled_toc_indices(MANUAL) == {1, 2, 3, 4, 5}


def test_the_toc_stops_where_the_body_repeats_the_first_entry():
    texts = ["차례>", "1. 사업개요", "1.1. 배경 및 목적", "2. 과업 내용", "1. 사업개요", "본문", "1.1. 배경 및 목적", "2. 과업 내용"]

    assert titled_toc_indices(texts) == {1, 2, 3}


def test_page_numbers_and_leaders_are_ignored_when_matching_the_body():
    texts = ["목 차", "제1장 총칙 ········ 3", "제2장 사업 ········ 9", "제3장 부칙 ······· 20", "제1장 총칙", "x", "제2장 사업", "제3장 부칙"]

    assert titled_toc_indices(texts) == {1, 2, 3}


def test_a_word_toc_in_a_sentence_or_entries_missing_from_the_body_are_not_a_toc():
    assert titled_toc_indices(["이 문서는 목차를 먼저 보여 준다.", "가", "나", "다", "가", "나", "다"]) == set()
    assert titled_toc_indices(["목차", "가 항목", "나 항목", "다 항목", "전혀 다른 본문"]) == set()


def test_text_path_marks_titled_toc_lines_and_keeps_body_headings():
    text = "\n\n".join(MANUAL)

    blocks = _build_blocks(text, layout_entries=None, toc_offsets=_detect_toc_line_offsets(text))

    toc = [b[4] for b in blocks if b[0] == "TOC"]
    headings = [b[4] for b in blocks if b[0] == "HEADING"]
    assert toc[:2] == ["0 이 매뉴얼 쓰는 법", "1 설치 전 준비"]
    assert headings.count("1 설치 전 준비") == 1


def test_middle_dot_leaders_count_as_toc_leaders():
    text = "기계설비공사 업무 ·················· 3\n착공 전 확인 ···················· 9\n사용 전 검사 ··················· 15\n\n본문"

    assert len(_detect_toc_line_offsets(text)) == 3
