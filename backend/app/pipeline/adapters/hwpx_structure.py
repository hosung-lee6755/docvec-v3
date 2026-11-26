"""HWPX의 병합 셀과 문단 서식 읽기(전체 점검 2-2, 2-12, 2026-11-16).

표: 예전에는 한 줄에 실제로 들어 있는 칸만 순서대로 늘어놓았다. 세로로 합친 칸이 있으면 다음 줄에는
그 칸이 아예 없어서 뒤의 값이 한 열씩 앞으로 당겨졌다. 여기서는 칸의 주소(cellAddr)와 합친 크기
(cellSpan)로 격자를 만들어 열을 맞춘다. 세로로 합친 칸의 글은 아래 줄에도 되풀이해 적는다(줄 하나만
잘려 나가도 무슨 항목의 값인지 알 수 있게). 가로로 합친 칸은 첫 칸에만 적고 나머지는 비운다(같은 말이
옆으로 여러 번 되풀이되지 않게). 화면이 원래 모양으로 그릴 수 있도록 합친 칸의 위치와 크기는 따로 남긴다.

문단 서식: 한글 문서는 제목에도 "바탕글" 스타일을 그대로 두고 글자만 키우는 일이 많다. 그래서 스타일
이름만으로는 제목을 가릴 수 없고, 문단에서 가장 많이 쓰인 글자 모양(charPr)의 크기와 굵기를 함께 넘긴다.
"개요 N" 스타일을 쓴 문단은 그 수준을 제목 수준으로 넘긴다.
"""
import re
from dataclasses import dataclass, field

from app.pipeline.adapters.table_merge import fill_columns

BODY_FONT_FALLBACK = 10.0
# charPr의 height는 1/100pt 단위다
_HEIGHT_UNIT = 100.0
_OUTLINE_NAME_RE = re.compile(r"^(?:개요|Outline)\s*(\d+)$", re.IGNORECASE)
MAX_HEADING_LEVEL = 6
# 주소가 깨진 파일이 격자를 끝없이 키우지 못하게 막는다
MAX_GRID_CELLS = 20000


def local_tag(elem) -> str:
    tag = elem.tag
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _int_attr(elem, name: str, default: int) -> int:
    try:
        return int(elem.get(name, default))
    except (TypeError, ValueError):
        return default


def outline_level(*names: str) -> int | None:
    """스타일 이름 가운데 "개요 N"이나 "Outline N"이 있으면 그 수준을 돌려준다."""
    for name in names:
        match = _OUTLINE_NAME_RE.match((name or "").strip())
        if match:
            return min(int(match.group(1)), MAX_HEADING_LEVEL)
    return None


@dataclass(frozen=True)
class CharShape:
    font_size: float
    is_bold: bool
    is_italic: bool


@dataclass(frozen=True)
class HwpxStyles:
    char_shapes: dict[str, CharShape] = field(default_factory=dict)
    # 문단 스타일 id → 개요 수준(1부터)
    outline_levels: dict[str, int] = field(default_factory=dict)
    style_names: dict[str, str] = field(default_factory=dict)
    # 문단 모양 id → 그 문단 앞에 붙는 글머리표 글("-", "•")
    para_marks: dict[str, str] = field(default_factory=dict)


# 글머리표 글자가 기호 글꼴(Wingdings 등)의 사설 영역 글자면 화면처럼 "•" 로 적는다
_PRIVATE_USE = range(0xE000, 0xF900)
_DEFAULT_BULLET = "•"


def _bullet_text(char: str) -> str:
    char = (char or "").strip()
    if not char or any(ord(c) in _PRIVATE_USE for c in char):
        return _DEFAULT_BULLET
    return char


