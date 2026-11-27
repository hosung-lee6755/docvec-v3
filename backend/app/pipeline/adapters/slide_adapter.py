"""PPTX 어댑터(전체 점검 1-2).

슬라이드 하나가 한 쪽이다. 제목 자리의 글은 제목으로, 표는 표로, 그림은 그림 인식 대상으로 넘긴다.
도형은 위에서 아래, 왼쪽에서 오른쪽 순서로 읽고, 발표자 노트는 슬라이드 끝에 붙인다.
"""
from pathlib import Path

from app.pipeline.adapters.base import (
    AdapterCapabilities,
    BaseAdapter,
    RawImageRegion,
    RawPage,
    RawParsedDocument,
)
from app.pipeline.adapters.simple_layout import PAGE_HEIGHT, PAGE_WIDTH, BlockCollector, failed
from app.pipeline.adapters.symbol_fonts import symbol_char, symbol_font_kind, with_symbol_font_chars

_EMU_PER_POINT = 12700
NOTES_LABEL = "발표자 노트"


def _points(emu) -> float:
    return float(emu or 0) / _EMU_PER_POINT


def _reading_order(shapes) -> list:
    return sorted(shapes, key=lambda s: (s.top or 0, s.left or 0))


def _flatten(shapes) -> list:
    """묶인 도형을 풀어 읽는 순서대로 늘어놓는다."""
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    flat = []
    for shape in _reading_order(shapes):
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            flat.extend(_flatten(shape.shapes))
        else:
            flat.append(shape)
    return flat


def _bbox(shape) -> tuple[float, float, float, float]:
    left, top = _points(shape.left), _points(shape.top)
    return (left, top, left + _points(shape.width), top + _points(shape.height))


