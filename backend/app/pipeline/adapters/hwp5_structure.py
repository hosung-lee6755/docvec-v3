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
    _bullet_text,
    grid_from_cells,
    outline_level,
)
from app.pipeline.adapters.symbol_fonts import hancom_symbol_kind, with_symbol_font_chars

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


def _hwp_paragraph_marks(root) -> dict[str, str]:
    """글머리표 문단 모양(ParaShape head-shape="bullet")의 번호(문서 순서, 0부터) → 붙일 기호.
    numbering-bullet-id 는 Bullet 정의의 1부터 센 번호다."""
    bullets: list[str] = []
    shapes: list[tuple[str | None, int]] = []
    for section in root:
        if section.tag == BODY_TAG:
            continue
        for elem in section.iter():
            if elem.tag == "Bullet":
                bullets.append(_bullet_text(elem.get("char", "")))
            elif elem.tag == "ParaShape":
                shapes.append((elem.get("head-shape"), _int_attr(elem, "numbering-bullet-id", 0)))
    return {
        str(index): bullets[bullet_id - 1]
        for index, (head_shape, bullet_id) in enumerate(shapes)
        if head_shape == "bullet" and 1 <= bullet_id <= len(bullets)
    }


def add_hwp_paragraph_marks(root) -> None:
    """글머리표 문단 앞에 기호 글(<Text>)을 넣는다. 본문 문단과 표 칸 문단을 읽는 코드가 모두 이 글을 읽는다.

    구형 HWP 도 HWPX 처럼 글머리표가 글이 아니라 문단 모양에 있어, "- 대상 항만(31개)" 의 "-" 가 본문에서
    빠졌다(1_지능형 항만수요예측 컨설팅, 2026-11-26). 처음 대조에서는 글머리표 모양 문단이 없다고 보았으나 표본을
    잘못 골랐던 것으로, 올린 HWP 10건 중 6건에 있다. 번호 문단(number)은 다루지 않는다. 글이 이미 그 기호로
    시작하면 두 번 붙이지 않는다. root 는 pyhwp 가 이 문서를 읽으려고 방금 만든 XML 이라 고쳐도 원본에는 영향이 없다."""
    marks = _hwp_paragraph_marks(root)
    if not marks:
        return
    body = root.find(BODY_TAG)
    for paragraph in (body.iter("Paragraph") if body is not None else ()):
        mark = marks.get(paragraph.get("parashape-id"))
        if mark is None:
            continue
        own_text = "".join(t.text or "" for t in paragraph.iter("Text"))
        if own_text.lstrip().startswith(mark):
            continue
        text = paragraph.makeelement("Text", {})
        text.text = f"{mark} "
        paragraph.insert(0, text)


# 글꼴 이름(FaceName)은 언어 무리 순서대로 이어 적혀 있고, 무리마다 몇 개인지는 IdMappings 에 있다
_FONT_GROUPS = ("ko", "en", "cn", "jp", "other", "symbol", "user")


def _hwp_symbol_kinds(root) -> list[str]:
    """글자 모양(CharShape, 문서 순서)마다 기호 글꼴 코드를 읽을 글꼴 종류. 기호·사용자 글자 무리의 글꼴을 본다."""
    doc_info = root.find("DocInfo")
    if doc_info is None:
        return []
    mappings = next(doc_info.iter("IdMappings"), None)
    faces = [elem.get("name") or "" for elem in doc_info.iter("FaceName")]
    starts: dict[str, int] = {}
    offset = 0
    for group in _FONT_GROUPS:
        starts[group] = offset
        offset += _int_attr(mappings, f"{group}-fonts", 0) if mappings is not None else 0

    def face(font_face, group: str) -> str | None:
        if font_face is None:
            return None
        position = _int_attr(font_face, group, -1)
        index = starts[group] + position
        return faces[index] if position >= 0 and index < len(faces) else None

    kinds: list[str] = []
    for char_shape in doc_info.iter("CharShape"):
        font_face = char_shape.find("FontFace")
        kinds.append(hancom_symbol_kind([face(font_face, "symbol"), face(font_face, "user")]))
    return kinds


def add_hwp_symbol_chars(root) -> None:
    """본문 글(<Text>)의 기호 글꼴 코드(U+F020~F0FF)를 화면에 보이는 글자로 바꾼다(symbol_fonts.py).

    제안요청서 HWP 의 "\\uf071 사업명", "\\uf06d 세부" 가 파싱 본문과 청크에서 빈칸으로 보였다(2026-11-26). 글자 모양의
    글꼴이 Symbol 이면 Symbol 표로, 아니면 한글 문서의 쓰임새대로 Wingdings 로 읽는다. root 는 방금 만든 XML 이다."""
    body = root.find(BODY_TAG)
    if body is None:
        return
    kinds = _hwp_symbol_kinds(root)
    for text in body.iter("Text"):
        if not text.text:
            continue
        index = _int_attr(text, "charshape-id", -1)
        kind = kinds[index] if 0 <= index < len(kinds) else "wingdings"
        text.text = with_symbol_font_chars(text.text, kind)


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