def _paragraph_marks(header_root) -> dict[str, str]:
    """글머리표 문단 모양(paraPr > heading type="BULLET")마다 붙일 기호. HWPX 글머리표는 글이 아니라 문단 모양에
    들어 있어 문단 글만 읽으면 "- 대상 R&D과제 요약문" 의 "-" 가 빠졌다(R&D 공고, 2026-11-26). 번호 문단(NUMBER)은
    올린 문서에 없어 다루지 않는다."""
    bullets = {
        elem.get("id"): _bullet_text(elem.get("char", ""))
        for elem in header_root.iter() if local_tag(elem) == "bullet" and elem.get("id") is not None
    }
    marks: dict[str, str] = {}
    for elem in header_root.iter():
        if local_tag(elem) != "paraPr" or elem.get("id") is None:
            continue
        heading = next((child for child in elem.iter() if local_tag(child) == "heading"), None)
        if heading is not None and heading.get("type") == "BULLET" and heading.get("idRef") in bullets:
            marks[elem.get("id")] = bullets[heading.get("idRef")]
    return marks


def add_paragraph_marks(section_root, styles: "HwpxStyles") -> None:
    """글머리표 문단의 첫 글 조각 앞에 기호 글(<t>)을 넣는다. 본문 문단과 표 칸 문단을 읽는 코드가 모두 이 글을 읽는다.
    section_root 는 이 문서를 읽으려고 방금 푼 XML 이라 고쳐도 원본에는 영향이 없다."""
    if not styles.para_marks:
        return
    for paragraph in section_root.iter():
        if local_tag(paragraph) != "p":
            continue
        mark = styles.para_marks.get(paragraph.get("paraPrIDRef"))
        run = next((child for child in paragraph if local_tag(child) == "run"), None)
        if mark is None or run is None:
            continue
        namespace = run.tag[: -len("run")]
        text = run.makeelement(f"{namespace}t", {})
        text.text = f"{mark} "
        run.insert(0, text)


def load_styles(header_root) -> HwpxStyles:
    """Contents/header.xml에서 글자 모양과 스타일, 글머리표 문단 모양을 읽는다."""
    char_shapes: dict[str, CharShape] = {}
    outline_levels: dict[str, int] = {}
    style_names: dict[str, str] = {}
    for elem in header_root.iter():
        tag = local_tag(elem)
        if tag == "charPr" and elem.get("id") is not None:
            children = {local_tag(child) for child in elem}
            char_shapes[elem.get("id")] = CharShape(
                font_size=_int_attr(elem, "height", int(BODY_FONT_FALLBACK * _HEIGHT_UNIT)) / _HEIGHT_UNIT,
                is_bold="bold" in children,
                is_italic="italic" in children,
            )
        elif tag == "style" and elem.get("id") is not None:
            name = (elem.get("name") or elem.get("engName") or "").strip()
            style_names[elem.get("id")] = name
            level = outline_level(name, elem.get("engName") or "")
            if level:
                outline_levels[elem.get("id")] = level
    return HwpxStyles(
        char_shapes=char_shapes, outline_levels=outline_levels, style_names=style_names,
        para_marks=_paragraph_marks(header_root),
    )


def _dominant_char_shape(paragraph, styles: HwpxStyles) -> CharShape | None:
    """문단에서 글자 수가 가장 많은 글자 모양. 표 안의 글자는 세지 않는다."""
    lengths: dict[str, int] = {}

    def text_length(elem) -> int:
        total = 0
        for child in elem:
            tag = local_tag(child)
            if tag == "t":
                total += len("".join(child.itertext()))
            elif tag != "tbl":
                total += text_length(child)
        return total

    for run in paragraph:
        if local_tag(run) != "run":
            continue
        ref = run.get("charPrIDRef")
        length = text_length(run)
        if ref is not None and length:
            lengths[ref] = lengths.get(ref, 0) + length
    if not lengths:
        return None
    return styles.char_shapes.get(max(lengths, key=lengths.get))


def paragraph_layout(paragraph, text: str, styles: HwpxStyles) -> dict:
    """구조 분석이 읽는 줄 정보 한 건. 쪽 번호는 쪽을 다시 나눈 뒤에 맞춘다(sync_layout_pages)."""
    shape = _dominant_char_shape(paragraph, styles)
    style_id = paragraph.get("styleIDRef")
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


