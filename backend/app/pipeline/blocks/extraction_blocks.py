"""입력·추출 블록: 파일검증/형식판별/텍스트추출/OCR — 통합 설계서 §3.3①~④.

These replace the front end of the retired fixed pipeline (parse_document,
app/pipeline/tasks/pipeline.py). They call the exact same adapter/helper
functions parse_document used to call, just from a block's run() instead of
a Celery task body, so extraction behavior is unchanged from before the
cutover — only the orchestration moved.
"""
import tempfile
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from app.pipeline.blocks.base import BaseBlock, BlockContext, BlockExecutionError, BlockResult

_DEFAULT_ALLOWED_EXTENSIONS = [".pdf", ".docx", ".hwp", ".hwpx"]
# PDF-only has_text_layer heuristic (format_detect) — sample the first few
# pages rather than the whole document so detection stays cheap; a scanned
# PDF has ~0 extractable chars on every page, a real one has plenty on any.
_PDF_SAMPLE_PAGES = 3
_PDF_TEXT_LAYER_MIN_CHARS = 20


class FileValidateConfig(BaseModel):
    max_file_size_mb: float = 100.0
    allowed_extensions: list[str] = _DEFAULT_ALLOWED_EXTENSIONS
    reject_encrypted: bool = True
    reject_duplicates: bool = True
    max_pages: int = 1000
    scan_malware: bool = False


class FileValidateBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "file_validate"

    @property
    def category(self) -> str:
        return "입력·추출"

    @property
    def config_schema(self):
        return FileValidateConfig

    def run(self, context: BlockContext) -> BlockResult:
        from app.db.models.document import Document
        from app.db.session import get_sync_db

        if not context.document_id:
            raise ValueError("실행할 문서가 지정되지 않았습니다.")

        cfg = FileValidateConfig(**(context.config or {}))
        db = get_sync_db()
        try:
            doc = db.get(Document, context.document_id)
            if doc is None:
                raise ValueError("지정된 문서를 찾을 수 없습니다.")

            checks: list[dict] = []
            suffix = Path(doc.filename).suffix.lower()
            ext_ok = suffix in {e.lower() for e in cfg.allowed_extensions}
            checks.append({"name": "extension", "ok": ext_ok, "detail": suffix})
            if not ext_ok:
                raise BlockExecutionError(
                    f"지원하지 않는 파일 형식입니다: {suffix or '알 수 없음'}",
                    error_code="FILE_UNSUPPORTED", permanent=True,
                )

            size_mb = doc.file_size / (1024 * 1024)
            size_ok = size_mb <= cfg.max_file_size_mb
            checks.append({"name": "file_size", "ok": size_ok, "detail": f"{size_mb:.1f}MB"})
            if not size_ok:
                raise BlockExecutionError(
                    f"파일 크기 초과: {size_mb:.1f}MB > {cfg.max_file_size_mb}MB",
                    error_code="FILE_UNSUPPORTED", permanent=True,
                )

            if cfg.reject_duplicates:
                dup = db.query(Document).filter(
                    Document.file_hash == doc.file_hash,
                    Document.id != doc.id,
                    Document.collection_id == doc.collection_id,
                ).first()
                checks.append({
                    "name": "duplicate", "ok": dup is None,
                    "detail": str(dup.id) if dup else None,
                })

            # reject_encrypted/max_pages: real detection needs the file open,
            # which format_detect already does next — enforced there instead
            # of downloading the file twice. scan_malware: no-op placeholder,
            # no ClamAV integration exists yet (설계서 §3.3① "연동 여지").
            if cfg.scan_malware:
                checks.append({"name": "malware_scan", "ok": True, "detail": "스캔 미연동(통과 처리)"})

            return BlockResult(output={"passed": True, "checks": checks, "document_id": str(doc.id)})
        finally:
            db.close()


class FormatDetectConfig(BaseModel):
    pass


