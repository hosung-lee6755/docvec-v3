"""글꼴 정보가 없는 형식(TXT, MD, HTML, XLSX, PPTX)의 어댑터가 함께 쓰는 조각.

구조 분석은 줄의 글자 크기와 굵기로 제목을 고른다(structure_blocks.py). 이 형식들은 글꼴 대신
"제목이다"라는 표시(마크다운 #, HTML h1, 시트 이름, 슬라이드 제목)를 가지므로, 그 표시를
본문보다 큰 굵은 글자로 옮겨 적어 같은 판정을 타게 한다.
"""
from app.pipeline.adapters.base import RawParsedDocument, RawTableCandidate, RawTextBlock
from app.pipeline.blocks.table_markdown import rows_to_markdown

BODY_FONT_SIZE = 11.0
_HEADING_BASE_SIZE = 24.0
_HEADING_STEP = 2.0
MAX_HEADING_LEVEL = 6
# 쪽 크기를 모르는 형식에 쓰는 A4(pt)
PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0


def heading_font_size(level: int) -> float:
    level = max(1, min(level, MAX_HEADING_LEVEL))
    return _HEADING_BASE_SIZE - _HEADING_STEP * (level - 1)


def layout_entry(text: str, page_number: int, heading_level: int | None = None) -> dict:
    is_heading = heading_level is not None
    return {
        "page_number": page_number,
        "text": text,
        "bbox": None,
        "font_size": heading_font_size(heading_level) if is_heading else BODY_FONT_SIZE,
        "is_bold": is_heading,
        "is_italic": False,
        "style_name": f"Heading {heading_level}" if is_heading else None,
        "font_name": None,
    }


class BlockCollector:
    """한 문서의 글 조각, 표, 줄 정보를 순서대로 모은다. 표 번호는 문서 전체에서 이어진다."""

    def __init__(self) -> None:
        self.line_layout: list[dict] = []
        self._table_ordinal = 0

    def text(self, blocks: list[RawTextBlock], text: str, page_number: int, heading_level: int | None = None) -> None:
        stripped = text.strip()
        if not stripped:
            return
        blocks.append(RawTextBlock(text=stripped, page_number=page_number))
        self.line_layout.append(layout_entry(stripped, page_number, heading_level))

    def table(
        self, blocks: list[RawTextBlock], tables: list[RawTableCandidate], rows: list[list[str]], page_number: int,
    ) -> None:
        cleaned = [row for row in rows if any(cell for cell in row)]
        if not cleaned:
            return
        self._table_ordinal += 1
        tables.append(RawTableCandidate(page_number=page_number, rows=cleaned))
        blocks.append(RawTextBlock(
            text=f"[표 {self._table_ordinal}]\n{rows_to_markdown(cleaned)}",
            page_number=page_number,
            block_type="table",
        ))


def failed(format_id: str, message: str) -> RawParsedDocument:
    return RawParsedDocument(format_id=format_id, page_count=0, pages=[], metadata={}, warnings=[message])
