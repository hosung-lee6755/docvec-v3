"""스캔 PDF의 표와 그림 찾기(전체 점검 1-3, 2026-11-16).

스캔 PDF는 글자가 그림 한 장이라 전면 OCR 엔진(pdf_adapter)으로 읽는데, 이 엔진은 표와 그림을
찾지 못한다(실측: 27쪽 보고서에서 표 0개, 그림 0개). Docling을 전면 OCR로 돌리면 같은 문서에서
표 9개, 그림 10개를 찾는다. 다만 Docling이 쓰는 OCR은 글자를 덜 정확하게 읽는다(EasyOCR은 조사
"을"을 "올"로 읽고, Tesseract를 붙이면 조사 인식이 더 떨어진다. 2026-11-16 실측).

그래서 본문은 기존 전면 OCR 결과를 그대로 두고, Docling은 표와 그림을 찾는 데만 쓴다. 찾은 표는
쪽 끝에 "[표 N]"으로 덧붙이고, 그림은 그림 인식 대상으로 넘긴다. 표 안의 글자는 Docling의 OCR이
읽은 것이라 본문보다 오독이 많다. 표의 낱말은 본문 OCR에도 들어 있으므로 검색은 본문으로 되고,
표는 행과 열의 구조를 살리는 데 쓴다.
"""
import io
import logging
from pathlib import Path

from app.pipeline.adapters.base import RawImageRegion, RawParsedDocument, RawTableCandidate, RawTextBlock
from app.pipeline.blocks.table_markdown import rows_to_markdown

logger = logging.getLogger(__name__)

DETECTED_AS = "ocr_layout"
TABLE_CONFIDENCE = 0.6
# 칸이 이보다 적은 표는 레이아웃 오인식(글 상자, 쪽 번호)인 경우가 많다
_MIN_TABLE_CELLS = 4

_converter = None


def _get_converter():
    """전면 OCR용 변환기. 글자 층이 있는 PDF용 변환기(docling_adapter)와 설정이 달라 따로 둔다."""
    global _converter
    if _converter is None:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import EasyOcrOptions, PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        options = PdfPipelineOptions()
        options.do_ocr = True
        options.do_table_structure = True
        options.ocr_options = EasyOcrOptions(lang=["ko", "en"], force_full_page_ocr=True)
        options.generate_picture_images = True
        _converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
    return _converter


def _provenance(item) -> tuple[int | None, tuple[float, float, float, float] | None]:
    prov = (getattr(item, "prov", None) or [None])[0]
    if prov is None:
        return None, None
    box = getattr(prov, "bbox", None)
    bbox = (float(box.l), float(box.t), float(box.r), float(box.b)) if box is not None else None
    return getattr(prov, "page_no", None), bbox


def _table_rows(table, document) -> list[list[str]]:
    frame = table.export_to_dataframe(document)
    header = [str(column).strip() for column in frame.columns]
    rows = [[str(value).strip() for value in row] for row in frame.itertuples(index=False)]
    # 머리글이 없는 표는 열 이름이 0, 1, 2로 나온다. 그런 머리글 행은 넣지 않는다
    has_header = any(not name.isdigit() for name in header)
    return ([header] if has_header else []) + rows


def _picture_bytes(picture, document) -> bytes | None:
    image = picture.get_image(document)
    if image is None:
        return None
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def detect_layout(pdf_path: Path) -> tuple[list[dict], list[dict]]:
    """(표 목록, 그림 목록). 표는 {"page", "bbox", "rows"}, 그림은 {"page", "bbox", "image_bytes"}."""
    document = _get_converter().convert(str(pdf_path)).document
    tables, pictures = [], []
    for table in document.tables:
        page, bbox = _provenance(table)
        rows = _table_rows(table, document)
        if page and sum(1 for row in rows for cell in row if cell) >= _MIN_TABLE_CELLS:
            tables.append({"page": page, "bbox": bbox, "rows": rows})
    for picture in document.pictures:
        page, bbox = _provenance(picture)
        image_bytes = _picture_bytes(picture, document)
        if page and bbox and image_bytes:
            pictures.append({"page": page, "bbox": bbox, "image_bytes": image_bytes})
    return tables, pictures


def merge_layout(parsed: RawParsedDocument, tables: list[dict], pictures: list[dict]) -> dict:
    """찾은 표와 그림을 쪽에 덧붙인다. 표 번호는 문서에 이미 있는 표 다음부터 잇는다."""
    pages = {page.page_number: page for page in parsed.pages}
    ordinal = sum(1 for page in parsed.pages for block in page.text_blocks if block.block_type == "table")
    added_tables = added_pictures = 0
    for table in sorted(tables, key=lambda t: (t["page"], -(t["bbox"][1] if t["bbox"] else 0))):
        page = pages.get(table["page"])
        if page is None:
            continue
        ordinal += 1
        added_tables += 1
        page.table_candidates.append(RawTableCandidate(
            page_number=page.page_number, rows=table["rows"], bbox=table["bbox"],
            confidence=TABLE_CONFIDENCE, detected_as=DETECTED_AS,
        ))
        page.text_blocks.append(RawTextBlock(
            text=f"[표 {ordinal}]\n{rows_to_markdown(table['rows'])}",
            page_number=page.page_number, bbox=table["bbox"], block_type="table", confidence=TABLE_CONFIDENCE,
        ))
    for picture in pictures:
        page = pages.get(picture["page"])
        if page is None:
            continue
        added_pictures += 1
        page.image_regions.append(RawImageRegion(
            page_number=page.page_number, bbox=picture["bbox"], image_bytes=picture["image_bytes"],
        ))
    return {"tables": added_tables, "figures": added_pictures}


def enrich_scanned_pdf(parsed: RawParsedDocument, pdf_path: Path) -> dict:
    """스캔 PDF의 추출 결과에 표와 그림을 더한다. 실패하면 본문만으로 계속하고 경고를 남긴다."""
    try:
        tables, pictures = detect_layout(pdf_path)
    except Exception as exc:  # noqa: BLE001 - 표와 그림은 덤이다. 본문 추출까지 실패시키지 않는다
        logger.exception("scan layout detection failed: %s", pdf_path.name)
        parsed.warnings.append(f"스캔 문서의 표와 그림을 찾지 못했습니다: {exc}")
        return {"tables": 0, "figures": 0}
    added = merge_layout(parsed, tables, pictures)
    if added["tables"] or added["figures"]:
        parsed.warnings.append(
            f"스캔 문서에서 표 {added['tables']}개와 그림 {added['figures']}개를 찾아 덧붙였습니다. "
            "표 안의 글자는 본문보다 오독이 많을 수 있습니다."
        )
    return added
