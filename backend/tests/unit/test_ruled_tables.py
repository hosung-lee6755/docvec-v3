"""PDF에 선으로 그린 표를 선 그대로 읽는다 (2026-11-17, 기계설비기술기준매뉴얼 표 실측).

실제 문서의 표는 바깥 왼쪽과 오른쪽 테두리 세로선이 없고, 칸 안에 작은 표가 또 들어 있었다.
Docling은 안쪽 표의 선까지 바깥 표의 열로 펼쳐 4열 표를 10열로 만들고 같은 글을 일곱 번 복사했다.
"""
import fitz
import pdfplumber
import pytest

from app.pipeline.adapters.ruled_tables import find_ruled_tables, match_ruled_table


def _line(page, x0, y0, x1, y1):
    page.draw_line(fitz.Point(x0, y0), fitz.Point(x1, y1), width=0.5)


@pytest.fixture
def nested_pdf(tmp_path):
    """머리 행 + 2행, 4열(번호, 판단기준, 판단근거, 필요서류). 좌우 테두리 없음. 2행 판단기준 칸 안에 2x2 표."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    xs = [60, 120, 400, 460, 540]
    ys = [100, 130, 250, 500]
    for y in ys:
        _line(page, xs[0], y, xs[-1], y)
    for x in xs[1:-1]:
        _line(page, x, ys[0], x, ys[-1])
    # 2행 판단기준 칸(120~400, 250~500) 안의 작은 표
    for y in (330, 370, 410):
        _line(page, 150, y, 370, y)
    for x in (150, 260, 370):
        _line(page, x, 330, x, 410)
    texts = [
        (80, 120, "No"), (200, 120, "Criteria"), (410, 120, "Basis"), (470, 120, "Docs"),
        (80, 190, "1"), (130, 190, "Insulate pipes"), (410, 190, "2.2"), (470, 190, "Spec"),
        (80, 300, "2"), (130, 300, "Meter box rule"), (410, 300, "2.3.5"), (470, 300, "Spec"),
        (160, 355, "DN"), (270, 355, "Thickness"), (160, 395, "20"), (270, 395, "25mm"),
    ]
    for x, y, text in texts:
        page.insert_text(fitz.Point(x, y), text, fontsize=9)
    path = tmp_path / "nested.pdf"
    doc.save(path)
    return path


def test_reads_the_outer_table_with_missing_side_borders_and_keeps_the_inner_table_apart(nested_pdf):
    with pdfplumber.open(nested_pdf) as pdf:
        tables = find_ruled_tables(pdf.pages[0])

    assert len(tables) == 1
    outer = tables[0]
    assert outer.rows[0] == ["No", "Criteria", "Basis", "Docs"]
    assert [row[0] for row in outer.rows[1:]] == ["1", "2"]
    assert outer.rows[2][1] == "Meter box rule"  # 안쪽 표 글은 바깥 칸에 섞지 않는다
    assert len(outer.nested) == 1
    assert outer.nested[0].rows == [["DN", "Thickness"], ["20", "25mm"]]


def test_matches_a_docling_table_by_position(nested_pdf):
    with pdfplumber.open(nested_pdf) as pdf:
        tables = find_ruled_tables(pdf.pages[0])

    assert match_ruled_table(tables, (62, 102, 538, 498)) is tables[0]
    assert match_ruled_table(tables, (60, 600, 540, 700)) is None


def test_a_single_framed_box_is_not_a_table(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.draw_rect(fitz.Rect(60, 100, 540, 300), width=0.5)
    page.insert_text(fitz.Point(80, 150), "Note inside a box", fontsize=9)
    path = tmp_path / "box.pdf"
    doc.save(path)

    with pdfplumber.open(path) as pdf:
        assert find_ruled_tables(pdf.pages[0]) == []


def test_a_single_cell_first_row_becomes_the_table_title(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    for y in (100, 130, 160, 190):
        _line(page, 60, y, 540, y)
    for x in (60, 540):
        _line(page, x, 100, x, 190)
    _line(page, 300, 130, 300, 190)
    for x, y, text in ((250, 120, "Checklist"), (80, 150, "Item"), (320, 150, "Result"), (80, 180, "Boiler"), (320, 180, "OK")):
        page.insert_text(fitz.Point(x, y), text, fontsize=9)
    path = tmp_path / "titled.pdf"
    doc.save(path)

    with pdfplumber.open(path) as pdf:
        table = find_ruled_tables(pdf.pages[0])[0]

    assert table.title == "Checklist"
    assert table.rows == [["Item", "Result"], ["Boiler", "OK"]]


def test_page_header_and_footer_rules_do_not_wrap_the_page_in_a_fake_table(nested_pdf, tmp_path):
    # 리뷰 M4: 쪽 머리와 바닥 구분선이 같은 x에서 끝나도 표 테두리로 보충하지 않는다
    doc = fitz.open(nested_pdf)
    page = doc[0]
    _line(page, 60, 40, 540, 40)
    _line(page, 60, 760, 540, 760)
    path = tmp_path / "ruled_page.pdf"
    doc.save(path)

    with pdfplumber.open(path) as pdf:
        tables = find_ruled_tables(pdf.pages[0])

    assert len(tables) == 1 and tables[0].rows[0] == ["No", "Criteria", "Basis", "Docs"]


def test_rows_stacked_without_rules_in_one_cell_are_split_by_line():
    # 기계설비기술기준 매뉴얼의 설계 외기온·습도 표: 도시마다 가로 선이 없어 17개 도시가 한 칸에 줄로 쌓인다.
    # 나누지 않으면 "서 울 인 천 … | 31.2 30.1 …"이 되어 서울의 값을 짚을 수 없다(채팅 오답 실측, 2026-11-19)
    from app.pipeline.adapters.ruled_tables import _clean_rows

    raw = [
        ["", "도시명", "건구온도(℃)", "습구온도(℃)"],
        ["", "서 울\n인 천\n수 원", "31.2\n30.1\n31.2", "25.5\n25.0\n- 8.7"],
    ]
    assert _clean_rows(raw) == [
        ["", "도시명", "건구온도(℃)", "습구온도(℃)"],
        ["", "서 울", "31.2", "25.5"],
        ["", "인 천", "30.1", "25.0"],
        ["", "수 원", "31.2", "- 8.7"],
    ]


def test_wrapped_text_in_cells_is_not_split_into_rows():
    from app.pipeline.adapters.ruled_tables import _clean_rows

    raw = [["항목", "설명"], ["환기 설비", "실내 공기를\n바깥 공기로\n바꾸는 설비"]]
    assert _clean_rows(raw) == [["항목", "설명"], ["환기 설비", "실내 공기를\n바깥 공기로\n바꾸는 설비"]]


def test_year_column_next_to_prose_folded_into_the_same_line_count_is_not_split():
    from app.pipeline.adapters.ruled_tables import _clean_rows

    raw = [["연도", "내용"], ["2023\n2024\n2025", "설비 교체 공사를 마치고 시운전을\n거쳐 준공 검사를 받은 뒤 운영을\n시작했으며 점검 주기를 정했다"]]
    assert _clean_rows(raw)[1][0] == "2023\n2024\n2025"
