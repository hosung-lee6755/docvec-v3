"""IBM Docling 기반 PDF 어댑터 — Docling 도입 설계서(2026-07-23) Phase 1.

기존 PDFAdapter를 대체하는 게 아니라 `TextExtractConfig.engine=="docling"`일
때만 PDF에 한해 선택적으로 쓰인다(DOCX/HWP/HWPX는 Docling 미지원이라 항상
기존 어댑터). `BaseAdapter` 계약(`RawParsedDocument`/`RawPage`/`RawTextBlock`/
`RawTableCandidate`)을 그대로 따르므로 `TextExtractBlock.run()`의 parsed_text/
extraction_layout/tables 조립 로직은 수정 없이 그대로 재사용된다 — 추가로
`RawParsedDocument.metadata["elements"]`에 통합 요소 JSON(page/type/bbox/
content.markdown/metadata 형태)만 얹는다.

기본 OCR 엔진(RapidOCR)은 한글을 의미 없는 한자 형태로 오인식하는 것을
격리 트라이얼로 실제 확인했다(2026-07-23) — 반드시 EasyOCR을 한국어로 명시
설정해야 한다. Docling 정식 버전의 `ProvenanceItem`/`DocItemLabel` 속성명은
설치된 버전에 따라 달라질 수 있으므로 아래 헬퍼들은 `getattr` 기반으로
방어적으로 값을 꺼낸다 — 실제 docling 패키지가 설치된 뒤(컨테이너 리빌드
후) 실제 문서로 재검증 필요."""
import io
import re
from pathlib import Path
from uuid import uuid4

from app.pipeline.adapters.base import (
    AdapterCapabilities,
    BaseAdapter,
    RawImageRegion,
    RawPage,
    RawParsedDocument,
    RawTableCandidate,
    RawTextBlock,
)
from app.pipeline.adapters.docling_toc import TOC_LABELS, choose_toc_lines, grid_text
from app.pipeline.adapters.native_spacing import NativeRegionReader, choose_spacing
from app.pipeline.adapters.hwpx_structure import grid_from_cells
from app.pipeline.adapters.ruled_tables import RuledTable, find_ruled_tables, match_ruled_table
from app.pipeline.adapters.table_text_coverage import TextLine, lines_from_words, missing_lines, refill_cells
from app.pipeline.blocks.table_markdown import rows_to_markdown

# Docling DocItemLabel 값 -> 우리 쪽 block_type/요소 type 매핑. 매핑에 없는
# 라벨(예: caption, footnote 등 세분화된 것들)은 "paragraph"로 취급 —
# structure_analyze(Phase 2)가 이 값을 보고 세분화를 원하면 그때 추가한다.
_TABLE_LABELS = {"table"}
_HEADING_LABELS = {"title", "section_header", "section-header"}
_HEADER_LABELS = {"page_header", "page-header"}
_FOOTER_LABELS = {"page_footer", "page-footer"}
_PICTURE_LABELS = {"picture", "figure"}
_LIST_ITEM_LABELS = {"list_item", "list-item"}
_CAPTION_LABELS = {"caption"}


def _item_label(item) -> str:
    label = getattr(item, "label", None)
    if label is None:
        return "text"
    return str(getattr(label, "value", label)).lower()


def _item_page_and_bbox(item) -> tuple[int, tuple[float, float, float, float] | None]:
    prov = getattr(item, "prov", None) or []
    if not prov:
        return 1, None
    first = prov[0]
    page_no = getattr(first, "page_no", None) or getattr(first, "page", None) or 1
    bbox_obj = getattr(first, "bbox", None)
    if bbox_obj is None:
        return page_no, None
    try:
        bbox = (
            float(getattr(bbox_obj, "l", 0.0)),
            float(getattr(bbox_obj, "t", 0.0)),
            float(getattr(bbox_obj, "r", 0.0)),
            float(getattr(bbox_obj, "b", 0.0)),
        )
    except (TypeError, ValueError):
        bbox = None
    return page_no, bbox


def _table_rows(table_item) -> list[list[str]]:
    """표를 [머리글, 행, 행, ...]으로 바꾼다. Docling이 머리글 행을 알아보지 못하면 열 이름이 0, 1, 2…가
    되는데, 그때는 번호 대신 첫 행을 머리글로 쓴다(번호 머리글 표 87개, 2026-11-13 검토)."""
    try:
        df = table_item.export_to_dataframe()
    except Exception:
        return []
    body = [[str(v) for v in row] for row in df.itertuples(index=False)]
    header = [str(c) for c in df.columns]
    if header == [str(i) for i in range(len(header))]:
        return body
    return [header, *body]


