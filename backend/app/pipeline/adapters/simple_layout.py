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
        spans: list[dict] | None = None, title: str | None = None,
        parent_table_id: str | None = None, parent_cell: dict | None = None,
    ) -> RawTableCandidate | None:
        """spans는 합친 칸({"row", "col", "row_span", "col_span"}, 0부터)이다. 빈 줄을 빼면 그만큼 당겨 적는다.
        title 은 표 번호 다음 줄에 적는다(칸 안에서 떼어 낸 표가 어느 칸에 있었는지, nested_tables.py)."""
        kept = [index for index, row in enumerate(rows) if any(cell for cell in row)]
        if not kept:
            return None
        cleaned = [rows[index] for index in kept]
        remapped = _remap_spans(spans or [], kept)
        self._table_ordinal += 1
        candidate = RawTableCandidate(
            page_number=page_number, rows=cleaned, spans=remapped or None, title=title,
            parent_table_id=parent_table_id, parent_cell=parent_cell,
        )
        tables.append(candidate)
        head = f"[표 {self._table_ordinal}]\n{title}" if title else f"[표 {self._table_ordinal}]"
        blocks.append(RawTextBlock(
            text=f"{head}\n{rows_to_markdown(cleaned)}",
            page_number=page_number,
            block_type="table",
        ))
        return candidate

    @property
    def table_count(self) -> int:
        """지금까지 낸 표 수. 마지막으로 낸 표의 번호 [표 N]이다."""
        return self._table_ordinal


def _remap_spans(spans: list[dict], kept: list[int]) -> list[dict]:
    new_index = {old: new for new, old in enumerate(kept)}
    adjusted: list[dict] = []
    for span in spans:
        covered = [new_index[r] for r in range(span["row"], span["row"] + span["row_span"]) if r in new_index]
        if covered and (len(covered) > 1 or span["col_span"] > 1):
            adjusted.append({**span, "row": covered[0], "row_span": len(covered)})
    return adjusted


def failed(format_id: str, message: str) -> RawParsedDocument:
    return RawParsedDocument(format_id=format_id, page_count=0, pages=[], metadata={}, warnings=[message])