# 문단 글머리표(buChar)·자동 번호(buAutoNum). 글이 아니라 문단 서식이라 예전에는 "✓ 데이터 수집" 의 "✓" 가
# 빠졌다(산업단지 발표자료, 2026-11-26). 기호 글꼴 글자는 화면 모양으로 적고(symbol_fonts.py), 표가 없는 기호
# 글꼴(Webdings, Wingdings 2·3)이나 표에 없는 글자는 "•" 로 적는다.
_SYMBOL_FONTS = ("wingdings", "symbol", "webdings")
_DEFAULT_BULLET = "•"
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_ROMAN = ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
          (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"))


def _roman(number: int) -> str:
    out = []
    for value, letters in _ROMAN:
        count, number = divmod(number, value)
        out.append(letters * count)
    return "".join(out)


def _auto_number(kind: str, number: int) -> str:
    """buAutoNum 형식(arabicPeriod, alphaLcParenR, romanUcPeriod, circleNumDbPlain 등)대로 적은 번호."""
    if kind.startswith("circleNum"):
        return _CIRCLED[number - 1] if 0 < number <= len(_CIRCLED) else str(number)
    if kind.startswith("alpha"):
        core = chr(ord("a") + (number - 1) % 26)
    elif kind.startswith("roman"):
        core = _roman(number)
    else:
        core = str(number)
    if "Uc" in kind:
        core = core.upper()
    if kind.endswith("ParenBoth"):
        return f"({core})"
    if kind.endswith("ParenR"):
        return f"{core})"
    if kind.endswith("Period"):
        return f"{core}."
    return core


def _bullet_char(char: str, typeface: str) -> str:
    if any(font in typeface.lower() for font in _SYMBOL_FONTS):
        return symbol_char(char, symbol_font_kind(typeface)) or _DEFAULT_BULLET
    return char.strip() or _DEFAULT_BULLET


def _run_text(run) -> str:
    """글자 묶음의 글. sym 글꼴이 기호 글꼴이면 기호 글꼴 코드(U+F0xx)를 화면에 보이는 글자로 바꾼다. 예전에는
    "\\uf0e0 2023년" 의 화살표가 파싱 본문과 청크에서 빈칸으로 보였다(산업단지 완료보고, 2026-11-26)."""
    properties = run._r.rPr
    sym = next((child for child in properties if child.tag.endswith("}sym")), None) if properties is not None else None
    return with_symbol_font_chars(run.text, symbol_font_kind(sym.get("typeface")) if sym is not None else None)


def _with_run_symbols(paragraphs, text: str) -> str:
    """paragraphs 의 글자 묶음 중 sym 글꼴이 기호 글꼴인 묶음의 코드만 text 안에서 화면 글자로 바꾼 새 글."""
    replaced: dict[str, str] = {}
    for paragraph in paragraphs:
        for run in paragraph.runs:
            shown = _run_text(run)
            replaced.update((code, char) for code, char in zip(run.text, shown, strict=True) if code != char)
    return "".join(replaced.get(char, char) for char in text) if replaced else text


def _cell_text(cell) -> str:
    """표 칸의 글(python-pptx 의 cell.text, 문단 안 줄바꿈 포함). 기호 글꼴 글자 묶음에 든 코드만 화면 글자로 바꾼다."""
    return _with_run_symbols(cell.text_frame.paragraphs, cell.text)


def _paragraph_text(paragraph) -> str:
    """문단 글. 글자 묶음만 이으면 문단 안 줄바꿈(<a:br/>)과 필드(<a:fld>, 날짜·쪽 번호)가 빠져 줄 앞뒤 낱말이
    붙었다(2026-11-26 대조). python-pptx 의 paragraph.text 는 줄바꿈을 "\\v" 로 적으므로 줄바꿈으로 바꾼다."""
    return _with_run_symbols((paragraph,), paragraph.text).replace("\v", "\n")


def _paragraph_mark(paragraph, counters: dict[int, tuple[str, int]]) -> str:
    """문단 앞에 화면이 그리는 기호. counters 는 수준마다 이어 매기는 자동 번호(형식, 마지막 번호)다."""
    properties = paragraph._p.pPr
    level = paragraph.level
    children = {child.tag.rsplit("}", 1)[-1]: child for child in properties} if properties is not None else {}
    if "buAutoNum" in children:
        auto = children["buAutoNum"]
        kind = auto.get("type", "arabicPeriod")
        previous = counters.get(level)
        number = previous[1] + 1 if previous and previous[0] == kind else int(auto.get("startAt", "1"))
        counters[level] = (kind, number)
        return _auto_number(kind, number)
    counters.pop(level, None)
    if "buChar" in children and "buNone" not in children:
        typeface = children["buFont"].get("typeface", "") if "buFont" in children else ""
        return _bullet_char(children["buChar"].get("char", ""), typeface)
    return ""


def _shape_text(shape) -> str:
    lines: list[str] = []
    counters: dict[int, tuple[str, int]] = {}
    for paragraph in shape.text_frame.paragraphs:
        text = _paragraph_text(paragraph).strip()
        if not text:
            continue
        mark = _paragraph_mark(paragraph, counters)
        lines.append(f"{mark} {text}" if mark else text)
    return "\n".join(lines)


# 제목 자리(placeholder)가 없는 슬라이드의 제목 고르기(2026-11-25). 글상자로만 꾸민 발표 자료는 제목 자리가 없어
# 슬라이드 제목이 하나도 잡히지 않았다. 슬라이드 위쪽 띠 안의 짧은 글 가운데 글자가 가장 큰 것을 제목으로 삼고,
# 글자 크기가 적힌 큰 글이 없으면 맨 위 띠의 짧은 글을 제목으로 삼는다.
_TITLE_BAND = 0.3            # 슬라이드 높이에서 제목을 찾는 위쪽 비율
_UNSIZED_TITLE_BAND = 0.15   # 글자 크기를 알 수 없는 글은 더 위쪽에 있어야 제목으로 본다
_TITLE_MIN_POINTS = 14.0     # 본문·도형 글(9~12pt)과 가르는 제목 글자 크기
_TITLE_MAX_CHARS = 40


def _font_points(shape) -> float | None:
    sizes = [
        run.font.size.pt
        for paragraph in shape.text_frame.paragraphs for run in paragraph.runs if run.font.size is not None
    ]
    return max(sizes) if sizes else None


def _is_title_like(text: str) -> bool:
    lines = text.split("\n")
    return 0 < len(text) <= _TITLE_MAX_CHARS and len(lines) <= 2 and sum(ch.isalpha() for ch in text) >= 2


def _fallback_title_shape(shapes, slide_height: float):
    """제목 자리가 없을 때 제목으로 쓸 글상자. 없으면 None."""
    sized, unsized = [], []
    for shape in shapes:
        if not getattr(shape, "has_text_frame", False) or not shape.has_text_frame:
            continue
        ratio = _points(shape.top) / slide_height if slide_height else 1.0
        if ratio > _TITLE_BAND or not _is_title_like(_shape_text(shape)):
            continue
        points = _font_points(shape)
        if points is not None and points >= _TITLE_MIN_POINTS:
            sized.append((-points, ratio, shape))
        elif points is None and ratio <= _UNSIZED_TITLE_BAND:
            unsized.append((ratio, shape))
    if sized:
        return min(sized, key=lambda item: item[:2])[2]
    if unsized:
        return min(unsized, key=lambda item: item[0])[1]
    return None


# 레이아웃 고정 글로 받아들일 최소 글자(문자) 수
_MIN_FIXED_TEXT_LETTERS = 2


def _fixed_texts(shapes) -> list[str]:
    """레이아웃·마스터에 놓인 고정 도형의 글(자리 표시자는 뺀다). 표는 칸 글을 줄마다 " / " 로 잇는다."""
    texts: list[str] = []
    for shape in _flatten(shapes):
        if shape.is_placeholder:
            continue
        if getattr(shape, "has_table", False) and shape.has_table:
            for row in shape.table.rows:
                cells = [_cell_text(cell).strip() for cell in row.cells if _cell_text(cell).strip()]
                if cells:
                    texts.append(" / ".join(cells))
        elif shape.has_text_frame and _shape_text(shape):
            texts.append(_shape_text(shape))
    # 구간 번호("Ⅰ", "Ⅱ"), 쪽 번호 자리("#"), 장식("-  -")은 글이 아니다(산업단지 완료보고 발표자료)
    return [text for text in texts if sum(char.isalpha() for char in text) >= _MIN_FIXED_TEXT_LETTERS]


def _new_background_texts(slide, seen: set[str]) -> list[str]:
    """이 슬라이드가 처음 쓰는 레이아웃과 마스터의 고정 글. 표지 레이아웃의 사업명, 보안 등급처럼 화면에는 보이지만
    슬라이드 도형이 아니라 빠지던 글이다(KMI 화면설계서, 2026-11-25). 같은 배경을 쓰는 슬라이드마다 되풀이하면
    머리말처럼 검색을 흐리므로 처음 쓰는 슬라이드에서 한 번만 낸다. seen 에 읽은 배경을 더한다."""
    layout = slide.slide_layout
    texts: list[str] = []
    for part in (layout.slide_master, layout):
        name = str(part.part.partname)
        if name in seen:
            continue
        seen.add(name)
        texts.extend(_fixed_texts(part.shapes))
    return texts


class SlideAdapter(BaseAdapter):
    @property
    def format_id(self) -> str:
        return "pptx"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            native_text=True, native_table=True, native_image=True, native_structure=True,
            bbox_available=True, reading_order=True, ocr_required=False,
        )

    def can_handle(self, file_path: Path, mime_type: str) -> bool:
        return file_path.suffix.lower() == ".pptx"

    def extract(self, file_path: Path, options: dict) -> RawParsedDocument:
        try:
            from pptx import Presentation

            presentation = Presentation(str(file_path))
        except Exception as exc:  # noqa: BLE001
            return failed("pptx", f"파워포인트 파일을 열지 못했습니다: {exc}")

        collector = BlockCollector()
        warnings: list[str] = []
        width = _points(presentation.slide_width) or PAGE_WIDTH
        height = _points(presentation.slide_height) or PAGE_HEIGHT
        seen_backgrounds: set[str] = set()
        pages = [
            self._page(collector, warnings, page_number, slide, width, height, _new_background_texts(slide, seen_backgrounds))
            for page_number, slide in enumerate(presentation.slides, start=1)
        ]
        properties = presentation.core_properties
        return RawParsedDocument(
            format_id="pptx", page_count=len(pages), pages=pages,
            metadata={
                "line_layout": collector.line_layout,
                "document_title": (properties.title or "").strip() or None,
                "document_created_at": properties.created,
            },
            warnings=warnings,
        )

    @staticmethod
    def _page(collector: BlockCollector, warnings: list[str], page_number: int, slide, width: float, height: float,
              background_texts: list[str]) -> RawPage:
        from pptx.enum.shapes import MSO_SHAPE_TYPE

        blocks, tables, images = [], [], []
        shapes = _flatten(slide.shapes)
        title_shape = slide.shapes.title
        if title_shape is None or not title_shape.has_text_frame or not _shape_text(title_shape):
            title_shape = _fallback_title_shape(shapes, height)
        if title_shape is not None:
            collector.text(blocks, _shape_text(title_shape), page_number, heading_level=1)

        for shape in shapes:
            if title_shape is not None and shape.shape_id == title_shape.shape_id:
                continue
            if getattr(shape, "has_table", False) and shape.has_table:
                rows = [[_cell_text(cell).strip() for cell in row.cells] for row in shape.table.rows]
                collector.table(blocks, tables, rows, page_number)
            elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                try:
                    images.append(RawImageRegion(page_number=page_number, bbox=_bbox(shape), image_bytes=shape.image.blob))
                except Exception as exc:  # noqa: BLE001 - 연결된(파일에 없는) 그림 등
                    warnings.append(f"슬라이드 {page_number}의 그림을 읽지 못했습니다: {exc}")
            elif shape.has_text_frame:
                collector.text(blocks, _shape_text(shape), page_number)

        for text in background_texts:
            collector.text(blocks, text, page_number)

        if slide.has_notes_slide:
            notes = (slide.notes_slide.notes_text_frame.text or "").strip()
            if notes:
                collector.text(blocks, f"{NOTES_LABEL}: {notes}", page_number)

        return RawPage(
            page_number=page_number, width=width, height=height,
            text_blocks=blocks, table_candidates=tables, image_regions=images, native_text_coverage=1.0,
        )

    def extract_metadata(self, file_path: Path) -> dict:
        return {"file_path": str(file_path)}
