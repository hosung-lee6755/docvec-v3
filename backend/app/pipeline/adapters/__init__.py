from pathlib import Path

from app.pipeline.adapters.base import BaseAdapter


class UnsupportedFileTypeError(Exception):
    def __init__(self, file_path: Path, mime_type: str):
        self.suffix = file_path.suffix
        self.mime_type = mime_type
        super().__init__(
            f"지원하지 않는 파일 형식입니다: {self.suffix or mime_type or '알 수 없음'}. "
            "지원 형식: PDF, DOCX, HWP, HWPX"
        )


def get_adapter(file_path: Path, mime_type: str, engine: str = "legacy") -> BaseAdapter:
    from app.pipeline.adapters.docx_adapter import DOCXAdapter
    from app.pipeline.adapters.hwp_adapter import HWPAdapter
    from app.pipeline.adapters.pdf_adapter import PDFAdapter

    for adapter in (PDFAdapter(), HWPAdapter(), DOCXAdapter()):
        if adapter.can_handle(file_path, mime_type):
            # Docling은 PDF만 지원 — DOCX/HWP/HWPX는 engine 값과 무관하게
            # 항상 기존 어댑터(Docling 도입 설계서, 2026-07-23 Phase 1).
            if engine == "docling" and adapter.format_id == "pdf":
                from app.pipeline.adapters.docling_adapter import DoclingAdapter

                return DoclingAdapter()
            return adapter
    raise UnsupportedFileTypeError(file_path, mime_type)
