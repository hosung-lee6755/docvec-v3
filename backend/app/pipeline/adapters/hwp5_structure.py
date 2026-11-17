"""구형 HWP(바이너리)의 병합 칸과 문단 서식 읽기(2026-11-17).

HWPX에서 하던 일(hwpx_structure.py)을 pyhwp가 만든 XML에도 한다. 처음에는 pyhwp가 글자 크기와 굵기를
안정적으로 내주지 않는다고 보고 넣지 않았는데, 실제 문서 두 건으로 확인하니 다음 값이 모두 나온다.

- DocInfo의 CharShape: basesize(1/100pt), bold, italic. 본문의 Text는 charshape-id로 이것을 가리킨다.
- DocInfo의 Style: local-name("개요 1"), name("Outline 1"). 본문의 Paragraph는 style-id로 가리킨다.
- TableCell: col, row, colspan, rowspan.

CharShape와 Style의 id는 따로 적혀 있지 않고 문서에 나온 순서(0부터)다.
"""
from app.pipeline.adapters.hwpx_structure import (
    BODY_FONT_FALLBACK,
    CharShape,
    HwpxStyles,
    grid_from_cells,
    outline_level,
)

# basesize는 1/100pt 단위다
_SIZE_UNIT = 100.0
# 문단에 걸려 있는 표와 도형의 글자는 그 문단의 글자로 세지 않는다
_ANCHORED_CONTROLS = ("TableControl", "GShapeObjectControl")
BODY_TAG = "BodyText"


def _int_attr(elem, name: str, default: int) -> int:
    try:
        return int(elem.get(name, default))
    except (TypeError, ValueError):
        return default


def load_hwp_styles(root) -> HwpxStyles:
    """본문 밖(DocInfo)에서 글자 모양과 스타일을 읽는다."""
    char_shapes: dict[str, CharShape] = {}
    outline_levels: dict[str, int] = {}
    style_names: dict[str, str] = {}
    for section in root:
        if section.tag == BODY_TAG:
            continue
        for elem in section.iter():
            if elem.tag == "CharShape":
                char_shapes[str(len(char_shapes))] = CharShape(
                    font_size=_int_attr(elem, "basesize", int(BODY_FONT_FALLBACK * _SIZE_UNIT)) / _SIZE_UNIT,
                    is_bold=elem.get("bold") == "1",
                    is_italic=elem.get("italic") == "1",
                )
            elif elem.tag == "Style":
                style_id = str(len(style_names))
                local_name = (elem.get("local-name") or "").strip()
                english_name = (elem.get("name") or "").strip()
                style_names[style_id] = local_name or english_name
                level = outline_level(local_name, english_name)
                if level:
                    outline_levels[style_id] = level
    return HwpxStyles(char_shapes=char_shapes, outline_levels=outline_levels, style_names=style_names)


def _own_text_lengths(elem, lengths: dict[str, int]) -> None:
    for child in elem:
        if child.tag == "Text":
            ref = child.get("charshape-id")
            if ref is not None and child.text:
                lengths[ref] = lengths.get(ref, 0) + len(child.text)
        elif child.tag not in _ANCHORED_CONTROLS:
            _own_text_lengths(child, lengths)


def hwp_paragraph_layout(paragraph, text: str, styles: HwpxStyles) -> dict:
    """구조 분석이 읽는 줄 정보 한 건. 모양은 hwpx_structure.paragraph_layout과 같다."""
    lengths: dict[str, int] = {}
    _own_text_lengths(paragraph, lengths)
    shape = styles.char_shapes.get(max(lengths, key=lengths.get)) if lengths else None
    style_id = paragraph.get("style-id")
    level = styles.outline_levels.get(style_id)
    return {
        "page_number": 1,
        "text": text,
        "bbox": None,
        "font_size": shape.font_size if shape else None,
        "is_bold": bool(shape and shape.is_bold),
        "is_italic": bool(shape and shape.is_italic),
        "style_name": f"Heading {level}" if level else (styles.style_names.get(style_id) or None),
        "font_name": None,
        "heading_level": level,
    }


def hwp_table_grid(table_body, cell_text) -> tuple[list[list[str]], list[dict]]:
    """TableBody를 열이 맞는 격자로 만든다. 돌려주는 값은 hwpx_structure.table_grid와 같다.
    칸에 주소가 없으면(오래된 pyhwp, 시험용 XML) 나온 순서를 주소로 쓴다."""
    cells: list[tuple[int, int, int, int, str]] = []
    rows = [child for child in table_body if child.tag == "TableRow"]
    for row_index, table_row in enumerate(rows):
        next_col = 0
        for cell in table_row:
            if cell.tag != "TableCell":
                continue
            row = _int_attr(cell, "row", row_index)
            col = _int_attr(cell, "col", next_col)
            row_span = max(1, _int_attr(cell, "rowspan", 1))
            col_span = max(1, _int_attr(cell, "colspan", 1))
            next_col = col + col_span
            if row < 0 or col < 0:
                continue
            cells.append((row, col, row_span, col_span, cell_text(cell)))
    return grid_from_cells(cells)
