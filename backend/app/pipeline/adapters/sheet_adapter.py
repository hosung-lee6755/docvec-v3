"""XLSX 어댑터(전체 점검 1-2).

시트 하나를 한 쪽으로 본다. 시트 이름은 제목이 되고, 빈 행으로 떨어진 구역은 각각 표가 된다.
수식은 엑셀이 마지막으로 계산해 저장한 값을 읽는다.
"""
from datetime import date, datetime, time
from pathlib import Path

from app.pipeline.adapters.base import AdapterCapabilities, BaseAdapter, RawPage, RawParsedDocument
from app.pipeline.adapters.simple_layout import PAGE_HEIGHT, PAGE_WIDTH, BlockCollector, failed

# 시트 하나에서 읽는 행 수의 상한. 넘는 부분은 읽지 않고 경고로 남긴다
MAX_ROWS_PER_SHEET = 5000
MAX_COLUMNS = 100
# 칸이 한 개뿐인 구역은 표가 아니라 글(메모, 표 제목)로 넘긴다
_MIN_TABLE_CELLS = 2


def cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.10g}"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d") if value.time() == time(0, 0) else value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, (date, time)):
        return value.isoformat()
    return str(value).strip()


def _trim(row: list[str]) -> list[str]:
    end = len(row)
    while end and not row[end - 1]:
        end -= 1
    return row[:end]


def _regions(rows: list[list[str]]) -> list[list[list[str]]]:
    """빈 행으로 나뉜 구역들. 구역 안의 행은 가장 긴 행에 맞춰 빈 칸으로 채운다."""
    regions, current = [], []
    for row in rows + [[]]:
        if row:
            current.append(row)
            continue
        if current:
            width = max(len(r) for r in current)
            regions.append([r + [""] * (width - len(r)) for r in current])
            current = []
    return regions


class SheetAdapter(BaseAdapter):
    @property
    def format_id(self) -> str:
        return "xlsx"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            native_text=True, native_table=True, native_image=False, native_structure=True,
            bbox_available=False, reading_order=True, ocr_required=False,
        )

    def can_handle(self, file_path: Path, mime_type: str) -> bool:
        return file_path.suffix.lower() == ".xlsx"

    def extract(self, file_path: Path, options: dict) -> RawParsedDocument:
        try:
            from openpyxl import load_workbook

            workbook = load_workbook(str(file_path), read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001
            return failed("xlsx", f"엑셀 파일을 열지 못했습니다: {exc}")

        collector = BlockCollector()
        pages: list[RawPage] = []
        warnings: list[str] = []
        try:
            for page_number, sheet in enumerate(workbook.worksheets, start=1):
                rows, truncated = self._read_rows(sheet)
                if truncated:
                    warnings.append(f"시트 '{sheet.title}'은 {MAX_ROWS_PER_SHEET}행까지만 읽었습니다.")
                pages.append(self._page(collector, page_number, sheet.title, rows))
            title = (workbook.properties.title or "").strip() or None
            created = workbook.properties.created
        finally:
            workbook.close()

        return RawParsedDocument(
            format_id="xlsx", page_count=len(pages), pages=pages,
            metadata={"line_layout": collector.line_layout, "document_title": title, "document_created_at": created},
            warnings=warnings,
        )

    @staticmethod
    def _read_rows(sheet) -> tuple[list[list[str]], bool]:
        rows: list[list[str]] = []
        for index, values in enumerate(sheet.iter_rows(values_only=True, max_col=MAX_COLUMNS)):
            if index >= MAX_ROWS_PER_SHEET:
                return rows, True
            rows.append(_trim([cell_text(v) for v in values]))
        return rows, False

    @staticmethod
    def _page(collector: BlockCollector, page_number: int, title: str, rows: list[list[str]]) -> RawPage:
        blocks, tables = [], []
        collector.text(blocks, title, page_number, heading_level=1)
        for region in _regions(rows):
            filled = sum(1 for row in region for cell in row if cell)
            if filled < _MIN_TABLE_CELLS:
                collector.text(blocks, " ".join(cell for row in region for cell in row if cell), page_number)
            else:
                collector.table(blocks, tables, region, page_number)
        return RawPage(
            page_number=page_number, width=PAGE_WIDTH, height=PAGE_HEIGHT,
            text_blocks=blocks, table_candidates=tables, image_regions=[], native_text_coverage=1.0,
        )

    def extract_metadata(self, file_path: Path) -> dict:
        return {"file_path": str(file_path)}
