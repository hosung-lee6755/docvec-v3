"""표 영역 안 원본 글자 줄이 표 글에서 빠졌는지 보고, 빠진 줄을 칸 좌표로 되돌려 넣는다(2026-11-23).

실측
- 자율형공장 공고 17쪽: Docling 이 칸 안 넷째 줄 "∙ 자율형 공장기술에 대해 공장 전 부분으로의 확장성 및 효율성"을 어느
  칸에도 넣지 않았다. 그 줄은 위 칸(142,616,366,654)과 아래 칸(142,671,444,696) 사이(657~668)에 있다.
- UIUX 가이드라인 80쪽: 바깥 세로 테두리가 없는 선 표에서 "Style"과 "Usage" 열이 칸으로 잡히지 않아
  "Display는 화면에서 가장 큰 텍스트로…"가 모두 빠졌다. 같은 표를 Docling 은 다 읽었다."""
from app.pipeline.adapters.table_text_coverage import (
    TextLine,
    lines_from_words,
    missing_lines,
    refill_cells,
)


def _words(*specs):
    # (x0, top, x1, bottom, word, block, line, word_no) — PyMuPDF get_text("words")와 같은 모양
    return [(x0, top, x1, bottom, word, block, line, n) for n, (x0, top, x1, bottom, word, block, line) in enumerate(specs)]


def test_words_are_grouped_into_lines_in_reading_order():
    lines = lines_from_words(_words(
        (200, 30, 240, 40, "둘째", 1, 0), (142, 10, 160, 20, "∙", 0, 0), (165, 10, 200, 20, "첫째", 0, 0),
    ))

    assert [line.text for line in lines] == ["∙ 첫째", "둘째"]
    assert lines[0].box == (142, 10, 200, 20)


def test_a_line_counts_as_missing_only_when_most_of_its_words_are_absent():
    table_text = ["∙ 자율형 공장 구축계획 및 적용 가능성", "Display는화면에서가장 큰텍스트로", "Large", "66"]
    lines = [
        TextLine("∙ 자율형 공장기술에 대해 공장 전 부분으로의 확장성 및 효율성", (142, 657, 454, 668)),
        TextLine("Display는 화면에서 가장", (430, 150, 514, 160)),  # 띄어쓰기만 다르다
        TextLine("Large 66", (124, 138, 186, 146)),  # 여러 칸이 한 줄로 읽혔다
        TextLine("∙", (100, 1, 101, 2)),  # 낱말이 없다
    ]

    assert [line.text for line in missing_lines(lines, table_text)] == [lines[0].text]


def test_symbols_drawn_apart_from_the_text_layer_do_not_make_a_line_missing():
    # 세원화성 진단보고서 34쪽: 글자 층은 "가격원", Docling 칸 글은 "가격 (원)"이다. 기호까지 견주면 빠진 줄로 보고
    # 칸에 "가격 (원) 가격원"처럼 한 번 더 붙였다
    table_text = ["가격 (원)", "투자회수기간 (년)", "곤란 (수리비과다)"]
    lines = [
        TextLine("가격원", (142, 578, 176, 588)),
        TextLine("투자회수기간년", (122, 605, 196, 615)),
        TextLine("곤란수리비과다", (301, 633, 375, 643)),
    ]

    assert missing_lines(lines, table_text) == []


def test_a_dropped_line_between_two_cells_goes_to_the_cell_above():
    cells = [
        ((78, 629, 111, 654), "고도화 (40)"),
        ((142, 616, 366, 654), "∙ 자율형 공장 구축계획 및 적용 가능성"),
        ((142, 671, 444, 696), "∙ CEO·경영진의 고도화 실천의지"),
    ]
    dropped = TextLine("∙ 자율형 공장기술에 대해 공장 전 부분으로의 확장성 및 효율성", (142, 657, 454, 668))

    texts = refill_cells([box for box, _ in cells], [text for _, text in cells], [dropped])

    assert texts == [
        "고도화 (40)",
        "∙ 자율형 공장 구축계획 및 적용 가능성 ∙ 자율형 공장기술에 대해 공장 전 부분으로의 확장성 및 효율성",
        "∙ CEO·경영진의 고도화 실천의지",
    ]


def test_a_line_far_from_every_cell_or_in_another_column_is_left_out():
    cells = [((142, 100, 300, 120), "칸")]
    far_below = TextLine("멀리 떨어진 줄", (142, 300, 250, 310))
    other_column = TextLine("다른 열의 줄", (400, 100, 480, 110))

    assert refill_cells([box for box, _ in cells], ["칸"], [far_below, other_column]) == ["칸"]


def test_cells_without_a_box_are_skipped():
    dropped = TextLine("빠진 줄", (10, 10, 40, 20))

    assert refill_cells([None, (10, 0, 50, 9)], ["", "위 칸"], [dropped]) == ["", "위 칸 빠진 줄"]