def _table_grid(table_item, texts: list[str] | None = None) -> tuple[list[list[str]], list[dict] | None]:
    """표 칸 목록으로 격자를 만든다. 합친 칸의 글은 HWP·HTML 표와 같은 규칙으로 둔다.

    export_to_dataframe()은 여러 열에 걸친 칸의 글을 열마다 복사해, 실측한 문서에서 같은 글이 한 행에
    일곱 번 들어갔다(2026-11-17). 세로로 합친 칸만 행마다 글을 두고 가로로 합친 칸은 첫 열에만 둔다.
    칸 정보가 없으면 예전처럼 DataFrame으로 만든다.

    머리 행이 여러 줄이면("냉방" 아래 "건구온도", "습구온도") 열마다 한 줄로 합친다. 큰 표를 나눌 때는
    첫 행만 조각마다 되풀이하므로, 두 줄로 두면 둘째 줄 열 이름이 둘째 조각부터 사라진다.

    texts 는 칸마다 쓸 글(table_cells 와 같은 순서)이다. 원본 글자 층에서 빠진 줄을 되돌려 넣은 글을 넘긴다.
    """
    cells = getattr(getattr(table_item, "data", None), "table_cells", None)
    if not cells:
        return _table_rows(table_item), None
    texts = texts if texts is not None and len(texts) == len(cells) else [(c.text or "") for c in cells]
    pairs = list(zip(cells, texts))
    header_count = _header_row_count(cells)
    if header_count < 2:
        rows, spans = grid_from_cells([_cell_tuple(c, text=t) for c, t in pairs])
        return rows, spans or None
    body = [(c, t) for c, t in pairs if c.start_row_offset_idx >= header_count]
    context = [_cell_tuple(c, row_shift=header_count, text=t) for c, t in pairs]  # 머리글 줄은 음수 번호
    body_rows, body_spans = grid_from_cells([_cell_tuple(c, row_shift=header_count, text=t) for c, t in body], context)
    header = _merged_header([c for c in cells if c.start_row_offset_idx < header_count])
    width = max(len(header), *(len(r) for r in body_rows)) if body_rows else len(header)
    rows = [header + [""] * (width - len(header)), *(r + [""] * (width - len(r)) for r in body_rows)]
    spans = [{**s, "row": s["row"] + 1} for s in body_spans]
    return rows, spans or None


# 이보다 많은 줄을 머리 행으로 보지 않는다(본문 전체가 머리 행으로 표시된 표를 막는다)
_MAX_HEADER_ROWS = 3


def _cell_tuple(cell, row_shift: int = 0, text: str | None = None) -> tuple[int, int, int, int, str]:
    return (
        cell.start_row_offset_idx - row_shift, cell.start_col_offset_idx,
        max(cell.row_span, 1), max(cell.col_span, 1), ((cell.text if text is None else text) or "").strip(),
    )


def _cell_box(cell, page_height: float):
    """Docling 칸 좌표를 위쪽 원점으로 바꾼다. 좌표가 없으면 None."""
    bbox = getattr(cell, "bbox", None)
    if bbox is None or not page_height:
        return None
    try:
        box = bbox.to_top_left_origin(page_height=page_height)
        return (float(box.l), float(box.t), float(box.r), float(box.b))
    except (AttributeError, TypeError, ValueError):
        return None


def _refilled_cell_texts(table_item, page_height: float, lines: list[TextLine]) -> list[str] | None:
    """Docling 칸 글에 원본 글자 층에서 빠진 줄을 칸 좌표로 되돌려 넣은 칸 글 목록(table_cells 순서).
    칸 정보가 없거나 빠진 줄이 없으면 None(그대로 쓴다)."""
    cells = getattr(getattr(table_item, "data", None), "table_cells", None)
    if not cells or not lines:
        return None
    texts = [(c.text or "") for c in cells]
    dropped = missing_lines(lines, texts)
    if not dropped:
        return None
    return refill_cells([_cell_box(c, page_height) for c in cells], texts, dropped)


def _respaced_cell_texts(table_item, page_height: float, texts: list[str], read_region) -> list[str]:
    """칸마다 칸 영역의 원본 글자와 견줘 띄어쓰기가 덜 깨진 쪽을 쓴다(본문의 choose_spacing 과 같은 규칙).
    Docling 칸 글은 "Display는화면에서가장"처럼 줄이 바뀌는 자리와 낱말 사이 공백을 잃는다(UIUX 가이드라인 80쪽)."""
    cells = getattr(getattr(table_item, "data", None), "table_cells", None) or []
    respaced = list(texts)
    for index, cell in enumerate(cells):
        box = _cell_box(cell, page_height)
        if box is not None and respaced[index].strip():
            respaced[index] = choose_spacing(respaced[index], read_region(box))
    return respaced


def _ruled_table_texts(table: RuledTable) -> list[str]:
    nested = [cell for inner in table.nested for row in inner.rows for cell in row]
    return [table.title or "", *(cell for row in table.rows for cell in row), *nested]


