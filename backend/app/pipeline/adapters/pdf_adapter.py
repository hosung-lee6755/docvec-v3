import re
from datetime import datetime
from pathlib import Path

from app.pipeline.blocks.table_markdown import rows_to_markdown

from app.pipeline.adapters.base import (
    BaseAdapter,
    AdapterCapabilities,
    RawImageRegion,
    RawParsedDocument,
    RawPage,
    RawTableCandidate,
    RawTextBlock,
)

_POINTS_PER_CM = 72 / 2.54
# Reference density for a "fully covered" text page, per engine_design.md
# §13.5's text_density < 5.0 chars/cm² OCR-candidate threshold. Used to derive
# a 0-1 native_text_coverage ratio from raw character density.
_FULL_PAGE_TEXT_DENSITY = 5.0


def _parse_pdf_date(raw: str | None) -> datetime | None:
    """PDF info dict creationDate, e.g. "D:20230415120000+00'00'" (PDF spec
    §7.9.4). Only the date/time digits are required; timezone suffix is
    ignored since Document.document_created_at only needs an authored-date
    signal, not exact instant. Returns None for missing/malformed values."""
    if not raw:
        return None
    match = re.match(r"D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?", raw)
    if not match:
        return None
    year, month, day, hour, minute, second = (
        int(g) if g else 0 for g in match.groups()
    )
    try:
        return datetime(year, month or 1, day or 1, hour, minute, second)
    except ValueError:
        return None


def _text_coverage(text: str, width: float, height: float) -> float:
    area_cm2 = (width / _POINTS_PER_CM) * (height / _POINTS_PER_CM)
    if area_cm2 <= 0:
        return 0.0
    density = len(text.strip()) / area_cm2
    return min(1.0, density / _FULL_PAGE_TEXT_DENSITY)


def _table_area(bbox) -> float:
    x0, top, x1, bottom = bbox
    return max(0.0, x1 - x0) * max(0.0, bottom - top)


def _table_iou(a, b) -> float:
    ax0, atop, ax1, abottom = a
    bx0, btop, bx1, bbottom = b
    ix0, iy0 = max(ax0, bx0), max(atop, btop)
    ix1, iy1 = min(ax1, bx1), min(abottom, bbottom)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    union = _table_area(a) + _table_area(b) - inter
    return inter / union if union > 0 else 0.0


_TABLE_FULL_PAGE_AREA_RATIO = 0.9


def _dedupe_tables(tables: list, page_area: float) -> list:
    """pdfplumber's find_tables() can report the same visual table multiple
    times when internal grid lines also satisfy its line-intersection heuristic
    as a nested sub-table, and can also mistake a page border/rule for a
    table spanning almost the entire page. Drop near-full-page false
    positives, then keep only the largest table in each remaining
    overlapping cluster (bbox IoU > 0.5)."""
    real_tables = [
        t for t in tables
        if page_area <= 0 or _table_area(t.bbox) / page_area < _TABLE_FULL_PAGE_AREA_RATIO
    ]
    kept: list = []
    for table in sorted(real_tables, key=lambda t: _table_area(t.bbox), reverse=True):
        if any(_table_iou(table.bbox, k.bbox) > 0.5 for k in kept):
            continue
        kept.append(table)
    return kept


# BYOK cloud VLM OCR: only used when the caller (process.py::parse_document)
# resolves a registered project/user OpenAI or Anthropic key and passes it
# through `options` — otherwise this is skipped entirely and behavior is
# unchanged (Tesseract only). Model choice is fixed per backend regardless of
# any chat model_key, since this runs at parse time, not in a conversation.
_VISION_MODEL_BY_BACKEND = {"openai": "gpt-4o-mini", "anthropic": "claude-3-5-sonnet"}
_VISION_OCR_PROMPT = (
    "이 이미지는 스캔된 문서 페이지입니다. 이미지 안의 모든 텍스트를 정확히 그대로 옮겨 적으세요. "
    "표가 있다면 행과 열 구분이 드러나도록 옮기세요. 설명이나 요약을 추가하지 말고 텍스트만 출력하세요."
)


