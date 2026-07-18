from pathlib import Path

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


# LSTM engine + auto page segmentation — measurably better than defaults on
# Korean scans in side-by-side tests on real documents.
_TESSERACT_CONFIG = "--oem 1 --psm 3"


def _preprocess_for_ocr(image):
    """Grayscale → autocontrast → Otsu binarization. Tesseract's Korean
    recognition degrades badly on gray/noisy scans, producing interleaved
    Latin gibberish; adaptive-threshold binarization substantially reduces
    that failure mode (verified on real scanned reports)."""
    import numpy as np
    from PIL import Image, ImageOps

    gray = ImageOps.autocontrast(image.convert("L"))
    arr = np.asarray(gray)
    hist, _ = np.histogram(arr, bins=256, range=(0, 256))
    total = arr.size
    sum_all = float((np.arange(256) * hist).sum())
    sum_b = 0.0
    weight_b = 0.0
    max_var = 0.0
    threshold = 127
    for i in range(256):
        weight_b += hist[i]
        if weight_b == 0:
            continue
        weight_f = total - weight_b
        if weight_f == 0:
            break
        sum_b += i * hist[i]
        mean_b = sum_b / weight_b
        mean_f = (sum_all - sum_b) / weight_f
        var = weight_b * weight_f * (mean_b - mean_f) ** 2
        if var > max_var:
            max_var = var
            threshold = i
    return Image.fromarray(((arr > threshold) * 255).astype("uint8"))


def _text_block_bbox(page) -> tuple[float, float, float, float] | None:
    """Bounding box enclosing every extracted word on the page. Native text
    only — OCR'd pages have no word-level geometry without pytesseract's
    image_to_data, which this adapter doesn't call."""
    try:
        words = page.extract_words()
    except Exception:
        return None
    if not words:
        return None
    return (
        min(w["x0"] for w in words),
        min(w["top"] for w in words),
        max(w["x1"] for w in words),
        max(w["bottom"] for w in words),
    )


def _text_excluding_tables(page, table_bboxes: list):
    """pdfplumber's `extract_text()` walks every character on the page by
    position — it has no notion of the ruled/bordered tables `find_tables()`
    detects, so a table's cell text is picked up twice: once here as plain
    positional text, once more in the dedicated `[표 N]` block built from
    `table.extract()`. Left unfiltered, that duplicate positional text (e.g.
    "1 김민준 개발팀", no longer pipe-delimited) reads as ordinary prose to
    downstream structure analysis, and digit-led rows can even misclassify as
    phantom headings. Cropping each table's bbox out before extraction keeps
    table content sourced from exactly one place."""
    for bbox in table_bboxes:
        try:
            page = page.outside_bbox(bbox)
        except Exception:
            continue
    return page.extract_text() or ""


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

    def extract(self, file_path: Path, options: dict) -> RawParsedDocument:
        import io

        import fitz  # pymupdf
        import pdfplumber
        import pytesseract
        from PIL import Image

        pages = []
        warnings = []
        ocr_used = False
        fitz_doc = None
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
                        except Exception:
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
                                )
                            )

                    text = _text_excluding_tables(page, [t.bbox for t in table_candidates])
                    block_type = "paragraph"
                    coverage = _text_coverage(text, page.width, page.height)
                    image_ratio = _image_area_ratio(page)

                    if coverage < self._OCR_COVERAGE_THRESHOLD or image_ratio > self._OCR_IMAGE_AREA_THRESHOLD:
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
                                ocr_text = pytesseract.image_to_string(
                                    _preprocess_for_ocr(image),
                                    lang="kor+eng",
                                    config=_TESSERACT_CONFIG,
                                )
                            except Exception as ocr_exc:
                                warnings.append(f"page {page_num} OCR failed: {ocr_exc}")
                                ocr_text = ""

                        if ocr_text.strip() and len(ocr_text.strip()) > len(text.strip()):
                            text = ocr_text
                            block_type = "ocr"
                            ocr_used = True
                            coverage = _text_coverage(text, page.width, page.height)

                    text_blocks = []
                    if text.strip():
                        text_blocks.append(
                            RawTextBlock(
                                text=text,
                                page_number=page_num,
                                bbox=_text_block_bbox(page) if block_type != "ocr" else None,
                                block_type=block_type,
                            )
                        )

                    for i, table in enumerate(table_candidates):
                        table_text = "\n".join(" | ".join(row) for row in table.rows)
                        text_blocks.append(
                            RawTextBlock(
                                text=f"[표 {i + 1}]\n{table_text}",
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
                        )
                    )

                return RawParsedDocument(
                    format_id="pdf",
                    page_count=len(pdf.pages),
                    pages=pages,
                    metadata={"ocr_used": ocr_used},
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