def table_grid(table, cell_text) -> tuple[list[list[str]], list[dict]]:
    """표를 열이 맞는 격자로 만든다. (줄 목록, 합친 칸 목록)을 돌려준다.
    합친 칸은 {"row", "col", "row_span", "col_span"}이고 줄과 열은 0부터 센다."""
    cells: list[tuple[int, int, int, int, str]] = []
    for row_index, tr in enumerate(child for child in table if local_tag(child) == "tr"):
        next_col = 0
        for tc in tr:
            if local_tag(tc) != "tc":
                continue
            addr = next((c for c in tc if local_tag(c) == "cellAddr"), None)
            span = next((c for c in tc if local_tag(c) == "cellSpan"), None)
            row = _int_attr(addr, "rowAddr", row_index) if addr is not None else row_index
            col = _int_attr(addr, "colAddr", next_col) if addr is not None else next_col
            row_span = max(1, _int_attr(span, "rowSpan", 1)) if span is not None else 1
            col_span = max(1, _int_attr(span, "colSpan", 1)) if span is not None else 1
            next_col = col + col_span
            if row < 0 or col < 0:
                continue
            cells.append((row, col, row_span, col_span, cell_text(tc)))
    return grid_from_cells(cells)


def grid_from_cells(
    cells: list[tuple[int, int, int, int, str]], context: list[tuple[int, int, int, int, str]] | None = None,
) -> tuple[list[list[str]], list[dict]]:
    """(줄, 열, 줄 수, 열 수, 글) 목록으로 격자와 합친 칸 목록을 만든다. HWPX, 구형 HWP, DOCX, Docling 이 함께 쓴다.

    context 는 머리글을 떼고 본문만 넘길 때 머리글까지 담은 칸 목록이다(머리글 줄 번호는 음수). 가로로 합친 칸을
    열마다 채울지 머리글을 보고 정한다."""
    if not cells:
        return [], []
    height = max(row + row_span for row, _, row_span, _, _ in cells)
    width = max(col + col_span for _, col, _, col_span, _ in cells)
    if height * width > MAX_GRID_CELLS:
        return [], []

    grid = [["" for _ in range(width)] for _ in range(height)]
    spans: list[dict] = []
    for cell in cells:
        row, col, row_span, col_span, text = cell
        # 합친 칸을 어느 열에 적을지는 모든 형식이 같은 규칙을 쓴다(table_merge.fill_columns, 2026-11-25)
        targets = fill_columns(cell, context or cells, width)
        for offset in range(row_span):
            for target in targets:
                grid[row + offset][target] = text
        if row_span > 1 or col_span > 1:
            spans.append({"row": row, "col": col, "row_span": row_span, "col_span": col_span})

    # 글이 하나도 없는 줄은 뺀다. 줄이 빠지면 합친 칸의 줄 번호도 그만큼 당긴다
    kept = [index for index, row in enumerate(grid) if any(row)]
    new_index = {old: new for new, old in enumerate(kept)}
    rows = [grid[index] for index in kept]
    adjusted: list[dict] = []
    for span in spans:
        covered = [new_index[r] for r in range(span["row"], span["row"] + span["row_span"]) if r in new_index]
        if not covered:
            continue
        if len(covered) > 1 or span["col_span"] > 1:
            adjusted.append({**span, "row": covered[0], "row_span": len(covered)})
    return rows, adjusted


def sync_layout_pages(parsed) -> None:
    """쪽을 다시 나눈 뒤 줄 정보의 쪽 번호를 글 조각에 맞춘다. 줄 정보는 문단 조각과 같은 순서로
    하나씩 만들어지므로, 수가 같을 때만 순서대로 옮겨 적는다(다르면 건드리지 않는다)."""
    layout = parsed.metadata.get("line_layout") or []
    paragraphs = [
        block for page in parsed.pages for block in page.text_blocks if block.block_type != "table"
    ]
    if not layout or len(layout) != len(paragraphs):
        return
    for entry, block in zip(layout, paragraphs):
        entry["page_number"] = block.page_number