def _docling_misses_less(table_item, ruled: RuledTable, lines: list[TextLine]) -> bool:
    """선 표보다 Docling 표가 원본 줄을 덜 빠뜨렸는가. 칸 안 표가 있는 선 표는 그대로 쓴다.

    빠진 줄을 되돌려 넣기 전 Docling 칸 글로 견준다. 넣은 뒤 글로 견주면 Docling 쪽 빠진 줄이 늘 0에 가까워,
    칸 순서를 지킨 선 표 대신 글 순서가 뒤섞인 Docling 표를 골랐다(세원화성 진단보고서 53쪽, 2026-11-23)."""
    if ruled.nested or not lines:
        return False
    cells = getattr(getattr(table_item, "data", None), "table_cells", None) or []
    docling_texts = [(c.text or "") for c in cells]
    return len(missing_lines(lines, docling_texts)) < len(missing_lines(lines, _ruled_table_texts(ruled)))


def _header_row_count(cells) -> int:
    """맨 위에서부터 칸이 모두 열 머리(column_header)인 줄 수."""
    by_row: dict[int, list] = {}
    for cell in cells:
        by_row.setdefault(cell.start_row_offset_idx, []).append(cell)
    count = 0
    while count < _MAX_HEADER_ROWS and by_row.get(count) and all(
        getattr(c, "column_header", False) for c in by_row[count]
    ):
        count += 1
    return count


def _merged_header(header_cells) -> list[str]:
    """여러 줄 머리 행을 열마다 위에서 아래 순서로 이어 붙인 한 줄로 만든다. 같은 글은 한 번만 쓴다."""
    width = max(c.start_col_offset_idx + max(c.col_span, 1) for c in header_cells)
    parts: list[list[str]] = [[] for _ in range(width)]
    for cell in sorted(header_cells, key=lambda c: (c.start_row_offset_idx, c.start_col_offset_idx)):
        text = (cell.text or "").strip()
        for col in range(cell.start_col_offset_idx, cell.start_col_offset_idx + max(cell.col_span, 1)):
            if text and text not in parts[col]:
                parts[col].append(text)
    return [" ".join(p) for p in parts]


def _top_left_bbox(item, page_height: float) -> tuple[float, float, float, float] | None:
    """Docling 좌표(아래쪽 원점일 수 있다)를 pdfplumber와 같은 위쪽 원점 좌표로 바꾼다."""
    prov = getattr(item, "prov", None) or []
    if not prov or not page_height:
        return None
    try:
        box = prov[0].bbox.to_top_left_origin(page_height=page_height)
        return (float(box.l), float(box.t), float(box.r), float(box.b))
    except (AttributeError, TypeError, ValueError):
        return None


class _RuledTableSource:
    """Docling 표 자리에 선으로 그린 표가 있으면 그것을 돌려준다. 쪽마다 한 번만 읽는다."""

    def __init__(self, file_path: Path, warnings: list[str]) -> None:
        self._path = file_path
        self._warnings = warnings
        self._pdf = None
        self._pages: dict[int, list[RuledTable]] = {}
        self._used: set[int] = set()
        self._open_failed = False

    def _tables(self, page_no: int) -> list[RuledTable]:
        if page_no in self._pages:
            return self._pages[page_no]
        self._pages[page_no] = []
        if self._open_failed:
            return []
        try:
            if self._pdf is None:
                import pdfplumber

                self._pdf = pdfplumber.open(self._path)
        except Exception as exc:  # noqa: BLE001 - 암호화나 손상 PDF. 한 번만 알리고 Docling 결과를 쓴다
            self._open_failed = True
            self._warnings.append(f"ruled table reader could not open the PDF: {exc}")
            return []
        page = None
        try:
            page = self._pdf.pages[page_no - 1]
            self._pages[page_no] = find_ruled_tables(page)
        except Exception as exc:  # noqa: BLE001 - 선 표를 못 읽으면 Docling 결과를 그대로 쓴다
            self._warnings.append(f"page {page_no} ruled table read failed: {exc}")
        finally:
            if page is not None:
                page.close()  # 쪽마다 캐시한 문자와 선을 바로 놓는다(큰 문서의 메모리)
        return self._pages[page_no]

    def lookup(self, page_no: int, bbox) -> tuple[RuledTable | None, bool]:
        """(쓸 선 표, 이미 낸 선 표와 같은 자리인가)."""
        if self._path.suffix.lower() != ".pdf":
            return None, False
        match = match_ruled_table(self._tables(page_no), bbox)
        if match is None:
            return None, False
        if id(match) in self._used:
            return None, True
        self._used.add(id(match))
        return match, False

    def close(self) -> None:
        if self._pdf is not None:
            self._pdf.close()


def _table_caption(item, doc) -> str | None:
    try:
        caption = item.caption_text(doc)
    except (AttributeError, TypeError, ValueError):
        return None
    caption = " ".join((caption or "").split())
    return caption or None


# 표 바로 위 줄이 표 제목인지 보는 머리("[별표 1]", "<표 3-1>", "[표 2]", "별표 4", "표 9")
_CAPTION_LINE_RE = re.compile(
    r"^(?:\[\s*별\s*표\s*[\d\-]+\s*\]|<\s*표\s*[\d\-.]+\s*>|\[\s*표\s*[\d\-.]+\s*\]|별\s*표\s*[\d\-]+|표\s*[\d\-.]+)\s*\S"
)
_CAPTION_MAX_CHARS = 80


