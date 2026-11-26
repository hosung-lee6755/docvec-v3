"""HWPX 병합 셀과 문단 서식(전체 점검 2-2, 2-12)."""
import zipfile
from types import SimpleNamespace
from xml.etree import ElementTree as ET

from app.pipeline.adapters.base import RawTextBlock
from app.pipeline.adapters.hwp_adapter import HWPAdapter
from app.pipeline.adapters.hwpx_structure import (
    MAX_GRID_CELLS,
    load_styles,
    paragraph_layout,
    sync_layout_pages,
    table_grid,
)
from app.pipeline.blocks.structure_blocks import _classify

HEADER = """<head xmlns:hh="h"><hh:charProperties>
  <hh:charPr id="0" height="1000"/>
  <hh:charPr id="1" height="1600"><hh:bold/></hh:charPr>
</hh:charProperties><hh:styles>
  <hh:style id="0" name="바탕글" engName="Normal"/>
  <hh:style id="2" name="개요 1" engName="Outline 1"/>
  <hh:style id="3" name="개요 2" engName="Outline 2"/>
</hh:styles></head>"""


def _cell(text, row, col, row_span=1, col_span=1):
    return (
        f'<tc><subList><p><run><t>{text}</t></run></p></subList>'
        f'<cellAddr colAddr="{col}" rowAddr="{row}"/><cellSpan colSpan="{col_span}" rowSpan="{row_span}"/></tc>'
    )


def _table(*rows):
    return "<tbl>" + "".join(f"<tr>{''.join(cells)}</tr>" for cells in rows) + "</tbl>"


def _text(tc):
    return "".join(t.text or "" for t in tc.iter("t"))


def test_row_span_keeps_columns_aligned_and_repeats_the_merged_text():
    table = ET.fromstring(_table(
        [_cell("구분", 0, 0), _cell("항목", 0, 1), _cell("금액", 0, 2)],
        [_cell("인건비", 1, 0, row_span=2), _cell("연구원", 1, 1), _cell("100", 1, 2)],
        [_cell("보조원", 2, 1), _cell("50", 2, 2)],
    ))

    rows, spans = table_grid(table, _text)

    assert rows == [["구분", "항목", "금액"], ["인건비", "연구원", "100"], ["인건비", "보조원", "50"]]
    assert spans == [{"row": 1, "col": 0, "row_span": 2, "col_span": 1}]


def test_col_span_writes_the_text_once_and_leaves_the_rest_empty():
    table = ET.fromstring(_table(
        [_cell("지원 조건", 0, 0, col_span=3)],
        [_cell("기간", 1, 0), _cell("한도", 1, 1), _cell("비율", 1, 2)],
    ))

    rows, spans = table_grid(table, _text)

    assert rows == [["지원 조건", "", ""], ["기간", "한도", "비율"]]
    assert spans == [{"row": 0, "col": 0, "row_span": 1, "col_span": 3}]


def test_cells_without_address_fall_back_to_reading_order():
    table = ET.fromstring("<tbl><tr><tc><p><run><t>a</t></run></p></tc><tc><p><run><t>b</t></run></p></tc></tr></tbl>")

    assert table_grid(table, _text) == ([["a", "b"]], [])


def test_empty_rows_are_dropped_and_span_rows_follow():
    table = ET.fromstring(_table(
        [_cell("", 0, 0), _cell("", 0, 1)],
        [_cell("분류", 1, 0, row_span=2), _cell("가", 1, 1)],
        [_cell("나", 2, 1)],
    ))

    rows, spans = table_grid(table, _text)

    assert rows == [["분류", "가"], ["분류", "나"]]
    assert spans == [{"row": 0, "col": 0, "row_span": 2, "col_span": 1}]


def test_broken_addresses_cannot_blow_up_the_grid():
    table = ET.fromstring(_table([_cell("x", MAX_GRID_CELLS, MAX_GRID_CELLS)]))

    assert table_grid(table, _text) == ([], [])


def test_styles_give_font_size_bold_and_outline_level():
    styles = load_styles(ET.fromstring(HEADER))
    heading = ET.fromstring('<p styleIDRef="3"><run charPrIDRef="1"><t>추진 배경</t></run></p>')
    body = ET.fromstring(
        '<p styleIDRef="0"><run charPrIDRef="1"><t>가</t></run><run charPrIDRef="0"><t>나다라마바사</t></run></p>'
    )

    heading_layout = paragraph_layout(heading, "추진 배경", styles)
    body_layout = paragraph_layout(body, "가나다라마바사", styles)

    assert (heading_layout["font_size"], heading_layout["is_bold"]) == (16.0, True)
    assert (heading_layout["heading_level"], heading_layout["style_name"]) == (2, "Heading 2")
    # 글자 수가 많은 쪽의 글자 모양을 문단의 모양으로 본다
    assert (body_layout["font_size"], body_layout["is_bold"], body_layout["heading_level"]) == (10.0, False, None)
    assert body_layout["style_name"] == "바탕글"


def test_outline_style_becomes_a_heading_only_for_short_lines():
    layout = {"heading_level": 2, "font_size": 10.0, "is_bold": False}

    assert _classify("추진 배경", layout, 10.0) == ("HEADING", 2)
    assert _classify("본 사업은 " + "매우 긴 본문 문장입니다 " * 6, layout, 10.0) == ("PARAGRAPH", None)


