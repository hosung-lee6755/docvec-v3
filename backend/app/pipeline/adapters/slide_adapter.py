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


def _shape_text(shape) -> str:
    return "\n".join(
        text for paragraph in shape.text_frame.paragraphs
        if (text := "".join(run.text for run in paragraph.runs).strip())
    )


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
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
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
                rows = [[cell.text.strip() for cell in row.cells] for row in shape.table.rows]
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