def _preceding_caption(page: RawPage) -> str | None:
    """캡션이 없는 표의 제목으로 쓸, 같은 쪽에서 바로 앞에 나온 제목 줄. 기계설비 매뉴얼에서 제목 없는 표 169개 중
    50개가 "[별표 1] 표 2 냉·난방설비의 …" 같은 줄을 바로 위에 두었다(2026-11-19)."""
    if not page.text_blocks or page.text_blocks[-1].block_type == "table":
        return None
    line = " ".join(page.text_blocks[-1].text.split())
    if len(line) > _CAPTION_MAX_CHARS or not _CAPTION_LINE_RE.match(line):
        return None
    return line


def _emit_table(page: RawPage, elements: list[dict], section_path: list[str], rows: list[list[str]],
                spans: list[dict] | None, bbox, detected_as: str, title: str | None = None,
                parent_table_id: str | None = None, parent_cell: dict | None = None) -> str:
    """표 하나를 표 후보, 본문 블록, 요소로 남기고 표 id 를 돌려준다. 제목이 있으면 표 글 맨 위에 한 줄로 둔다.
    칸 안에서 떼어 낸 표는 바깥 표 id 와 들어 있던 칸을 함께 남긴다(nested_tables.py)."""
    table_id = str(uuid4())
    page.table_candidates.append(RawTableCandidate(
        page_number=page.page_number, rows=rows, bbox=bbox, id=table_id, spans=spans, title=title,
        parent_table_id=parent_table_id, parent_cell=parent_cell,
    ))
    markdown = rows_to_markdown(rows)
    if title:
        markdown = f"{title}\n{markdown}"
    # 표도 다른 요소처럼 text_blocks에 한 항목을 남겨야 element_spans가 맞는다(Phase 1 검증 중 발견).
    page.text_blocks.append(
        RawTextBlock(text=markdown, page_number=page.page_number, bbox=bbox, block_type="table", element_id=table_id)
    )
    elements.append({
        "id": table_id, "page": page.page_number, "type": "table", "bbox": bbox,
        "content": {"text": markdown, "markdown": markdown},
        "metadata": {
            "section_path": list(section_path), "is_header": False,
            "is_footer": False, "confidence": 1.0, "detected_as": detected_as,
            "order": len(elements), "is_caption": False,
            "table_rows": len(rows), "table_cols": len(rows[0]) if rows else 0,
            "style": None,
        },
    })
    return table_id


def _page_native_text(page: RawPage) -> str:
    return "\n".join(block.text for block in page.text_blocks)


def _page_image_area_ratio(page: RawPage) -> float:
    page_area = page.width * page.height
    if page_area <= 0:
        return 0.0
    image_area = sum(
        max(0.0, region.bbox[2] - region.bbox[0]) * max(0.0, region.bbox[3] - region.bbox[1])
        for region in page.image_regions
        if region.bbox
    )
    return min(1.0, image_area / page_area)


def _pdf_properties(file_path: Path) -> tuple[int, str | None]:
    """원본 PDF 의 (실제 쪽수, 제목 속성). Docling 은 요소가 있는 쪽만 RawPage 로 만들어 빈 쪽·그림 쪽이
    빠지므로 쪽수는 파일에서 직접 센다. 못 읽으면 (0, None)."""
    try:
        import fitz  # pymupdf

        with fitz.open(str(file_path)) as pdf:
            return pdf.page_count, ((pdf.metadata or {}).get("title") or "").strip() or None
    except Exception:
        return 0, None


def _native_text_in_bbox(fitz_doc, page_no: int, bbox: tuple[float, float, float, float]) -> str:
    """원본 PDF 텍스트 레이어에서 bbox 안의 글자를 읽는다(없으면 "").

    Docling 은 그림(차트)으로 분류한 영역 안의 글자를 본문에서 빼 버리고, 그림 인식은 그 영역을
    이미지로 렌더링해 OCR 한다 — 원본에 정확한 라벨·수치가 있어도 깨진 OCR 조각이 남는다.
    bbox 는 Docling 의 PDF 좌표(왼쪽 아래 원점, top > bottom)나 왼쪽 위 원점(top < bottom) 모두 받는다."""
    if page_no < 1 or page_no > len(fitz_doc):
        return ""
    import fitz

    page = fitz_doc[page_no - 1]
    left, first_y, right, second_y = bbox
    if first_y > second_y:  # 왼쪽 아래 원점 → 왼쪽 위 원점으로 변환
        top, bottom = page.rect.height - first_y, page.rect.height - second_y
    else:
        top, bottom = first_y, second_y
    return page.get_text("text", clip=fitz.Rect(left, top, right, bottom)).strip()