def test_layout_pages_follow_repaginated_blocks():
    layout = [{"text": "a", "page_number": 1}, {"text": "b", "page_number": 1}]
    pages = [
        SimpleNamespace(text_blocks=[RawTextBlock(text="a", page_number=1)]),
        SimpleNamespace(text_blocks=[
            RawTextBlock(text="[표 1]", page_number=2, block_type="table"),
            RawTextBlock(text="b", page_number=2),
        ]),
    ]
    parsed = SimpleNamespace(metadata={"line_layout": layout}, pages=pages)

    sync_layout_pages(parsed)

    assert [entry["page_number"] for entry in layout] == [1, 2]


def test_layout_is_left_alone_when_counts_differ():
    layout = [{"text": "a", "page_number": 1}]
    parsed = SimpleNamespace(metadata={"line_layout": layout}, pages=[])

    sync_layout_pages(parsed)

    assert layout[0]["page_number"] == 1


def test_adapter_emits_layout_spans_and_aligned_table_text(tmp_path):
    section = (
        '<sec><p styleIDRef="2"><run charPrIDRef="1"><t>사업 개요</t></run></p>'
        '<p styleIDRef="0"><run charPrIDRef="0"><t>본문입니다.</t>'
        + _table(
            [_cell("구분", 0, 0), _cell("값", 0, 1)],
            [_cell("합계", 1, 0, row_span=2), _cell("1", 1, 1)],
            [_cell("2", 2, 1)],
        )
        + "</run></p></sec>"
    )
    path = tmp_path / "sample.hwpx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Contents/header.xml", HEADER)
        archive.writestr("Contents/section0.xml", section)

    parsed = HWPAdapter().extract(path, {})

    page = parsed.pages[0]
    assert [entry["text"] for entry in parsed.metadata["line_layout"]] == ["사업 개요", "본문입니다."]
    assert parsed.metadata["line_layout"][0]["heading_level"] == 1
    assert page.table_candidates[0].rows == [["구분", "값"], ["합계", "1"], ["합계", "2"]]
    assert page.table_candidates[0].spans == [{"row": 1, "col": 0, "row_span": 2, "col_span": 1}]
    assert "합계 | 2" in page.text_blocks[-1].text


def test_bold_large_date_on_a_cover_is_not_a_heading():
    layout = {"font_size": 17.0, "is_bold": True}

    assert _classify("2025년 12월", layout, 11.0) == ("PARAGRAPH", None)
    assert _classify("2025.12.21", layout, 11.0) == ("PARAGRAPH", None)
    assert _classify("추진 전략", layout, 11.0)[0] == "HEADING"


BULLET_HEADER = """<head xmlns:hh="h"><hh:bullets>
  <hh:bullet id="1" char="-" useImage="0"/>
  <hh:bullet id="2" char="" useImage="0"/>
</hh:bullets><hh:paraProperties>
  <hh:paraPr id="0"><hh:heading type="NONE" idRef="0" level="0"/></hh:paraPr>
  <hh:paraPr id="7"><hh:heading type="BULLET" idRef="1" level="0"/></hh:paraPr>
  <hh:paraPr id="8"><hh:heading type="BULLET" idRef="2" level="0"/></hh:paraPr>
</hh:paraProperties></head>"""


def test_bulleted_paragraphs_keep_their_bullet_in_body_and_cells(tmp_path):
    """HWPX 글머리표는 글이 아니라 문단 모양(paraPr heading BULLET)에 들어 있어, "- 대상 R&D과제 요약문" 의 "-" 와
    "• 헤드리스 브라우저" 의 "•" 가 본문과 표 칸에서 빠졌다(R&D 공고, UIUX 보고서, 2026-11-26). 기호 글자는
    원문 글꼴의 사설 영역 글자(Wingdings)면 "•" 로 적는다."""
    section = (
        '<sec><p paraPrIDRef="8"><run><t>헤드리스 브라우저</t></run></p>'
        '<p paraPrIDRef="0"><run><t>표 앞 문단</t>'
        + "<tbl><tr><tc><subList>"
        '<p paraPrIDRef="7"><run><t>대상 R&amp;D과제 요약문</t></run></p>'
        '<p paraPrIDRef="7"><run><t>사업계획서</t></run></p>'
        '</subList><cellAddr colAddr="0" rowAddr="0"/><cellSpan colSpan="1" rowSpan="1"/></tc>'
        '<tc><subList><p paraPrIDRef="0"><run><t>제출</t></run></p></subList>'
        '<cellAddr colAddr="1" rowAddr="0"/><cellSpan colSpan="1" rowSpan="1"/></tc></tr></tbl>'
        "</run></p></sec>"
    )
    path = tmp_path / "bullets.hwpx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Contents/header.xml", BULLET_HEADER)
        archive.writestr("Contents/section0.xml", section)

    parsed = HWPAdapter().extract(path, {})

    texts = [block.text for block in parsed.pages[0].text_blocks]
    assert texts[0] == "• 헤드리스 브라우저"
    assert texts[1] == "표 앞 문단"
    assert parsed.pages[0].table_candidates[0].rows == [["- 대상 R&D과제 요약문 / - 사업계획서", "제출"]]
