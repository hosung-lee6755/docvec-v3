from pathlib import Path
from typing import Iterator

from app.pipeline.blocks.table_markdown import rows_to_markdown

from app.pipeline.adapters.base import (
    AdapterCapabilities,
    BaseAdapter,
    RawImageRegion,
    RawPage,
    RawParsedDocument,
    RawTableCandidate,
    RawTextBlock,
)

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".tif")


def _docx_embedded_images(file_path: Path) -> list[bytes]:
    """A .docx is a zip; embedded media live under word/media/*. Read them
    directly instead of walking python-docx relationship objects — inline
    position isn't recoverable either way (docx has no fixed pages)."""
    import zipfile

    images: list[bytes] = []
    with zipfile.ZipFile(file_path, "r") as z:
        for name in sorted(z.namelist()):
            if name.startswith("word/media/") and name.lower().endswith(_IMAGE_SUFFIXES):
                images.append(z.read(name))
    return images


def _iter_block_items(doc) -> Iterator[object]:
    """Yield each body-level paragraph/table in true document order.

    doc.paragraphs and doc.tables are separate flat lists — a table sitting
    between two paragraphs in the source ends up entirely after both once
    read that way, scrambling reading order for any docx with an inline
    table (문서 파싱 고도화 회고, 2026-07-23: found while auditing docx
    fidelity against the same "output must match source" bar used for the
    PDF OCR-reconciliation bug). Walking doc.element.body directly preserves
    the actual order."""
    from docx.oxml.ns import qn
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph as DocxParagraph

    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield DocxParagraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield DocxTable(child, doc)


class DOCXAdapter(BaseAdapter):
    @property
    def format_id(self) -> str:
        return "docx"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            native_text=True,
            native_table=True,
            native_image=False,
            native_structure=True,
            bbox_available=False,
            reading_order=True,
            ocr_required=False,
        )

    def can_handle(self, file_path: Path, mime_type: str) -> bool:
        return (
            file_path.suffix.lower() == ".docx"
            or mime_type
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    def extract(self, file_path: Path, options: dict) -> RawParsedDocument:
        try:
            from docx import Document as DocxDocument  # type: ignore[import]
        except ImportError:
            return RawParsedDocument(
                format_id="docx",
                page_count=0,
                pages=[],
                metadata={},
                warnings=["python-docx library not installed; cannot parse .docx files"],
            )

        try:
            from docx.table import Table as DocxTable
            from docx.text.paragraph import Paragraph as DocxParagraph

            doc = DocxDocument(str(file_path))
            extract_font_signals = options.get("extract_font_signals", True)

            text_blocks: list[RawTextBlock] = []
            table_candidates: list[RawTableCandidate] = []
            # Per-paragraph font signals for font-aware structure analysis
            # (문서 파싱 고도화 Phase 1/2) — a side artifact alongside full_text,
            # not a replacement for it (see base.py's RawTextBlock comment).
            # Skippable via options["extract_font_signals"] (문서 파싱 고도화
            # Phase 3 config toggle, TextExtractConfig.extract_font_signals) —
            # default True matches pre-toggle behavior.
            line_layout: list[dict] = []
            table_ordinal = 0

            for item in _iter_block_items(doc):
                if isinstance(item, DocxParagraph):
                    stripped = item.text.strip()
                    if not stripped:
                        continue
                    text_blocks.append(RawTextBlock(text=stripped, page_number=1))
                    if extract_font_signals:
                        sizes = [r.font.size.pt for r in item.runs if r.font.size]
                        font_size = max(set(sizes), key=sizes.count) if sizes else None
                        # 메타 정보 생성.txt 2절 font_name — run.font.name(직접
                        # 지정된 글꼴)이 비어 있으면 문단 style의 글꼴을 폴백으로
                        # 쓴다(item.style.font.name, 대부분의 본문 텍스트는 직접
                        # run.font.name을 지정하지 않고 스타일의 글꼴을 상속받음).
                        names = [r.font.name for r in item.runs if r.font.name] or (
                            [item.style.font.name] if item.style and item.style.font.name else []
                        )
                        font_name = max(set(names), key=names.count) if names else None
                        line_layout.append({
                            "page_number": 1,
                            "text": stripped,
                            "bbox": None,
                            "font_size": font_size,
                            "is_bold": any(r.font.bold for r in item.runs if r.font.bold is True),
                            "is_italic": any(r.font.italic for r in item.runs if r.font.italic is True),
                            "style_name": item.style.name if item.style else None,
                            "font_name": font_name,
                        })
                elif isinstance(item, DocxTable):
                    rows = [[cell.text.strip() for cell in row.cells] for row in item.rows]
                    cleaned_rows = [row for row in rows if any(cell for cell in row)]
                    if not cleaned_rows:
                        continue
                    table_ordinal += 1
                    table_candidates.append(RawTableCandidate(page_number=1, rows=cleaned_rows))
                    table_text = rows_to_markdown(cleaned_rows)
                    text_blocks.append(
                        RawTextBlock(
                            text=f"[표 {table_ordinal}]\n{table_text}",
                            page_number=1,
                            block_type="table",
                        )
                    )

            warnings: list[str] = []
            image_regions: list[RawImageRegion] = []
            try:
                image_regions = [
                    RawImageRegion(page_number=1, bbox=(0, 0, 0, 0), image_bytes=data)
                    for data in _docx_embedded_images(file_path)
                ]
            except Exception as img_exc:
                warnings.append(f"DOCX image extraction failed: {img_exc}")

            page = RawPage(
                page_number=1,
                width=595,
                height=842,
                text_blocks=text_blocks,
                table_candidates=table_candidates,
                image_regions=image_regions,
            )
            # 메타 정보 생성.txt 1절 document_created_at — docx core properties에
            # 이미 있는 값을 읽기만 하면 되므로(신규 의존성 없음) 문서 자체의
            # 작성일로 그대로 사용한다. 손상된 파일 등으로 못 읽으면 None.
            document_created_at = None
            try:
                document_created_at = doc.core_properties.created
            except Exception:
                pass

            return RawParsedDocument(
                format_id="docx",
                page_count=1,
                pages=[page],
                metadata={"line_layout": line_layout, "document_created_at": document_created_at},
                warnings=warnings,
            )
        except Exception as exc:
            return RawParsedDocument(
                format_id="docx",
                page_count=0,
                pages=[],
                metadata={},
                warnings=[f"DOCX extraction failed: {exc}"],
            )

    def extract_metadata(self, file_path: Path) -> dict:
        return {"file_path": str(file_path)}
