"""구형 HWP의 병합 칸과 문단 서식(hwp5_structure.py). pyhwp가 만드는 XML 모양을 흉내 낸다."""
from pathlib import Path
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree as ET

from app.pipeline.adapters import hwp_adapter as hwp
from app.pipeline.adapters.hwp5_structure import (
    add_hwp_paragraph_marks,
    add_hwp_symbol_chars,
    hwp_paragraph_layout,
    hwp_table_grid,
    load_hwp_styles,
)
from app.pipeline.adapters.hwp_adapter import HWPAdapter

DOC_INFO = (
    "<DocInfo><IdMappings>"
    '<CharShape basesize="1300" bold="0" italic="0"/>'
    '<CharShape basesize="1500" bold="1" italic="0"/>'
    '<CharShape basesize="bad" bold="0" italic="1"/>'
    '<Style local-name="바탕글" name="Normal"/>'
    '<Style local-name="개요 2" name="Outline 2"/>'
    '<Style local-name="" name="Outline 9"/>'
    "</IdMappings></DocInfo>"
)


def _paragraph(text: str, shape: str = "0", style: str = "0", inner: str = "") -> str:
    return (
        f'<Paragraph style-id="{style}"><LineSeg><Text charshape-id="{shape}">{text}</Text>{inner}</LineSeg>'
        "</Paragraph>"
    )


def _cell(text: str, **attrs: int) -> str:
    rendered = "".join(f' {name}="{value}"' for name, value in attrs.items())
    return f"<TableCell{rendered}>{_paragraph(text)}</TableCell>"


def _doc(body: str) -> bytes:
    return f"<HwpDoc>{DOC_INFO}<BodyText>{body}</BodyText></HwpDoc>".encode()


def _cell_text(cell) -> str:
    return "".join(cell.itertext()).strip()


def test_styles_are_numbered_in_document_order():
    styles = load_hwp_styles(ET.fromstring(_doc("")))

    assert styles.char_shapes["1"].font_size == 15.0 and styles.char_shapes["1"].is_bold
    assert styles.char_shapes["2"].font_size == 10.0 and styles.char_shapes["2"].is_italic
    assert styles.style_names == {"0": "바탕글", "1": "개요 2", "2": "Outline 9"}
    assert styles.outline_levels == {"1": 2, "2": 6}


def test_char_shapes_inside_the_body_are_not_counted_as_definitions():
    root = ET.fromstring(_doc('<CharShape basesize="9900" bold="1"/>'))

    assert len(load_hwp_styles(root).char_shapes) == 3


def test_paragraph_layout_uses_the_most_used_char_shape_and_outline_style():
    root = ET.fromstring(_doc(
        '<Paragraph style-id="1"><LineSeg>'
        '<Text charshape-id="0">가</Text><Text charshape-id="1">과업의 주요 내용</Text>'
        '<TableControl><Text charshape-id="0">표 안의 아주 긴 글자는 세지 않는다</Text></TableControl>'
        "</LineSeg></Paragraph>"
    ))
    paragraph = root.find("BodyText/Paragraph")

    layout = hwp_paragraph_layout(paragraph, "가과업의 주요 내용", load_hwp_styles(root))

    assert (layout["font_size"], layout["is_bold"], layout["heading_level"]) == (15.0, True, 2)
    assert layout["style_name"] == "Heading 2" and layout["page_number"] == 1


def test_paragraph_layout_without_known_shape_leaves_font_empty():
    root = ET.fromstring(_doc(_paragraph("본문", shape="77")))

    layout = hwp_paragraph_layout(root.find("BodyText/Paragraph"), "본문", load_hwp_styles(root))

    assert layout["font_size"] is None and not layout["is_bold"] and layout["style_name"] == "바탕글"


BULLET_DOC_INFO = (
    "<DocInfo><IdMappings>"
    '<Bullet char="-"/><Bullet char=""/>'
    '<ParaShape head-shape="none" numbering-bullet-id="0"/>'
    '<ParaShape head-shape="bullet" numbering-bullet-id="1"/>'
    '<ParaShape head-shape="bullet" numbering-bullet-id="2"/>'
    '<ParaShape head-shape="outline" numbering-bullet-id="1"/>'
    "</IdMappings></DocInfo>"
)


def _shaped(text: str, shape_id: str) -> str:
    return f'<Paragraph parashape-id="{shape_id}"><LineSeg><Text charshape-id="0">{text}</Text></LineSeg></Paragraph>'


def test_bulleted_paragraphs_keep_their_bullet_in_body_and_cells():
    # 1_지능형 항만수요예측(컨설팅) HWP: 글머리표가 글이 아니라 문단 모양(head-shape=bullet)에 있어
    # "- 대상 항만(31개)" 의 "-" 가 본문에서 빠졌다(2026-11-26 기호 대조)
    body = (
        _shaped("대상 항만(31개)", "1") + _shaped("기호 글꼴 글머리표", "2") + _shaped("일반 문단", "0")
        + _shaped("개요 번호 문단", "3") + _shaped("- 이미 기호가 있는 문단", "1")
        + f'<TableControl><TableBody><TableCell>{_shaped("칸 안 항목", "1")}</TableCell></TableBody></TableControl>'
    )
    root = ET.fromstring(f"<HwpDoc>{BULLET_DOC_INFO}<BodyText>{body}</BodyText></HwpDoc>".encode())

    add_hwp_paragraph_marks(root)

    texts = [hwp._hwp_collect_text(p).strip() for p in root.iter("Paragraph")]
    assert texts == [
        "- 대상 항만(31개)", "● 기호 글꼴 글머리표", "일반 문단", "개요 번호 문단", "- 이미 기호가 있는 문단", "- 칸 안 항목",
    ]


