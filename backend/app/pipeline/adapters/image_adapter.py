"""이미지 어댑터(전체 점검 1-2). PNG, JPG, TIFF, BMP, WEBP.

이미지를 쪽마다 한 장인 PDF로 바꿔 스캔 PDF와 같은 길(전면 OCR)로 보낸다. 여러 장짜리 TIFF는
장마다 한 쪽이 된다. OCR 설정과 품질 판정을 스캔 PDF와 똑같이 쓰려고 따로 OCR을 부르지 않는다.
"""
import tempfile
from pathlib import Path

from app.pipeline.adapters.base import AdapterCapabilities, BaseAdapter, RawParsedDocument
from app.pipeline.adapters.simple_layout import failed
from app.pipeline.formats import IMAGE_SUFFIXES


def image_to_pdf_bytes(file_path: Path) -> bytes:
    import fitz

    with fitz.open(str(file_path)) as image:
        return image.convert_to_pdf()


class ImageAdapter(BaseAdapter):
    @property
    def format_id(self) -> str:
        return "image"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            native_text=False, native_table=False, native_image=True, native_structure=False,
            bbox_available=False, reading_order=False, ocr_required=True,
        )

    def can_handle(self, file_path: Path, mime_type: str) -> bool:
        return file_path.suffix.lower() in IMAGE_SUFFIXES

    def extract(self, file_path: Path, options: dict) -> RawParsedDocument:
        from app.pipeline.adapters.pdf_adapter import PDFAdapter

        try:
            pdf_bytes = image_to_pdf_bytes(file_path)
        except Exception as exc:  # noqa: BLE001
            return failed("image", f"이미지 파일을 열지 못했습니다: {exc}")

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            pdf_path = Path(tmp.name)
            try:
                tmp.write(pdf_bytes)
            except BaseException:
                pdf_path.unlink(missing_ok=True)
                raise
        try:
            parsed = PDFAdapter().extract(pdf_path, options)
        finally:
            pdf_path.unlink(missing_ok=True)
        parsed.format_id = "image"
        return parsed

    def extract_metadata(self, file_path: Path) -> dict:
        return {"file_path": str(file_path)}