def _cloud_vlm_ocr(image_bytes: bytes, vision_backend: str, vision_api_key: str) -> str | None:
    model_key = _VISION_MODEL_BY_BACKEND.get(vision_backend)
    if not model_key:
        return None
    try:
        from app.services.llm import get_llm_provider

        provider = get_llm_provider(model_key, api_key=vision_api_key)
        return provider.generate_vision("", image_bytes, "image/png", _VISION_OCR_PROMPT)
    except Exception:
        return None


# LSTM engine + single-column segmentation. psm3(자동)은 한글 스캔에서 글자 사이를 벌려
# (한 글자 토큰 ~40%) 검색 가능한 텍스트가 나오지 않았다. scripts/ocr_benchmark.py 실측
# (32쪽/56질문): psm3 F1 0.24·검색 hit@1 0.30 → psm4 F1 0.63·hit@1 0.68.
# 값을 바꿀 때는 벤치마크를 다시 돌려 근거를 확인한다(유지보수 가이드 참고).
_TESSERACT_CONFIG = "--oem 1 --psm 4"


def _ocr_page_with_confidence(image, pytesseract) -> tuple[str, float | None, int]:
    """Returns (text, mean word confidence 0-1, word count) for one page.

    The text is Tesseract's own image_to_string output. image_to_data (word
    boxes) is used only for the confidence: for Hangul it returns syllable-sized
    "words", so joining them with spaces scatters every sentence ("취 약 지",
    single-character tokens ~65% on a real scanned report vs ~5-10% from
    image_to_string). The OCR benchmark measures image_to_string, so this keeps
    production text identical to what the benchmark scored."""
    data = pytesseract.image_to_data(
        image, lang="kor+eng", config=_TESSERACT_CONFIG, output_type=pytesseract.Output.DICT,
    )
    confidences: list[float] = []
    for i, word in enumerate(data["text"]):
        if not word.strip():
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if conf >= 0:
            confidences.append(conf)
    text = pytesseract.image_to_string(image, lang="kor+eng", config=_TESSERACT_CONFIG).strip()
    mean_confidence = (sum(confidences) / len(confidences) / 100.0) if confidences else None
    return text, mean_confidence, len(confidences)


def _preprocess_for_ocr(image):
    """Grayscale only. Otsu 이진화는 벤치마크에서 이득이 없었고(F1 0.628→0.621)
    흐린 글자를 지울 위험이 있어 쓰지 않는다."""
    return image.convert("L")


def _text_block_bbox(words: list[dict]) -> tuple[float, float, float, float] | None:
    """Bounding box enclosing every extracted word on the page. Native text
    only — OCR'd pages have no word-level geometry without pytesseract's
    image_to_data, which this adapter doesn't call."""
    if not words:
        return None
    return (
        min(w["x0"] for w in words),
        min(w["top"] for w in words),
        max(w["x1"] for w in words),
        max(w["bottom"] for w in words),
    )


def _table_exclusion_rects(tables) -> list:
    """표 후보들이 본문에서 가릴 영역. 선으로 닫힌 칸이 있으면 그 칸들만, 없으면 bbox 전체."""
    rects: list = []
    for table in tables:
        if table.cell_bboxes:
            rects.extend(table.cell_bboxes)
        elif table.bbox:
            rects.append(table.bbox)
    return rects


