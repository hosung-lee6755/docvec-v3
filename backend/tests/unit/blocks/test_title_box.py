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


@pytest.mark.parametrize("row, expected", [
    # 붙임·참고 표시가 든 상자는 부록 묶음의 맨 윗단계다(정부 보도자료 d1, 공고문 d3, 2026-11-24)
    ("참고1 | 법령체계 개편(안)", ("참고1 법령체계 개편(안)", 1)),
    ("붙임 1 |  | 동시수행 및 참여제한 사업 목록", ("붙임 1 동시수행 및 참여제한 사업 목록", 1)),
    ("<별첨 2> 사업계획서 서식", ("<별첨 2> 사업계획서 서식", 1)),
    ("【참고 3】 | 영상회의 개요", ("【참고 3】 영상회의 개요", 1)),
    # 번호 없이 한 문구만 든 표어 상자는 절 제목이다(d1 "제명을 바꾼다!")
    (" | 제명을 바꾼다! (사무관리규정 → 행정업무의 효율적 운영에 관한 규정)",
     ("제명을 바꾼다! (사무관리규정 → 행정업무의 효율적 운영에 관한 규정)", 1)),
    (" | 20년간 행정업무처리의 근간이 되었던 「사무관리규정」, 역사 속으로 사라져",
     ("20년간 행정업무처리의 근간이 되었던 「사무관리규정」, 역사 속으로 사라져", 1)),
    ("협업을 증진한다!", ("협업을 증진한다!", 1)),
])
def test_annex_and_slogan_boxes_are_headings(row, expected):
    assert title_box_heading(["[표 7]", row], MAX_CHARS) == expected


@pytest.mark.parametrize("row", [
    # 기관 이름 한두 낱말은 흐름도 상자다
    "중소벤처기업부 (주관)",
    # 표 바로 앞의 소제목 표시는 표로 둔다
    " | < 부적격 사항 > | ",
    # 문장으로 끝나거나 여러 문단·글머리표가 든 상자는 강조 글이지 제목이 아니다
    "접수 마감일에는 접속이 원활하지 않을 수 있습니다.",
    "세종시 이전 등 달라진 행정환경 변화에 대응 위해 / 20년 만에 사무관리규정 전부 개정",
    "◈ 기획재정부가 세종시로 이전할 경우 부담이 크다",
    "☞ 평가, 선정, 협약 등 절차는 사정에 따라 변경될 수 있음",
    # 칸이 여럿인 머리 상자
    " | 보 도 자 료 | 작성과 | 행정제도과",
    # 숫자 위주
    "2025 | 2026 | 합계",
])
def test_unmarked_boxes_that_are_not_headlines_stay_tables(row):
    assert title_box_heading(["[표 7]", row], MAX_CHARS) is None


def test_slogan_box_pushes_square_bullet_headings_below_it():
    text = "\n\n".join([
        "[표 5]\n | 제명을 바꾼다! (사무관리규정 → 행정업무의 효율적 운영에 관한 규정)",
        "□ 법령체계 정비",
        "본문입니다.",
        "[표 9]\n참고1 | 법령체계 개편(안)",
        "□ 개 요",
    ])

    assert _headings(text) == [
        (1, "제명을 바꾼다! (사무관리규정 → 행정업무의 효율적 운영에 관한 규정)"),
        (2, "□ 법령체계 정비"),
        (1, "참고1 법령체계 개편(안)"),
        (2, "□ 개 요"),
    ]


def test_slogan_box_after_numbered_title_boxes_stays_a_table():
    # 번호 제목 상자로 장을 나눈 지침에서 한 칸 상자는 할 일의 주체 표시다("시·도(시·군), 농협경제지주(일선조합),
    # 축산단체"). 1단계 제목으로 올리면 장 밖으로 튀어나와 뒤 청크의 절 경로가 장 제목을 잃는다(조사료 지침, 2026-11-24)
    text = "\n\n".join([
        "[표 1]\nⅡ |  | 사업 시행 주요내용",
        "5. 이행점검단계",
        "[표 2]\n시·도(시·군), 농협경제지주(일선조합), 축산단체",
        "○ 수시로 현장점검",
    ])

    assert _headings(text) == [(1, "Ⅱ 사업 시행 주요내용"), (2, "5. 이행점검단계")]
    assert title_box_heading(["[표 2]", "시·도(시·군), 농협경제지주(일선조합), 축산단체"], MAX_CHARS, allow_slogan=False) is None


# HWP 표 글도 PDF·DOCX 처럼 Markdown 표로 적는다(2026-11-25). 한 줄짜리 Markdown 표는 머리 줄과 구분선 두 줄이다
@pytest.mark.parametrize("lines, expected", [
    (["[표 7]", "| Ⅰ |  | 사업 개요 |", "|---|---|---|"], ("Ⅰ 사업 개요", 1)),
    (["[표 7]", "| ① | 조사료 사일리지 제조·운송비 지원 |", "|---|---|"], ("① 조사료 사일리지 제조·운송비 지원", 2)),
    (["[표 7]", "| 참고1 | 법령체계 개편(안) |", "|---|---|"], ("참고1 법령체계 개편(안)", 1)),
])
def test_single_row_markdown_table_is_read_like_a_pipe_row(lines, expected):
    assert title_box_heading(lines, MAX_CHARS) == expected


def test_markdown_table_with_two_rows_stays_a_table():
    lines = ["[표 3]", "| ① | 첫째 줄 |", "|---|---|", "| ② | 둘째 줄 |"]

    assert title_box_heading(lines, MAX_CHARS) is None