def test_row_span_keeps_columns_aligned_and_repeats_the_text():
    body = ET.fromstring(
        "<TableBody>"
        f"<TableRow>{_cell('구분', row=0, col=0, rowspan=2, colspan=1)}{_cell('A', row=0, col=1)}</TableRow>"
        f"<TableRow>{_cell('B', row=1, col=1)}</TableRow>"
        "</TableBody>"
    )

    rows, spans = hwp_table_grid(body, _cell_text)

    assert rows == [["구분", "A"], ["구분", "B"]]
    assert spans == [{"row": 0, "col": 0, "row_span": 2, "col_span": 1}]


def test_col_span_writes_the_text_once():
    body = ET.fromstring(
        "<TableBody>"
        f"<TableRow>{_cell('제목', row=0, col=0, colspan=2)}</TableRow>"
        f"<TableRow>{_cell('가', row=1, col=0)}{_cell('나', row=1, col=1)}</TableRow>"
        "</TableBody>"
    )

    rows, spans = hwp_table_grid(body, _cell_text)

    assert rows == [["제목", ""], ["가", "나"]]
    assert spans == [{"row": 0, "col": 0, "row_span": 1, "col_span": 2}]


def test_cells_without_addresses_fall_back_to_their_order():
    body = ET.fromstring(f"<TableBody><TableRow>{_cell('x')}{_cell('y')}</TableRow><Other/></TableBody>")

    assert hwp_table_grid(body, _cell_text) == ([["x", "y"]], [])


def test_broken_addresses_are_skipped():
    body = ET.fromstring(f"<TableBody><TableRow>{_cell('x', row=-1, col=0)}</TableRow></TableBody>")

    assert hwp_table_grid(body, _cell_text) == ([], [])


def test_extract_hwp_fills_line_layout_and_table_spans():
    table = (
        "<TableControl><TableBody>"
        f"<TableRow>{_cell('구분', row=0, col=0, rowspan=2)}{_cell('A', row=0, col=1)}</TableRow>"
        f"<TableRow>{_cell('B', row=1, col=1)}</TableRow>"
        "</TableBody></TableControl>"
    )
    xml = _doc(_paragraph("1. 과업명", shape="1", inner=table) + _paragraph("본문입니다"))
    module = MagicMock()
    module.Hwp5File.return_value.xmlevents.return_value.dump.side_effect = (
        lambda buf, xml_declaration: buf.write(xml)
    )

    with patch.dict("sys.modules", {"hwp5": MagicMock(), "hwp5.xmlmodel": module}), \
         patch.object(hwp, "_hwp_bindata_named", return_value=[]):
        doc = HWPAdapter().extract(Path("a.hwp"), {})

    layout = doc.metadata["line_layout"]
    assert [(line["text"], line["font_size"], line["is_bold"]) for line in layout] == [
        ("1. 과업명", 15.0, True), ("본문입니다", 13.0, False),
    ]
    paragraphs = [block for block in doc.pages[0].text_blocks if block.block_type != "table"]
    assert len(layout) == len(paragraphs)
    assert doc.pages[0].table_candidates[0].spans == [{"row": 0, "col": 0, "row_span": 2, "col_span": 1}]


SYMBOL_DOC_INFO = (
    '<DocInfo><IdMappings ko-fonts="2" en-fonts="2" cn-fonts="2" jp-fonts="2" other-fonts="2" symbol-fonts="2" user-fonts="2">'
    + '<FaceName name="맑은 고딕"/><FaceName name="Symbol"/>' * 7
    + '<CharShape basesize="1100"><FontFace ko="0" en="0" cn="0" jp="0" other="0" symbol="0" user="0"/></CharShape>'
    + '<CharShape basesize="1100"><FontFace ko="0" en="0" cn="0" jp="0" other="0" symbol="1" user="1"/></CharShape>'
    + "</IdMappings></DocInfo>"
)


def test_symbol_font_codes_in_body_text_are_written_as_the_symbols_they_show():
    # 제안요청서 HWP: " 사업명", " 세부" 가 파싱 본문과 청크에서 빈칸으로 보였다(2026-11-26).
    # 한글은 이 코드를 맑은 고딕으로 적어 두지만 쓰임새는 Wingdings 다. Symbol 글꼴 글자는 Symbol 표로 읽는다
    body = (
        '<Paragraph parashape-id="0"><LineSeg><Text charshape-id="0"> 사업명 </Text></LineSeg></Paragraph>'
        '<Paragraph parashape-id="0"><LineSeg><Text charshape-id="0"> 세부</Text>'
        '<Text charshape-id="1"> 오차 </Text></LineSeg></Paragraph>'
    )
    root = ET.fromstring(f"<HwpDoc>{SYMBOL_DOC_INFO}<BodyText>{body}</BodyText></HwpDoc>".encode())

    add_hwp_symbol_chars(root)

    texts = [hwp._hwp_collect_text(p) for p in root.iter("Paragraph")]
    assert texts == ["❑ 사업명 ", "❍ 세부 오차 μ"]