def _text_excluding_tables(page, table_bboxes: list):
    """pdfplumber's `extract_text()` walks every character on the page by
    position — it has no notion of the ruled/bordered tables `find_tables()`
    detects, so a table's cell text is picked up twice: once here as plain
    positional text, once more in the dedicated `[표 N]` block built from
    `table.extract()`. Left unfiltered, that duplicate positional text (e.g.
    "1 김민준 개발팀", no longer pipe-delimited) reads as ordinary prose to
    downstream structure analysis, and digit-led rows can even misclassify as
    phantom headings. Cropping each table's bbox out before extraction keeps
    table content sourced from exactly one place.

    `table_bboxes` 는 표의 칸(셀) 사각형들이다 — pdfplumber 가 셀 글자를 배정하는 것과 같은 기준(글자
    중심점이 사각형 안)으로 가려서, 셀에 들어간 글자는 표 블록에만, 셀 밖 글자(칸 선이 불완전한 표의
    첫 열 본문 등)는 본문에 남아 한 번씩만 나온다."""
    if not table_bboxes:
        return page.extract_text() or ""

    def _in_table(obj) -> bool:
        if obj.get("object_type") != "char":
            return False
        cx = (obj["x0"] + obj["x1"]) / 2
        cy = (obj["top"] + obj["bottom"]) / 2
        return any(x0 <= cx <= x1 and top <= cy <= bottom for x0, top, x1, bottom in table_bboxes)

    try:
        page = page.filter(lambda obj: not _in_table(obj))
    except Exception:
        return page.extract_text() or ""
    return page.extract_text() or ""


# Chars within this many points of each other's baseline are treated as the
# same visual line — small enough to not merge two genuinely stacked lines,
# large enough to absorb normal font-rendering jitter within one line.
_LINE_TOP_TOLERANCE = 2.0


def _extract_line_layout(page, exclude_bboxes: list) -> list[dict]:
    """Per-visual-line text + font signals from pdfplumber's char-level data
    (`page.chars`), independent of and without altering the flattened `text`
    used for parsed_text/chunking/citations/page_map. Populates
    `RawParsedDocument.metadata["line_layout"]` for font-aware structure
    analysis (문서 파싱 고도화 Phase 1/2 — see base.py's RawTextBlock comment).
    Chars inside `exclude_bboxes` (already-detected table regions) are
    skipped, same as `_text_excluding_tables`, so table text isn't
    double-reported here. Returns [] when there's no char data at all (OCR'd
    pages have none — pytesseract's image_to_string carries no font info)."""
    try:
        chars = page.chars
    except Exception:
        return []
    if not chars:
        return []

    def _excluded(c) -> bool:
        cx = (c.get("x0", 0) + c.get("x1", 0)) / 2
        cy = (c.get("top", 0) + c.get("bottom", 0)) / 2
        return any(
            x0 <= cx <= x1 and top <= cy <= bottom
            for x0, top, x1, bottom in exclude_bboxes
        )

    usable = [c for c in chars if c.get("text") and not _excluded(c)]
    if not usable:
        return []

    # pdfplumber yields chars in content-stream order, not guaranteed
    # top-to-bottom — sort before clustering into lines.
    usable.sort(key=lambda c: (c["top"], c["x0"]))
    lines: list[list[dict]] = []
    for c in usable:
        if lines and abs(c["top"] - lines[-1][-1]["top"]) <= _LINE_TOP_TOLERANCE:
            lines[-1].append(c)
        else:
            lines.append([c])

    result = []
    for line_chars in lines:
        line_chars.sort(key=lambda c: c["x0"])
        text = "".join(c["text"] for c in line_chars).strip()
        if not text:
            continue
        sizes = [round(c["size"], 1) for c in line_chars if c.get("size")]
        font_size = max(set(sizes), key=sizes.count) if sizes else None
        fontnames = [c.get("fontname") or "" for c in line_chars]
        # 메타 정보 생성.txt 2절 font_name — pdfplumber가 이미 char별로 주는
        # embedded font 이름(예: "Times-Bold")을 가장 빈도 높은 것으로 채택.
        # bold/italic 판정에만 쓰고 버리던 fontnames를 재사용(신규 파싱 없음).
        named_fonts = [fn for fn in fontnames if fn]
        font_name = max(set(named_fonts), key=named_fonts.count) if named_fonts else None
        result.append({
            "text": text,
            "bbox": (
                min(c["x0"] for c in line_chars),
                min(c["top"] for c in line_chars),
                max(c["x1"] for c in line_chars),
                max(c["bottom"] for c in line_chars),
            ),
            "font_size": font_size,
            "is_bold": any("bold" in fn.lower() for fn in fontnames),
            "is_italic": any("italic" in fn.lower() or "oblique" in fn.lower() for fn in fontnames),
            "style_name": None,
            "font_name": font_name,
        })
    return result