_TOC_RIGHT_OVERFLOW = 3.0
_TOC_LEFT_MARGIN = 4.0
# 같은 줄로 볼 낱말 세로 중심의 최대 차이(pt)
_SAME_LINE_TOLERANCE = 3.0


def _visual_lines(words: list[tuple]) -> str:
    """PyMuPDF 낱말 목록을 화면에 보이는 줄로 다시 묶는다.

    목차의 쪽 번호가 항목과 다른 글 블록에 들어 있는 PDF 가 있어(기계설비 매뉴얼 3쪽), 블록 순서대로 읽으면
    항목들이 먼저 나오고 쪽 번호가 맨 뒤에 몰린다. 세로 위치가 같은 낱말을 한 줄로 모아 왼쪽부터 잇는다."""
    lines: list[list[tuple]] = []
    for word in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        center = (word[1] + word[3]) / 2
        if lines and abs(center - (lines[-1][0][1] + lines[-1][0][3]) / 2) <= _SAME_LINE_TOLERANCE:
            lines[-1].append(word)
        else:
            lines.append([word])
    return "\n".join(" ".join(w[4] for w in sorted(line, key=lambda w: w[0])) for line in lines)


class _NativeTextReader:
    """원본 PDF 텍스트 레이어를 쪽·영역 단위로 읽는다. 처음 쓸 때 한 번만 열고, 열지 못하면 ""만 돌려준다."""

    def __init__(self, file_path: Path, warnings: list[str]) -> None:
        self._path = file_path
        self._warnings = warnings
        self._doc = None
        self._failed = False

    def read_full_width(self, page_no: int, bbox: tuple[float, float, float, float] | None) -> str:
        """bbox 의 위아래 범위를 쪽 너비 전체로 넓혀 읽는다. Docling 의 목차 영역은 오른쪽 끝 쪽 번호 열을
        자주 빠뜨린다(기계설비 매뉴얼 3쪽에서 항목 30개 중 20여 개의 쪽 번호가 잘렸다, 2026-11-20)."""
        if bbox is None or self._failed:
            return ""
        try:
            if self._doc is None:
                import fitz  # pymupdf

                self._doc = fitz.open(str(self._path))
            if page_no < 1 or page_no > len(self._doc):
                return ""
            # 점선이 길면 쪽 번호가 쪽 오른쪽 끝 밖에 찍힌 PDF 도 있어(같은 매뉴얼) 오른쪽은 넉넉히 연다
            page = self._doc[page_no - 1]
            first_y, second_y = bbox[1], bbox[3]
            if first_y > second_y:  # 왼쪽 아래 원점 → 왼쪽 위 원점
                first_y, second_y = page.rect.height - first_y, page.rect.height - second_y
            import fitz  # pymupdf

            # 왼쪽은 목차 영역에서 시작한다(옆 단·사이드바 글이 섞이지 않게). 오른쪽만 쪽 번호 열까지 넓힌다
            left = max(0.0, min(bbox[0], bbox[2]) - _TOC_LEFT_MARGIN)
            clip = fitz.Rect(left, first_y, page.rect.width * _TOC_RIGHT_OVERFLOW, second_y)
            return _visual_lines(page.get_text("words", clip=clip))
        except Exception as exc:  # 보강일 뿐이다. 실패하면 Docling 표 칸 글로 대신한다
            self._failed = True
            self._warnings.append(f"목차 영역 원본 텍스트 읽기 실패: {exc}")
            return ""

    def lines_in(self, page_no: int, bbox: tuple[float, float, float, float] | None) -> list[TextLine]:
        """위쪽 원점 bbox 안의 원본 글자 줄. 글자 층이 없거나(스캔) 읽지 못하면 빈 목록이다."""
        if bbox is None or self._failed:
            return []
        try:
            if self._doc is None:
                import fitz  # pymupdf

                self._doc = fitz.open(str(self._path))
            if page_no < 1 or page_no > len(self._doc):
                return []
            import fitz  # pymupdf

            return lines_from_words(self._doc[page_no - 1].get_text("words", clip=fitz.Rect(*bbox)))
        except Exception as exc:  # 보강일 뿐이다. 실패하면 표 결과를 그대로 쓴다
            self._failed = True
            self._warnings.append(f"표 영역 원본 텍스트 읽기 실패: {exc}")
            return []

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()


def _emit_text(page: RawPage, elements: list[dict], section_path: list[str], label: str, text: str,
               bbox, level=None) -> None:
    """글 요소 하나를 요소 목록과 쪽 글 블록에 더한다."""
    is_header = label in _HEADER_LABELS
    is_footer = label in _FOOTER_LABELS
    block_type = "header" if is_header else "footer" if is_footer else "paragraph"
    element_id = str(uuid4())
    if text:
        page.text_blocks.append(
            RawTextBlock(
                text=text, page_number=page.page_number, bbox=bbox, block_type=block_type,
                element_id=element_id,
            )
        )
    metadata = {
        "section_path": list(section_path), "is_header": is_header, "is_footer": is_footer,
        # 메타 정보 생성 설계서(2026-07-23) Phase 3 — order는 순회 인덱스(읽기 순서),
        # style/font_size/font_name은 Docling이 제공하지 않아 항상 None(자동 생성 불가, 스키마에는 노출).
        "order": len(elements), "is_caption": label in _CAPTION_LABELS, "style": None,
    }
    if label in _HEADING_LABELS:
        # DocumentNode.level 계층 구성에 필요(Phase 2) — Docling의 SectionHeaderItem.level이 곧 heading depth.
        metadata["level"] = level
    elements.append({
        "id": element_id, "page": page.page_number, "type": label, "bbox": bbox,
        "content": {"text": text, "markdown": text},
        "metadata": metadata,
    })