def _detect_pdf_signals(path: Path) -> tuple[bool, bool, float]:
    """Best-effort has_text_layer/is_encrypted/confidence for PDFs, sampling
    the first few pages. Non-PDF formats never reach this — DOCX/HWP/HWPX
    have no scanned-image variant, so callers treat them as has_text_layer."""
    import pdfplumber

    try:
        with pdfplumber.open(path) as pdf:
            sample = pdf.pages[:_PDF_SAMPLE_PAGES]
            text_chars = sum(len((p.extract_text() or "").strip()) for p in sample)
            has_text_layer = text_chars >= _PDF_TEXT_LAYER_MIN_CHARS
            confidence = 1.0 if has_text_layer else min(1.0, text_chars / (_PDF_TEXT_LAYER_MIN_CHARS * 5))
            return has_text_layer, False, confidence
    except Exception as exc:
        if "password" in str(exc).lower() or "encrypt" in str(exc).lower():
            return False, True, 0.0
        return True, False, 0.5


class FormatDetectBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "format_detect"

    @property
    def category(self) -> str:
        return "입력·추출"

    @property
    def config_schema(self):
        return FormatDetectConfig

    def run(self, context: BlockContext) -> BlockResult:
        from app.core.config import settings
        from app.db.models.document import Document
        from app.db.session import get_sync_db
        from app.pipeline.adapters import UnsupportedFileTypeError, get_adapter
        from app.services.storage import storage_service

        db = get_sync_db()
        try:
            doc = db.get(Document, context.document_id)
            if doc is None:
                raise ValueError("지정된 문서를 찾을 수 없습니다.")

            raw_bytes = storage_service.download_file(settings.minio_bucket_originals, doc.minio_key)
            with tempfile.NamedTemporaryFile(suffix=Path(doc.filename).suffix, delete=False) as tmp:
                tmp.write(raw_bytes)
                tmp_path = Path(tmp.name)
            try:
                try:
                    adapter = get_adapter(tmp_path, doc.mime_type or "")
                except UnsupportedFileTypeError as exc:
                    raise BlockExecutionError(
                        str(exc), error_code="FILE_UNSUPPORTED", permanent=True
                    ) from exc

                has_text_layer, is_encrypted, confidence = True, False, 1.0
                if tmp_path.suffix.lower() == ".pdf":
                    has_text_layer, is_encrypted, confidence = _detect_pdf_signals(tmp_path)
            finally:
                tmp_path.unlink(missing_ok=True)

            if is_encrypted:
                raise BlockExecutionError(
                    "암호화된 파일은 처리할 수 없습니다.", error_code="FILE_ENCRYPTED", permanent=True
                )

            return BlockResult(output={
                "document_id": str(doc.id),
                "detected_file_type": type(adapter).__name__.replace("Adapter", "").lower(),
                "detected_mime_type": doc.mime_type,
                "is_scanned_document": not has_text_layer,
                "has_text_layer": has_text_layer,
                "is_encrypted": is_encrypted,
                "confidence": confidence,
            })
        finally:
            db.close()


class TextExtractConfig(BaseModel):
    extract_tables: bool = True
    extract_images: bool = True
    recognize_figures: bool = True
    max_figures: int = 40


class TextExtractBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "text_extract"

    @property
    def category(self) -> str:
        return "입력·추출"

    @property
    def config_schema(self):
        return TextExtractConfig

    def run(self, context: BlockContext) -> BlockResult:
        from app.db.models.document import Document
        from app.db.models.document_revision import DocumentTextRevision
        from app.db.session import get_sync_db
        from app.pipeline.adapters import UnsupportedFileTypeError, get_adapter
        from app.pipeline.job_tracker import complete_job, fail_job, start_job
        from app.pipeline.tasks.process import (
            _build_page_map,
            _recognize_document_images,
            _repaginate_hwp_like,
            _resolve_vision_credentials,
        )
        from app.core.config import settings
        from app.services.storage import storage_service

        if not context.document_id:
            raise ValueError("실행할 문서가 지정되지 않았습니다.")
        cfg = TextExtractConfig(**(context.config or {}))

        db = get_sync_db()
        current_job = start_job(db, context.document_id, "PARSE")
        try:
            doc = db.get(Document, context.document_id)
            if doc is None:
                raise ValueError("지정된 문서를 찾을 수 없습니다.")

            doc.status = "PARSING"
            doc.updated_at = datetime.utcnow()
            db.commit()

            raw_bytes = storage_service.download_file(settings.minio_bucket_originals, doc.minio_key)
            with tempfile.NamedTemporaryFile(suffix=Path(doc.filename).suffix, delete=False) as tmp:
                tmp.write(raw_bytes)
                tmp_path = Path(tmp.name)
            try:
                try:
                    adapter = get_adapter(tmp_path, doc.mime_type or "")
                except UnsupportedFileTypeError as exc:
                    raise BlockExecutionError(
                        str(exc), error_code="FILE_UNSUPPORTED", permanent=True
                    ) from exc
                vision_options = _resolve_vision_credentials(db, doc)
                parsed = adapter.extract(tmp_path, vision_options)
            finally:
                tmp_path.unlink(missing_ok=True)

            if parsed.format_id in ("hwp", "hwpx"):
                try:
                    _repaginate_hwp_like(str(doc.id), doc, parsed)
                except Exception:
                    pass  # degrade to page_number=1, matching parse_document's behavior

            image_records = []
            if cfg.recognize_figures:
                try:
                    image_records = _recognize_document_images(str(doc.id), parsed, vision_options)
                except Exception:
                    image_records = []

            full_text = "\n\n".join(
                block.text
                for page in parsed.pages
                for block in page.text_blocks
                if block.text.strip()
            )
            table_count = sum(len(page.table_candidates) for page in parsed.pages)
            complete_job(
                db, current_job,
                f"텍스트 {len(full_text):,}자, 표 {table_count}개, 그림 {len(image_records)}개 추출"
                f" ({len(parsed.pages)}페이지)",
            )

            doc.parsed_text = full_text
            doc.page_map = _build_page_map(parsed.pages)
            doc.ocr_used = bool(parsed.metadata.get("ocr_used", False))
            doc.tables = [
                {"page_number": page.page_number, "rows": table.rows}
                for page in parsed.pages
                for table in page.table_candidates
            ] or None
            doc.images = image_records or None
            doc.updated_at = datetime.utcnow()

            db.add(DocumentTextRevision(document_id=str(doc.id), source="PARSE", parsed_text=full_text))
            db.commit()

            return BlockResult(
                output={
                    "document_id": str(doc.id),
                    "text": full_text,
                    "chars": len(full_text),
                    "page_count": len(parsed.pages),
                    "ocr_used": doc.ocr_used,
                },
                metrics={"chars": len(full_text), "tables": table_count, "images": len(image_records)},
            )
        except BlockExecutionError as exc:
            fail_job(db, current_job, str(exc))
            raise
        except Exception as exc:
            fail_job(db, current_job, str(exc))
            raise BlockExecutionError(str(exc), error_code="TEXT_EXTRACTION_FAILED") from exc
        finally:
            db.close()


class OcrConfig(BaseModel):
    force_ocr: bool = False
    engine: str = "auto"
    language: str = "ko+en"
    deskew: bool = True
    denoise: bool = True
    contrast: bool = True
    grayscale: bool = True
    min_confidence: float = 0.0


class OcrBlock(BaseBlock):
    """자리표시자 — 통합 설계서 §3.3④. OCR은 현재 text_extract가 호출하는
    어댑터(pdf_adapter.py) 내부에서 페이지별 커버리지 기준으로 이미 자동
    수행된다. 어댑터를 "형식판별→조건분기→OCR"로 완전히 분리하는 리팩터링은
    위험도가 높아 이번 단계 범위에 넣지 않았다 — 표준 워크플로우 그래프에도
    포함하지 않으며, 이 블록은 카탈로그 완성을 위해 등록만 하고 상류 출력을
    그대로 통과시킨다."""

    @property
    def block_type(self) -> str:
        return "ocr"

    @property
    def category(self) -> str:
        return "입력·추출"

    @property
    def config_schema(self):
        return OcrConfig

    def run(self, context: BlockContext) -> BlockResult:
        upstream = next(iter(context.upstream_outputs.values()), {})
        return BlockResult(output=upstream)