# Implicit (line-less) table detection (문서 파싱 고도화 Phase 3):
# pdfplumber's find_tables() only sees ruled/bordered tables — a table whose
# columns are aligned purely by whitespace (common in reports exported from
# spreadsheets without borders) is invisible to it. This looks for runs of
# consecutive text rows that share whitespace-gap positions at consistent
# x-coordinates and reports each run as a lower-confidence table candidate.
_IMPLICIT_TABLE_MIN_ROWS = 3
_IMPLICIT_TABLE_MIN_COLUMNS = 2
_IMPLICIT_TABLE_ROW_TOLERANCE = 3.0
# Minimum horizontal whitespace (points) between two words to count as a
# column break rather than a normal inter-word space.
_IMPLICIT_TABLE_GAP_THRESHOLD = 8.0
# How much a column boundary's x position may drift row-to-row and still be
# treated as "the same" column — real tables aren't pixel-perfect.
_IMPLICIT_TABLE_COLUMN_X_TOLERANCE = 6.0
_IMPLICIT_TABLE_CONFIDENCE = 0.6


def _cluster_words_into_rows(words: list[dict]) -> list[list[dict]]:
    ordered = sorted(words, key=lambda w: (w["top"], w["x0"]))
    rows: list[list[dict]] = []
    for w in ordered:
        if rows and abs(w["top"] - rows[-1][-1]["top"]) <= _IMPLICIT_TABLE_ROW_TOLERANCE:
            rows[-1].append(w)
        else:
            rows.append([w])
    for row in rows:
        row.sort(key=lambda w: w["x0"])
    return rows


def _row_gap_positions(row: list[dict]) -> list[float]:
    return [
        (a["x1"] + b["x0"]) / 2
        for a, b in zip(row, row[1:])
        if b["x0"] - a["x1"] >= _IMPLICIT_TABLE_GAP_THRESHOLD
    ]


def _shared_gaps(a: list[float], b: list[float]) -> list[float]:
    return [ga for ga in a if any(abs(ga - gb) <= _IMPLICIT_TABLE_COLUMN_X_TOLERANCE for gb in b)]


# A numbered/bulleted list item's marker ("▪", "1.", "2)") sits at a fixed
# left-indent before the wrapped sentence that follows — to this heuristic's
# gap-based column detector, that indent is indistinguishable from a real
# 2-column table's boundary. Root-caused 2026-07-23: this false-positive
# cropped a real paragraph out of a 988-page document's page 13, which then
# starved that page's native-text coverage and helped trigger a bad OCR
# override (see _MIN_TRUSTED_NATIVE_CHARS). A real 2-column table has
# comparably-sized content in both columns across rows; a list marker column
# is always a single glyph while the other column is long prose.
#
# The original version additionally required column 2 to be long prose
# (>=15 chars) in most rows, to avoid rejecting genuine short-value 2-column
# tables. Verified against a real 988-page document (문서 파싱 고도화 회고,
# 2026-07-23): that co-requirement left plenty of numbered section indexes
# with SHORT labels (e.g. "00. 기관 적용 범위 및 항목" / "01. 색상" / "02. 서체")
# undetected, since "색상"/"서체" never reach 15 chars. Column 2's length no
# longer matters — an overwhelming majority of marker-like column-1 values is
# a strong enough signal by itself. Marker matching is also no longer limited
# to a fixed glyph set: real PDFs sometimes render a bullet as a substituted
# CJK compatibility character (e.g. "㏂" standing in for "▪") or a bare
# unpunctuated number ("01" with no "."), so any very short column-1 token
# counts as marker-like too.
_LIST_MARKER_RE = re.compile(r"^[▪▫•‣◦∙·※\-–—*]$|^\(?\d{1,3}[.\)]?$")
_LIST_MARKER_MAX_CHARS = 2
_LIST_MARKER_RATIO_THRESHOLD = 0.8