def _attach_native_text_to_pictures(file_path: Path, pages_by_no: dict[int, RawPage],
                                    warnings: list[str]) -> None:
    """그림 영역마다 원본 텍스트 레이어의 글자를 `native_text`로 붙인다(그림 인식이 OCR 보다 우선 사용)."""
    regions = [(no, r) for no, page in pages_by_no.items() for r in page.image_regions if any(r.bbox)]
    if not regions:
        return
    try:
        import fitz  # pymupdf

        with fitz.open(str(file_path)) as fitz_doc:
            for page_no, region in regions:
                text = _native_text_in_bbox(fitz_doc, page_no, region.bbox)
                if text:
                    region.native_text = text
    except Exception as exc:  # 보강일 뿐이므로 실패해도 기존 OCR 경로로 계속한다
        warnings.append(f"그림 영역 원본 텍스트 읽기 실패: {exc}")


def _escalate_low_coverage_pages(
    file_path: Path,
    pages_by_no: dict[int, RawPage],
    elements: list[dict],
    vision_backend: str,
    vision_api_key: str,
    warnings: list[str],
) -> bool:
    """pdf_adapter.py의 클라우드 VLM OCR 폴백(BYOK 키 등록 시에만 동작, 등록 안
    되어 있으면 이 함수 자체가 호출되지 않음)과 동일한 임계값으로 Docling
    경로도 페이지별 저-커버리지를 escalate한다 — Docling 기본 OCR(EasyOCR)이
    인포그래픽처럼 텍스트/그래픽이 뒤섞인 페이지에서 요소를 거의 못 뽑아내는
    경우가 실제로 있다(서울시 도시 범죄 취약지 분석 PDF로 실증). Docling
    자체 VLM 파이프라인(granite-docling-258M)은 별도로 이 문서에 직접 검증한
    결과 한국어 텍스트 페이지에서 반복 루프/환각으로 못 쓴다고 판단해
    기각했다(Docling VLM 통합 조사, 2026-07-29) — 대신 이미 검증된
    pdf_adapter.py의 상용 vision LLM(OpenAI/Anthropic) 경로를 재사용한다.
    저-커버리지 페이지라도 Docling이 이미 뽑아낸 요소는 그대로 두고 VLM
    텍스트를 별도 블록으로 보강만 한다 — 페이지 전체를 대체하면 Docling이
    맞게 인식한 일부 구조(예: 표)까지 지워질 수 있다."""
    from app.pipeline.adapters.pdf_adapter import PDFAdapter, _cloud_vlm_ocr, _text_coverage

    escalated = False
    fitz_doc = None
    try:
        for page_no, page in pages_by_no.items():
            native_text = _page_native_text(page)
            trusted_native_text = len(native_text.strip()) >= PDFAdapter._MIN_TRUSTED_NATIVE_CHARS
            coverage = _text_coverage(native_text, page.width, page.height)
            image_ratio = _page_image_area_ratio(page)
            needs_escalation = image_ratio > PDFAdapter._OCR_IMAGE_AREA_THRESHOLD or (
                coverage < PDFAdapter._OCR_COVERAGE_THRESHOLD and not trusted_native_text
            )
            if not needs_escalation:
                continue
            if fitz_doc is None:
                import fitz  # pymupdf

                fitz_doc = fitz.open(str(file_path))
            try:
                pixmap = fitz_doc[page_no - 1].get_pixmap(dpi=300)
                page_image_bytes = pixmap.tobytes("png")
            except Exception as render_exc:
                warnings.append(f"page {page_no} vlm render failed: {render_exc}")
                continue
            vlm_text = _cloud_vlm_ocr(page_image_bytes, vision_backend, vision_api_key)
            if not vlm_text or not vlm_text.strip():
                continue
            element_id = str(uuid4())
            page.text_blocks.append(
                RawTextBlock(
                    text=vlm_text, page_number=page_no, bbox=None,
                    block_type="vlm_ocr", element_id=element_id,
                )
            )
            elements.append({
                "id": element_id, "page": page_no, "type": "vlm_ocr", "bbox": None,
                "content": {"text": vlm_text, "markdown": vlm_text},
                "metadata": {
                    "section_path": [], "is_header": False, "is_footer": False,
                    "confidence": None, "detected_as": "cloud_vlm_ocr",
                    "order": len(elements), "is_caption": False, "style": None,
                },
            })
            escalated = True
    finally:
        if fitz_doc is not None:
            fitz_doc.close()
    return escalated


