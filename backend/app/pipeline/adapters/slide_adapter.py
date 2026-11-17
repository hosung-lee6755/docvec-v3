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
        pages = [
            self._page(collector, warnings, page_number, slide, width, height)
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
    def _page(collector: BlockCollector, warnings: list[str], page_number: int, slide, width: float, height: float) -> RawPage:
        from pptx.enum.shapes import MSO_SHAPE_TYPE

        blocks, tables, images = [], [], []
        title_shape = slide.shapes.title
        if title_shape is not None and title_shape.has_text_frame:
            collector.text(blocks, _shape_text(title_shape), page_number, heading_level=1)

        for shape in _flatten(slide.shapes):
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
