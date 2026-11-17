"""제목 상자 표를 제목으로 읽기(title_box.py)와 그에 따른 줄 제목 수준."""
import pytest

from app.pipeline.blocks import structure_blocks as sb
from app.pipeline.blocks.title_box import shifted_level, starts_with_roman, title_box_heading

MAX_CHARS = 50


@pytest.mark.parametrize("row, expected", [
    ("① | 조사료 사일리지 제조·운송비 지원", ("① 조사료 사일리지 제조·운송비 지원", 2)),
    ("Ⅰ |  | 사업 개요", ("Ⅰ 사업 개요", 1)),
    ("Ⅱ. 2022년 사업 시행 주요내용", ("Ⅱ. 2022년 사업 시행 주요내용", 1)),
    ("1. 조사료 생산 | ", ("1. 조사료 생산", 2)),
    ("3. | 추진 일정", ("3. 추진 일정", 2)),
])
def test_single_row_table_starting_with_a_marker_is_a_heading(row, expected):
    assert title_box_heading(["[표 7]", row], MAX_CHARS) == expected


@pytest.mark.parametrize("lines", [
    ["[표 20]", "농림축산식품부"],
    ["[표 2]", " | 축산환경자원과"],
    ["[표 3]", "구분 | 규격 | 수량"],
    ["[표 4]", "1 | 2 | 3"],
    ["[표 5]", "① | 가 | 나 | 다"],
    ["[표 6]", "① | " + "긴 설명 " * 12],
    ["[표 8]", "① | 첫째 줄", "② | 둘째 줄"],
    ["[표 9]"],
    ["[표 10]", " |  | "],
])
def test_other_tables_stay_tables(lines):
    assert title_box_heading(lines, MAX_CHARS) is None


def test_roman_start_is_recognised():
    assert starts_with_roman(" Ⅲ. 사업추진체계") and starts_with_roman("Ⅳ 기타")
    assert not starts_with_roman("1. 사업대상자") and not starts_with_roman("Ⅲ")


def test_shifted_level_keeps_former_headings_within_the_limit():
    assert shifted_level(1, 2, 3) == 3
    assert shifted_level(2, 2, 3) == 3
    assert shifted_level(4, 2, 3) == 6
    assert shifted_level(1, 0, 3) == 1
    assert shifted_level(None, 2, 3) is None
    assert shifted_level(1, 1, None) == 2


def _headings(text: str, max_level: int | None = 3) -> list[tuple[int | None, str]]:
    return [(b[1], b[4]) for b in sb._build_blocks(text, max_level=max_level) if b[0] == "HEADING"]


def test_title_boxes_become_headings_and_push_line_headings_down():
    text = "\n\n".join([
        "[표 1]\nⅡ |  | 사업 시행 주요내용",
        "1. 사업대상자",
        "[표 2]\n① | 조사료 사일리지 제조비 지원",
        "1. 사업대상자",
        "본문입니다.",
        "[표 3]\n구분 | 금액\n보조 | 30",
        "2. 지원자격",
        "Ⅲ. 사업추진체계",
        "1. 추진 절차",
    ])

    blocks = sb._build_blocks(text, max_level=3)

    assert _headings(text) == [
        (1, "Ⅱ 사업 시행 주요내용"),
        (2, "1. 사업대상자"),
        (2, "① 조사료 사일리지 제조비 지원"),
        (3, "1. 사업대상자"),
        (3, "2. 지원자격"),
        (1, "Ⅲ. 사업추진체계"),
        (1, "1. 추진 절차"),
    ]
    assert [b[4] for b in blocks if b[0] == "TABLE"] == ["[표 3]\n구분 | 금액\n보조 | 30"]


def test_title_box_heading_keeps_the_span_of_the_table_block():
    text = "앞 문단\n\n[표 1]\n① | 세부사업\n\n뒤 문단"

    heading = next(b for b in sb._build_blocks(text) if b[0] == "HEADING")

    assert text[heading[2]:heading[3]] == "[표 1]\n① | 세부사업"


def test_documents_without_title_boxes_are_unchanged():
    text = "1. 개요\n\n본문\n\n1.1 배경\n\n[표 1]\n구분 | 값\n가 | 1"

    assert _headings(text) == [(1, "1. 개요"), (2, "1.1 배경")]


def test_letter_spaced_numbered_heading_is_accepted():
    assert _headings("1. 목    적\n\n본문") == [(1, "1. 목    적")]
    assert _headings("1. 가나다    5,000    3,000") == []