def _looks_like_list_marker_token(token: str) -> bool:
    return bool(_LIST_MARKER_RE.match(token)) or len(token) <= _LIST_MARKER_MAX_CHARS


def _looks_like_list_markers_not_table(table_rows: list[list[str]]) -> bool:
    if not table_rows or len(table_rows[0]) != 2:
        return False
    col0 = [row[0].strip() for row in table_rows]
    marker_like = sum(1 for c in col0 if c and _looks_like_list_marker_token(c))
    return marker_like >= len(col0) * _LIST_MARKER_RATIO_THRESHOLD


def _implicit_table_from_run(page_num: int, run: list[tuple[list[dict], list[float]]]) -> RawTableCandidate | None:
    if len(run) < _IMPLICIT_TABLE_MIN_ROWS:
        return None
    # `common` tracks each boundary's most recent x position rather than
    # freezing it at row 0's value — a boundary that drifts a little on
    # every row (e.g. 164 → 167 → 171) must be judged against its immediate
    # neighbor, not accumulate error against a value many rows back.
    common = run[0][1]
    for _, gaps in run[1:]:
        updated = []
        for c in common:
            candidates = [g for g in gaps if abs(g - c) <= _IMPLICIT_TABLE_COLUMN_X_TOLERANCE]
            if candidates:
                updated.append(min(candidates, key=lambda g: abs(g - c)))
        common = updated
    if len(common) < _IMPLICIT_TABLE_MIN_COLUMNS - 1:
        return None
    boundaries = sorted(common)
    row_words = [words_in_row for words_in_row, _ in run]
    table_rows = []
    for words_in_row in row_words:
        cells = [""] * (len(boundaries) + 1)
        for w in words_in_row:
            cx = (w["x0"] + w["x1"]) / 2
            col = sum(1 for b in boundaries if cx > b)
            cells[col] = (cells[col] + " " + w["text"]).strip()
        table_rows.append(cells)
    if _looks_like_list_markers_not_table(table_rows):
        return None
    bbox = (
        min(w["x0"] for words_in_row in row_words for w in words_in_row),
        min(w["top"] for words_in_row in row_words for w in words_in_row),
        max(w["x1"] for words_in_row in row_words for w in words_in_row),
        max(w["bottom"] for words_in_row in row_words for w in words_in_row),
    )
    return RawTableCandidate(
        page_number=page_num,
        rows=table_rows,
        bbox=bbox,
        confidence=_IMPLICIT_TABLE_CONFIDENCE,
        detected_as="implicit_alignment",
    )