_converter = None


def _get_converter():
    """프로세스마다 변환기를 한 번만 만든다. 문서마다 새로 만들면 레이아웃·표·OCR 모델을 매번 다시
    올린다(8쪽 문서 첫 변환 18초, 재사용 11초 실측, 2026-11-13). 텍스트 추출은 프로세스 하나인
    worker-extract에서만 돌아 모델이 한 벌만 남는다."""
    global _converter
    if _converter is None:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import EasyOcrOptions, PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = True
        # 기본 RapidOCR(중국어 모델)이 한글을 한자로 오인식하는 것을 실제
        # 확인함 — 반드시 EasyOCR + 한국어로 명시 설정.
        pipeline_options.ocr_options = EasyOcrOptions(lang=["ko"])
        # generate_picture_images 기본값은 False라 PictureItem.get_image()가
        # 항상 None을 반환했다 — 아래 picture 분기에서 실제 PNG bytes를 얻으려면
        # 반드시 켜야 한다(그림 탭 표출 버그, 2026-07-25).
        pipeline_options.generate_picture_images = True
        _converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
        )
    return _converter


class DoclingAdapter(BaseAdapter):
    @property
    def format_id(self) -> str:
        return "pdf"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            native_text=True,
            native_table=True,
            native_image=True,
            native_structure=True,
            bbox_available=True,
            reading_order=True,
            ocr_required=False,
        )

    def can_handle(self, file_path: Path, mime_type: str) -> bool:
        return mime_type == "application/pdf" or file_path.suffix.lower() == ".pdf"

    def extract(self, file_path: Path, options: dict) -> RawParsedDocument:
        result = _get_converter().convert(str(file_path))
        doc = result.document

        pages_by_no: dict[int, RawPage] = {}
        elements: list[dict] = []
        section_path: list[str] = []
        warnings: list[str] = []
        table_ordinal = 0
        ruled_source = _RuledTableSource(file_path, warnings)
        native_text = _NativeTextReader(file_path, warnings)
        # 본문 글의 띄어쓰기를 원본 글자 층과 견준다(Docling 이 "텅레 일의", "V oluntary"처럼 낱말을 떼던 문제, 2026-11-20)
        native_region = NativeRegionReader(file_path, warnings)

        def page_for(page_no: int) -> RawPage:
            if page_no not in pages_by_no:
                size = getattr(doc.pages.get(page_no), "size", None) if hasattr(doc, "pages") else None
                width = float(getattr(size, "width", 0.0) or 0.0)
                height = float(getattr(size, "height", 0.0) or 0.0)
                pages_by_no[page_no] = RawPage(
                    page_number=page_no, width=width, height=height,
                    text_blocks=[], table_candidates=[], image_regions=[],
                )
            return pages_by_no[page_no]

        for item, _level in doc.iterate_items():
            label = _item_label(item)
            page_no, bbox = _item_page_and_bbox(item)
            page = page_for(page_no)

            if label in _TABLE_LABELS:
                table_box = _top_left_bbox(item, page.height)
                ruled, is_covered = ruled_source.lookup(page_no, table_box)
                if is_covered:
                    continue  # 앞의 Docling 표와 같은 선 표다. 이미 그 결과로 냈다
                # 표 영역의 원본 글자 줄과 견줘 빠진 줄을 칸에 되돌려 넣고, 선 표가 Docling 표보다 많이 빠뜨렸으면
                # Docling 표를 쓴다(UIUX 가이드라인 80쪽 "Usage" 열, 자율형공장 공고 17쪽 칸 안 넷째 줄, 2026-11-23)
                source_lines = native_text.lines_in(page_no, table_box)
                cell_texts = _refilled_cell_texts(item, page.height, source_lines)
                if ruled is not None and _docling_misses_less(item, ruled, source_lines):
                    ruled = None
                if ruled is not None:
                    # 선으로 그린 표는 선 그대로 읽은 결과를 쓴다. 칸 안의 작은 표는 바로 뒤에 따로 낸다
                    caption = _table_caption(item, doc) or _preceding_caption(page)
                    outer_id = _emit_table(
                        page, elements, section_path, ruled.rows, list(ruled.spans) or None, bbox, "ruled_lines",
                        ruled.title or caption,
                    )
                    for t in ruled.nested:
                        _emit_table(
                            page, elements, section_path, t.rows, list(t.spans) or None, bbox, "ruled_lines",
                            t.title, parent_table_id=outer_id, parent_cell=t.host,
                        )
                    table_ordinal += 1 + len(ruled.nested)
                else:
                    docling_cells = getattr(getattr(item, "data", None), "table_cells", None) or []
                    if docling_cells and source_lines:
                        cell_texts = _respaced_cell_texts(
                            item, page.height, cell_texts or [(c.text or "") for c in docling_cells],
                            lambda box, page_no=page_no: native_region.read(page_no, box),
                        )
                    rows, spans = _table_grid(item, cell_texts)
                    if not any((cell or "").strip() for row in rows for cell in row):
                        # 칸을 하나도 읽지 못한 표는 빈 "[표 N]" 만 남긴다(윤곽선 글자 쪽, 만도 보고서 2026-11-25)
                        continue
                    table_ordinal += 1
                    _emit_table(
                        page, elements, section_path, rows, spans, bbox, "docling_table",
                        _table_caption(item, doc) or _preceding_caption(page),
                    )
                continue

            if label in _PICTURE_LABELS:
                # _recognize_document_images(process.py)가 image_bytes로
                # 실제 그림을 인식/저장한다 — bytes가 없으면(구버전 코드) 항상
                # 스킵되어 요소/구조 탭엔 그림이 보이는데 그림 탭은 늘 비어 있다.
                # RGBA/팔레트 모드는 그대로
                # PNG로 저장하고, 흰 배경 합성 등 모드 변환은 기존
                # _recognize_document_images가 이미 처리한다.
                image_bytes = None
                try:
                    pil_image = item.get_image(doc)
                    if pil_image is not None:
                        buf = io.BytesIO()
                        pil_image.save(buf, format="PNG")
                        image_bytes = buf.getvalue()
                except Exception:
                    image_bytes = None
                picture_id = str(uuid4())
                page.image_regions.append(
                    RawImageRegion(page_number=page_no, bbox=bbox or (0, 0, 0, 0), image_bytes=image_bytes,
                                   element_id=picture_id)
                )
                elements.append({
                    "id": picture_id, "page": page_no, "type": "picture", "bbox": bbox,
                    "content": {"text": "", "markdown": ""},
                    "metadata": {
                        "section_path": list(section_path), "is_header": False, "is_footer": False,
                        # 메타 정보 생성 설계서(2026-07-23) Phase 3 — image_path는
                        # Document.images가 이 시점(어댑터 extract() 실행 중)에는
                        # 아직 계산되지 않았으므로 여기서 채울 수 없다. 이미지
                        # 인식이 끝난 뒤 extraction_blocks.py::TextExtractBlock이
                        # 페이지 번호로 매치해 채운다.
                        "order": len(elements), "is_caption": False, "style": None,
                        "image_path": None,
                    },
                })
                continue

            if label in TOC_LABELS:
                # 목차는 글이 표 칸에 담겨 text 가 비어 있다. 원본 글(없으면 표 칸)을 목차 줄 하나씩 낸다
                lines = choose_toc_lines(native_text.read_full_width(page_no, bbox), grid_text(_table_grid(item)[0]))
                for line in lines:
                    _emit_text(page, elements, section_path, label, line, bbox)
                continue

            text = (getattr(item, "text", "") or "").strip()
            if text:
                text = choose_spacing(text, native_region.read(page_no, bbox))
            if label in _HEADING_LABELS:
                section_path = [text] if text else section_path
            _emit_text(page, elements, section_path, label, text, bbox, level=getattr(item, "level", None))

        # pdf_adapter.py의 클라우드 VLM OCR 폴백과 동일하게, 등록된 BYOK 키가
        # 있을 때만 저-커버리지 페이지를 escalate한다(_resolve_vision_credentials,
        # process.py) — 키가 없으면 vision_backend/vision_api_key가 빈 값이라
        # 이 블록 자체가 스킵되고 기존 EasyOCR-only 동작과 동일하다.
        ruled_source.close()
        native_text.close()
        native_region.close()
        _attach_native_text_to_pictures(file_path, pages_by_no, warnings)

        vision_backend = options.get("vision_backend")
        vision_api_key = options.get("vision_api_key")
        vlm_escalated = False
        if vision_backend and vision_api_key:
            vlm_escalated = _escalate_low_coverage_pages(
                file_path, pages_by_no, elements, vision_backend, vision_api_key, warnings,
            )

        line_layout = [
            {
                "page_number": el["page"], "text": el["content"]["text"],
                "bbox": el["bbox"], "font_size": None, "is_bold": el["type"] in _HEADING_LABELS,
                "is_italic": False, "style_name": el["type"],
            }
            for el in elements
            if el["type"] not in _TABLE_LABELS and el["type"] not in _PICTURE_LABELS
        ]

        pages = [pages_by_no[no] for no in sorted(pages_by_no)]
        source_page_count, document_title = _pdf_properties(file_path)
        ocr_used = vlm_escalated or any(
            getattr(item, "confidence", None) is not None for item, _ in doc.iterate_items()
        )

        return RawParsedDocument(
            format_id="pdf",
            page_count=max(len(pages), source_page_count),
            pages=pages,
            metadata={
                "ocr_used": ocr_used, "line_layout": line_layout, "elements": elements,
                "document_title": document_title,
            },
            warnings=warnings,
        )

    def extract_metadata(self, file_path: Path) -> dict:
        return {}
