"""TXT, 마크다운, HTML 어댑터(전체 점검 1-2).

쪽 개념이 없어 문서 전체를 한 쪽으로 둔다. 마크다운의 # 제목과 HTML의 h1~h6은 제목으로,
파이프 표와 <table>은 표로 넘긴다. 그 밖의 서식 기호는 손대지 않는다.
"""
import re
from pathlib import Path

from app.pipeline.adapters.base import (
    AdapterCapabilities,
    BaseAdapter,
    RawPage,
    RawParsedDocument,
    RawTableCandidate,
    RawTextBlock,
)
from app.pipeline.adapters.hwpx_structure import grid_from_cells
from app.pipeline.adapters.sheet_adapter import MAX_COLUMNS
from app.pipeline.adapters.simple_layout import PAGE_HEIGHT, PAGE_WIDTH, BlockCollector, failed

_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_MD_TABLE_DIVIDER_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_MD_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_FALLBACK_ENCODINGS = ("utf-8-sig", "cp949", "utf-16")
_HTML_HEADINGS = {f"h{level}": level for level in range(1, 7)}
_HTML_SKIPPED = {"script", "style", "noscript", "template", "head", "svg", "iframe", "object", "embed"}
_HTML_BLOCKS = {
    "p", "div", "section", "article", "main", "header", "footer", "nav", "aside", "li", "ul", "ol", "dl", "dt",
    "dd", "blockquote", "pre", "figure", "figcaption", "form", "address", "details", "summary", "tr", "body", "html",
}
_CAPABILITIES = AdapterCapabilities(
    native_text=True, native_table=True, native_image=False, native_structure=True,
    bbox_available=False, reading_order=True, ocr_required=False,
)


def decode_text(raw: bytes) -> str:
    """UTF-8, CP949(한글 Windows 메모장), UTF-16 순으로 읽는다. 다 안 되면 깨진 글자를 바꿔 읽는다."""
    for encoding in _FALLBACK_ENCODINGS:
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def _md_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_md_table_start(lines: list[str], index: int) -> bool:
    return "|" in lines[index] and index + 1 < len(lines) and bool(_MD_TABLE_DIVIDER_RE.match(lines[index + 1]))


def _single_page(format_id: str, blocks: list[RawTextBlock], tables: list[RawTableCandidate],
                 collector: BlockCollector, title: str | None = None) -> RawParsedDocument:
    page = RawPage(
        page_number=1, width=PAGE_WIDTH, height=PAGE_HEIGHT,
        text_blocks=blocks, table_candidates=tables, image_regions=[], native_text_coverage=1.0,
    )
    return RawParsedDocument(
        format_id=format_id, page_count=1, pages=[page],
        metadata={"line_layout": collector.line_layout, "document_title": title}, warnings=[],
    )


def parse_plain_text(text: str, is_markdown: bool) -> tuple[list[RawTextBlock], list[RawTableCandidate], BlockCollector]:
    """빈 줄로 문단을 나눈다. 마크다운이면 # 제목, 파이프 표, 코드 울타리를 알아본다."""
    collector = BlockCollector()
    blocks: list[RawTextBlock] = []
    tables: list[RawTableCandidate] = []
    paragraph: list[str] = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    def flush() -> None:
        collector.text(blocks, "\n".join(paragraph), 1)
        paragraph.clear()

    index, in_fence = 0, False
    while index < len(lines):
        line = lines[index]
        if is_markdown and _MD_FENCE_RE.match(line):
            in_fence = not in_fence
            paragraph.append(line)
        elif in_fence:
            paragraph.append(line)
        elif not line.strip():
            flush()
        elif is_markdown and (heading := _MD_HEADING_RE.match(line)):
            flush()
            collector.text(blocks, heading.group(2), 1, heading_level=len(heading.group(1)))
        elif is_markdown and _is_md_table_start(lines, index):
            flush()
            rows = [_md_row(line)]
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(_md_row(lines[index]))
                index += 1
            collector.table(blocks, tables, rows, 1)
            continue
        else:
            paragraph.append(line.rstrip())
        index += 1
    flush()
    return blocks, tables, collector


def _span_attr(cell, name: str) -> int:
    """rowspan/colspan 값. 숫자가 아니거나 1보다 작으면 1로 본다."""
    try:
        return max(1, int(str(cell.get(name, "1")).strip()))
    except ValueError:
        return 1


