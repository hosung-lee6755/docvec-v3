from pathlib import Path

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
            doc = DocxDocument(str(file_path))
            paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            full_text = "\n".join(paragraphs)

            text_blocks = []
            if full_text:
                text_blocks.append(RawTextBlock(text=full_text, page_number=1))

            table_candidates: list[RawTableCandidate] = []
            for table in doc.tables:
                rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
                cleaned_rows = [row for row in rows if any(cell for cell in row)]
                if cleaned_rows:
                    table_candidates.append(RawTableCandidate(page_number=1, rows=cleaned_rows))

            for i, table in enumerate(table_candidates):
                table_text = "\n".join(" | ".join(row) for row in table.rows)
                text_blocks.append(
                    RawTextBlock(
                        text=f"[표 {i + 1}]\n{table_text}", page_number=1, block_type="table"
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
            return RawParsedDocument(
                format_id="docx", page_count=1, pages=[page], metadata={}, warnings=warnings
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