def _detect_implicit_tables(
    words: list[dict], page_num: int, exclude_bboxes: list,
) -> list[RawTableCandidate]:
    """Column-aligned, line-less table detection. Words inside `exclude_bboxes`
    (already-detected ruled tables) are skipped so implicit detection can
    never overlap a ruled table already found by find_tables()."""
    if not words:
        return []

    def _excluded(w) -> bool:
        cx, cy = (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2
        return any(x0 <= cx <= x1 and top <= cy <= bottom for x0, top, x1, bottom in exclude_bboxes)

    usable = [w for w in words if not _excluded(w)]
    if not usable:
        return []

    tables: list[RawTableCandidate] = []
    run: list[tuple[list[dict], list[float]]] = []
    for row in _cluster_words_into_rows(usable):
        gaps = _row_gap_positions(row)
        is_table_row = len(row) >= _IMPLICIT_TABLE_MIN_COLUMNS and len(gaps) >= _IMPLICIT_TABLE_MIN_COLUMNS - 1
        if is_table_row and (not run or _shared_gaps(run[-1][1], gaps)):
            run.append((row, gaps))
            continue
        table = _implicit_table_from_run(page_num, run)
        if table:
            tables.append(table)
        run = [(row, gaps)] if is_table_row else []
    table = _implicit_table_from_run(page_num, run)
    if table:
        tables.append(table)
    return tables


def _image_area_ratio(page) -> float:
    page_area = page.width * page.height
    if page_area <= 0:
        return 0.0
    try:
        image_area = sum(
            max(0.0, img["x1"] - img["x0"]) * max(0.0, img["bottom"] - img["top"])
            for img in page.images
        )
    except Exception:
        return 0.0
    return min(1.0, image_area / page_area)


class PDFAdapter(BaseAdapter):
    @property
    def format_id(self) -> str:
        return "pdf"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            native_text=True,
            native_table=True,
            native_image=True,
            native_structure=False,
            bbox_available=True,
            reading_order=True,
            ocr_required=False,
        )

    def can_handle(self, file_path: Path, mime_type: str) -> bool:
        return (
            mime_type == "application/pdf"
            or file_path.suffix.lower() == ".pdf"
        )

    # engine_design.md §13.5: page-level OCR triggers when native text coverage
    # drops below 30%, or when images dominate the page (table/scan artifacts).
    _OCR_COVERAGE_THRESHOLD = 0.3
    _OCR_IMAGE_AREA_THRESHOLD = 0.5
    # A page whose native text (after excluding tables) already has at least
    # this many characters is treated as reliably parsed and skips the
    # coverage-based OCR trigger entirely, even if char density alone reads
    # low (bulleted/indented layouts are legitimately sparse per unit area).
    # Root-caused 2026-07-23: a 988-page real document's page with a fully
    # correct text layer tripped the density trigger anyway, and Tesseract's
    # Korean misread of that same bulleted layout ("longer text wins")
    # silently overwrote the correct text with garbled OCR output. OCR must
    # only fill in for pages with next to no usable native text, never
    # compete by length against a text layer that already parsed cleanly.
    _MIN_TRUSTED_NATIVE_CHARS = 50

    def extract(self, file_path: Path, options: dict) -> RawParsedDocument:
        import io

        import fitz  # pymupdf
        import pdfplumber
        import pytesseract
        from PIL import Image

        # 문서 파싱 고도화 Phase 3 설정 토글 — TextExtractConfig에서 전달됨
        # (extraction_blocks.py). 옵션이 아예 없는 호출자(과거 캐시 재생 등)는
        # 기존 동작(둘 다 켜짐)과 동일하게 기본값 True를 쓴다.
        detect_implicit_tables_enabled = options.get("detect_implicit_tables", True)
        extract_font_signals_enabled = options.get("extract_font_signals", True)

        pages = []
        warnings = []
        ocr_used = False
        fitz_doc = None
        line_layout: list[dict] = []
        # 메타 정보 생성.txt 1절 document_created_at — PDF info dict의
        # creationDate("D:YYYYMMDDHHmmSS..." 형식)를 읽는다. 별도의 짧은 fitz
        # 세션으로 처리해 아래 본문 추출(pdfplumber 기반) 로직과 독립적으로
        # 동작하며, 손상되었거나 값이 없으면 None으로 남긴다(그레이스풀 폴백).
        document_created_at = None
        try:
            meta_doc = fitz.open(str(file_path))
            try:
                document_created_at = _parse_pdf_date(meta_doc.metadata.get("creationDate"))
            finally:
                meta_doc.close()
        except Exception:
            pass
        # Global, not per-page — Document.tables[*] (extraction_blocks.py) is
        # built by iterating pages then their tables in this same order, so a
        # document-wide "[표 N]" ordinal lets structure_analyze recover which
        # doc.tables entry a TABLE node came from (source_table_id, 문서 파싱
        # 고도화 Phase 3) just by parsing the marker text — no separate lookup
        # table needed. Per-page numbering would collide across pages (every
        # page's first table would show as "[표 1]") and couldn't be reversed.
        table_ordinal = 0
        try:
            with pdfplumber.open(file_path) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    # Explicit-grid table detection (engine_design.md §11.3):
                    # pdfplumber's line-intersection based find_tables() covers the
                    # ruled/bordered table case; implicit (line-less) alignment
                    # detection is not attempted in this pass. Run this before
                    # native text extraction so table regions can be excluded
                    # from it (see _text_excluding_tables).
                    table_candidates: list[RawTableCandidate] = []
                    try:
                        found_tables = _dedupe_tables(page.find_tables(), page.width * page.height)
                    except Exception as table_exc:
                        found_tables = []
                        warnings.append(f"page {page_num} table detection failed: {table_exc}")
                    for table in found_tables:
                        try:
                            rows = table.extract()
                        except Exception as table_exc:
                            warnings.append(f"page {page_num} table extract failed: {table_exc}")
                            continue
                        cleaned_rows = [
                            [(cell or "").strip() for cell in row]
                            for row in rows
                            if any((cell or "").strip() for cell in row)
                        ]
                        if cleaned_rows:
                            table_candidates.append(
                                RawTableCandidate(
                                    page_number=page_num,
                                    rows=cleaned_rows,
                                    bbox=table.bbox,
                                    cell_bboxes=[tuple(cell) for cell in table.cells],
                                )
                            )

                    # Computed once and shared with _text_block_bbox below —
                    # pdfplumber's extract_words() re-runs word-clustering over
                    # page.chars on every call (not cached like .chars itself),
                    # so calling it twice per page measurably added up across a
                    # whole document. One call, reused, is a pure speed win.
                    try:
                        words = page.extract_words()
                    except Exception:
                        words = []

                    if detect_implicit_tables_enabled:
                        try:
                            table_candidates.extend(
                                _detect_implicit_tables(
                                    words, page_num, [t.bbox for t in table_candidates],
                                )
                            )
                        except Exception as implicit_exc:
                            warnings.append(f"page {page_num} implicit table detection failed: {implicit_exc}")

                    exclusion_rects = _table_exclusion_rects(table_candidates)
                    text = _text_excluding_tables(page, exclusion_rects)
                    block_type = "paragraph"
                    coverage = _text_coverage(text, page.width, page.height)
                    image_ratio = _image_area_ratio(page)
                    # Only populated by the Tesseract path below — a cloud VLM
                    # OCR result carries no word-level confidence at all.
                    page_ocr_confidence: float | None = None
                    page_ocr_word_count: int | None = None

                    trusted_native_text = len(text.strip()) >= self._MIN_TRUSTED_NATIVE_CHARS
                    needs_ocr = image_ratio > self._OCR_IMAGE_AREA_THRESHOLD or (
                        coverage < self._OCR_COVERAGE_THRESHOLD and not trusted_native_text
                    )
                    if needs_ocr:
                        if fitz_doc is None:
                            fitz_doc = fitz.open(str(file_path))
                        ocr_text = ""
                        try:
                            pixmap = fitz_doc[page_num - 1].get_pixmap(dpi=300)
                            page_image_bytes = pixmap.tobytes("png")
                        except Exception as render_exc:
                            warnings.append(f"page {page_num} render failed: {render_exc}")
                            page_image_bytes = None

                        vision_backend = options.get("vision_backend")
                        vision_api_key = options.get("vision_api_key")
                        if page_image_bytes and vision_backend and vision_api_key:
                            vlm_text = _cloud_vlm_ocr(page_image_bytes, vision_backend, vision_api_key)
                            if vlm_text and vlm_text.strip():
                                ocr_text = vlm_text

                        if not ocr_text.strip() and page_image_bytes:
                            try:
                                image = Image.open(io.BytesIO(page_image_bytes))
                                ocr_text, page_ocr_confidence, page_ocr_word_count = _ocr_page_with_confidence(
                                    _preprocess_for_ocr(image), pytesseract,
                                )
                            except Exception as ocr_exc:
                                warnings.append(f"page {page_num} OCR failed: {ocr_exc}")
                                ocr_text = ""
                                page_ocr_confidence, page_ocr_word_count = None, None

                        # OCR only replaces native text when that native text wasn't
                        # already trustworthy — never by raw length alone (see
                        # _MIN_TRUSTED_NATIVE_CHARS above for why "longer wins" is
                        # unsafe: a bad OCR misread can out-count a short but
                        # perfectly correct text layer).
                        if not trusted_native_text and ocr_text.strip() and len(ocr_text.strip()) > len(text.strip()):
                            text = ocr_text
                            block_type = "ocr"
                            ocr_used = True
                            coverage = _text_coverage(text, page.width, page.height)
                        else:
                            # OCR ran but lost to the native/table text already
                            # extracted — the confidence figure would describe
                            # discarded text, not what this page actually reports.
                            page_ocr_confidence, page_ocr_word_count = None, None

                    text_blocks = []
                    if text.strip():
                        text_blocks.append(
                            RawTextBlock(
                                text=text,
                                page_number=page_num,
                                bbox=_text_block_bbox(words) if block_type != "ocr" else None,
                                block_type=block_type,
                            )
                        )
                        if block_type != "ocr" and extract_font_signals_enabled:
                            for line in _extract_line_layout(page, exclusion_rects):
                                line["page_number"] = page_num
                                line_layout.append(line)

                    for table in table_candidates:
                        table_ordinal += 1
                        table_text = rows_to_markdown(table.rows)
                        text_blocks.append(
                            RawTextBlock(
                                text=f"[표 {table_ordinal}]\n{table_text}",
                                page_number=page_num,
                                bbox=table.bbox,
                                block_type="table",
                            )
                        )

                    # Embedded figure extraction: skipped for OCR'd pages, whose
                    # full render already went through VLM/Tesseract above —
                    # re-recognizing their embedded images would double-count.
                    image_regions: list[RawImageRegion] = []
                    if block_type != "ocr":
                        try:
                            if fitz_doc is None:
                                fitz_doc = fitz.open(str(file_path))
                            seen_xrefs: set[int] = set()
                            for img_info in fitz_doc[page_num - 1].get_image_info(xrefs=True):
                                xref = img_info.get("xref")
                                if not xref or xref in seen_xrefs:
                                    continue
                                seen_xrefs.add(xref)
                                extracted = fitz_doc.extract_image(xref)
                                if extracted and extracted.get("image"):
                                    image_regions.append(
                                        RawImageRegion(
                                            page_number=page_num,
                                            bbox=tuple(img_info.get("bbox", (0, 0, 0, 0))),
                                            image_bytes=extracted["image"],
                                        )
                                    )
                        except Exception as img_exc:
                            warnings.append(f"page {page_num} image extraction failed: {img_exc}")

                    pages.append(
                        RawPage(
                            page_number=page_num,
                            width=page.width,
                            height=page.height,
                            text_blocks=text_blocks,
                            table_candidates=table_candidates,
                            image_regions=image_regions,
                            native_text_coverage=coverage,
                            image_area_ratio=image_ratio,
                            ocr_confidence=page_ocr_confidence if block_type == "ocr" else None,
                            ocr_word_count=page_ocr_word_count if block_type == "ocr" else None,
                        )
                    )

                return RawParsedDocument(
                    format_id="pdf",
                    page_count=len(pdf.pages),
                    pages=pages,
                    metadata={
                        "ocr_used": ocr_used,
                        "line_layout": line_layout,
                        "document_created_at": document_created_at,
                    },
                    warnings=warnings,
                )
        except Exception as e:
            return RawParsedDocument(
                format_id="pdf",
                page_count=0,
                pages=[],
                metadata={},
                warnings=[str(e)],
            )
        finally:
            if fitz_doc is not None:
                fitz_doc.close()

    def extract_metadata(self, file_path: Path) -> dict:
        return {"file_path": str(file_path)}