def _html_table_grid(table) -> tuple[list[list[str]], list[dict]]:
    """rowspan/colspan을 지켜 열이 맞는 격자를 만든다. 세로 병합은 글을 아래 줄에도 적고, 가로 병합은 첫 칸에만
    적는다(HWPX와 같은 규칙). 합친 칸의 위치와 크기는 spans로 따로 돌려준다."""
    # 표 안의 표는 바깥 칸의 글로 합쳐진다. 안쪽 표의 행을 바깥 표의 행으로 세지 않는다
    trs = [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]
    occupied: set[tuple[int, int]] = set()
    cells: list[tuple[int, int, int, int, str]] = []
    for row, tr in enumerate(trs):
        col = 0
        for cell in tr.find_all(["th", "td"], recursive=False):
            while (row, col) in occupied:
                col += 1
            if col >= MAX_COLUMNS:
                break
            row_span = min(_span_attr(cell, "rowspan"), len(trs) - row)
            col_span = min(_span_attr(cell, "colspan"), MAX_COLUMNS - col)
            occupied.update((row + dr, col + dc) for dr in range(row_span) for dc in range(col_span))
            cells.append((row, col, row_span, col_span, cell.get_text(" ", strip=True)))
            col += col_span
    return grid_from_cells(cells)


def parse_html(html: str) -> tuple[list[RawTextBlock], list[RawTableCandidate], BlockCollector, str | None]:
    from bs4 import BeautifulSoup
    from bs4.element import Comment, NavigableString

    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(strip=True) if soup.title else None
    collector = BlockCollector()
    blocks: list[RawTextBlock] = []
    tables: list[RawTableCandidate] = []
    inline: list[str] = []

    def flush() -> None:
        collector.text(blocks, re.sub(r"[ \t\r\f\v]*\n[ \t\r\f\v]*", "\n", re.sub(r"[ \t]+", " ", "".join(inline))), 1)
        inline.clear()

    def walk(node, preformatted: bool = False) -> None:
        for child in node.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                inline.append(str(child) if preformatted else re.sub(r"\s+", " ", str(child)))
                continue
            name = (child.name or "").lower()
            if name in _HTML_SKIPPED:
                continue
            if name == "table":
                flush()
                rows, spans = _html_table_grid(child)
                collector.table(blocks, tables, rows, 1, spans)
            elif name in _HTML_HEADINGS:
                flush()
                collector.text(blocks, child.get_text(" ", strip=True), 1, heading_level=_HTML_HEADINGS[name])
            elif name == "br":
                inline.append("\n")
            elif name in _HTML_BLOCKS:
                flush()
                walk(child, preformatted or name == "pre")
                flush()
            else:
                walk(child, preformatted)

    walk(soup.body or soup)
    flush()
    return blocks, tables, collector, title or None


class TextAdapter(BaseAdapter):
    """TXT와 마크다운."""

    @property
    def format_id(self) -> str:
        return "text"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return _CAPABILITIES

    def can_handle(self, file_path: Path, mime_type: str) -> bool:
        return file_path.suffix.lower() in (".txt", ".md")

    def extract(self, file_path: Path, options: dict) -> RawParsedDocument:
        is_markdown = file_path.suffix.lower() == ".md"
        format_id = "markdown" if is_markdown else "text"
        try:
            blocks, tables, collector = parse_plain_text(decode_text(file_path.read_bytes()), is_markdown)
        except Exception as exc:  # noqa: BLE001
            return failed(format_id, f"텍스트 파일을 읽지 못했습니다: {exc}")
        return _single_page(format_id, blocks, tables, collector)

    def extract_metadata(self, file_path: Path) -> dict:
        return {"file_path": str(file_path)}


class HtmlAdapter(BaseAdapter):
    @property
    def format_id(self) -> str:
        return "html"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return _CAPABILITIES

    def can_handle(self, file_path: Path, mime_type: str) -> bool:
        return file_path.suffix.lower() in (".html", ".htm")

    def extract(self, file_path: Path, options: dict) -> RawParsedDocument:
        try:
            blocks, tables, collector, title = parse_html(decode_text(file_path.read_bytes()))
        except Exception as exc:  # noqa: BLE001
            return failed("html", f"HTML 파일을 읽지 못했습니다: {exc}")
        return _single_page("html", blocks, tables, collector, title)

    def extract_metadata(self, file_path: Path) -> dict:
        return {"file_path": str(file_path)}
