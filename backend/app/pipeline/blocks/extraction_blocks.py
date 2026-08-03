"""입력·추출 블록: 파일검증/형식판별/텍스트추출/OCR — 통합 설계서 §3.3①~④.

These replace the front end of the retired fixed pipeline (parse_document,
app/pipeline/tasks/pipeline.py). They call the exact same adapter/helper
functions parse_document used to call, just from a block's run() instead of
a Celery task body, so extraction behavior is unchanged from before the
cutover — only the orchestration moved.
"""
import logging
import re
import tempfile
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from app.pipeline.blocks.base import BaseBlock, BlockContext, BlockExecutionError, BlockResult

logger = logging.getLogger(__name__)

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
    # Exclude detected running headers/footers from parsed_text (chunking/
    # citations/RAG never see repeated page furniture).
    exclude_headers_footers: bool = True
    # PDF 전용(선 없는 정렬 기반 표 검출). 표가 거의 없는 문서군에서는 매 페이지
    # 추가 클러스터링 비용을 아끼려고 끌 수 있게 노출한다. 끄면 이 표들은 그냥
    # 일반 본문 텍스트로 남는다.
    detect_implicit_tables: bool = True
    # Document.extraction_layout(줄 단위 폰트/스타일 신호) 계산 자체를 끈다.
    # 끄면 structure_analyze는 항상 정규식-only 폴백 경로로만 동작한다
    # (extraction_layout이 없는 문서와 동일하게 처리).
    extract_font_signals: bool = True
    # "docling"이면 PDF에 한해 DoclingAdapter 사용(DOCX/HWP/HWPX는 이 값과
    # 무관하게 항상 기존 어댑터).
    engine: str = "legacy"


# Repeated-position clustering thresholds — a line counts as a running
# header/footer only if it recurs, verbatim, near the same margin on most
# pages; a one-off top/bottom line (e.g. a section's last sentence wrapping
# to the page bottom) must NOT be caught by this.
_HEADER_ZONE_PCT = 0.1
_FOOTER_ZONE_PCT = 0.85
_MIN_REPEAT_CONSISTENCY = 0.6
_FOOTNOTE_MARKER_RE = re.compile(r"^\s*(\d+[\)\.]|\*|†|‡)\s*\S")


def _detect_header_footer_footnote_lines(parsed) -> set[str]:
    """Cross-page repeated-position clustering over metadata["line_layout"]
    (문서 파싱 고도화 Phase 1). Tags each line entry's "role" key in place
    ("header" | "footer" | "footnote" | None) for Phase 2's structure
    analysis to consume later, and returns the set of stripped line texts
    that qualify as running headers/footers (candidates for exclusion from
    parsed_text — footnotes are page-specific, not excluded, just tagged).
    A no-op (returns empty set, tags nothing) when the adapter didn't supply
    line_layout — i.e. HWP/HWPX, or any format without bbox+page geometry."""
    line_layout = parsed.metadata.get("line_layout") or []
    if not line_layout or parsed.page_count < 2:
        return set()

    page_heights = {p.page_number: p.height for p in parsed.pages}
    occurrences: dict[str, set[int]] = {}
    for line in line_layout:
        line["role"] = None
        bbox, page_num = line.get("bbox"), line.get("page_number")
        height = page_heights.get(page_num)
        if not bbox or not height:
            continue
        _, top, _, bottom = bbox
        y_mid_pct = ((top + bottom) / 2) / height
        if y_mid_pct < _HEADER_ZONE_PCT or y_mid_pct > _FOOTER_ZONE_PCT:
            text = line["text"].strip()
            if text:
                occurrences.setdefault(text, set()).add(page_num)

    threshold = max(2, int(parsed.page_count * _MIN_REPEAT_CONSISTENCY))
    repeated = {text for text, pages in occurrences.items() if len(pages) >= threshold}

    for line in line_layout:
        bbox, page_num = line.get("bbox"), line.get("page_number")
        height = page_heights.get(page_num)
        if not bbox or not height:
            continue
        _, top, _, bottom = bbox
        y_mid_pct = ((top + bottom) / 2) / height
        text = line["text"].strip()
        if text in repeated:
            line["role"] = "header" if y_mid_pct < _HEADER_ZONE_PCT else "footer"
        elif y_mid_pct > _FOOTER_ZONE_PCT and _FOOTNOTE_MARKER_RE.match(line["text"]):
            line["role"] = "footnote"

    return repeated


def _strip_excluded_lines(text: str, excluded: set[str]) -> str:
    if not excluded:
        return text
    return "\n".join(line for line in text.split("\n") if line.strip() not in excluded)


def _assemble_full_text(pages, excluded_lines: set[str]) -> tuple[str, dict[str, tuple[int, int]]]:
    """`doc.parsed_text`가 될 최종 문자열과, 그 문자열 안에서 각 `element_id`가
    차지하는 (span_start, span_end) 오프셋을 함께 계산한다. 반환된 문자열은
    반드시 `"\\n\\n".join(...)`으로 조립되므로, structure_analyze가 elements
    경로에서 줄 단위 fuzzy 매칭 없이 정확한 span으로 DocumentNode를 만들 수
    있다. NUL 제거는 각 조각 단위로 먼저 해서 오프셋이 최종 문자열과
    어긋나지 않게 한다."""
    full_text_parts: list[str] = []
    element_spans: dict[str, tuple[int, int]] = {}
    cursor = 0
    for page in pages:
        for block in page.text_blocks:
            block_text = _strip_nul_bytes(_strip_excluded_lines(block.text, excluded_lines))
            if not block_text.strip():
                continue
            if full_text_parts:
                cursor += 2  # "\n\n" separator inserted by the join below
            start = cursor
            cursor += len(block_text)
            if block.element_id:
                element_spans[block.element_id] = (start, cursor)
            full_text_parts.append(block_text)
    return "\n\n".join(full_text_parts), element_spans


_HANGUL_RE = re.compile(r"[가-힣]")
_LATIN_RE = re.compile(r"[a-zA-Z]")


def _detect_language(text: str) -> str | None:
    """한글/영문 문자 비율 휴리스틱으로 문서 언어를 추정한다(메타 정보 생성
    설계서, 2026-07-23 Phase 1) — 정밀 언어 감지 라이브러리 없이 두 문자
    집합 중 한쪽이 최소 2배 우세할 때만 "ko"/"en"으로 판정. 텍스트가 비었거나
    두 문자 집합이 비슷한 비중이면(예: 코드/숫자 위주 문서) None."""
    hangul = len(_HANGUL_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    if hangul == 0 and latin == 0:
        return None
    if hangul >= latin * 2:
        return "ko"
    if latin >= hangul * 2:
        return "en"
    return None


def _match_image_paths(elements: list[dict], image_records: list[dict]) -> None:
    """PICTURE 타입 element의 metadata.image_path를 Document.images(페이지
    번호로 색인된 storage_key)와 best-effort로 매치한다(메타 정보 생성
    설계서, 2026-07-23 Phase 3) — 어댑터의 extract() 시점에는 이미지 인식이
    아직 끝나지 않아 image_path를 채울 수 없으므로(항상 None), 인식이 끝난
    여기서 채운다. 같은 페이지에 이미지가 여러 개면 등장 순서대로 하나씩
    소진 — 완벽한 1:1 매칭 보장은 없다(문서화된 한계)."""
    by_page: dict[int | None, list[str]] = {}
    for record in image_records:
        by_page.setdefault(record.get("page_number"), []).append(record.get("storage_key"))
    for el in elements:
        if el.get("type") != "picture":
            continue
        candidates = by_page.get(el.get("page"))
        if candidates:
            el.setdefault("metadata", {})["image_path"] = candidates.pop(0)


def _strip_nul_bytes(value):
    """Postgres text/json 컬럼은 NUL(\\x00) 문자를 저장할 수 없다(문자열 리터럴이
    C 스타일 NUL-terminated이기 때문) — 스캔 품질이 낮거나 손상된 PDF 등에서
    추출된 텍스트에 섞여 들어오면 db.commit()이 통째로 실패한다(988페이지 문서
    재처리 중 실제로 발생, "This Session's transaction has been rolled back...
    A string literal cannot contain NUL (0x00) characters"). 저장 직전 한 곳에서
    재귀적으로 제거해 어떤 어댑터가 만들어낸 값이든 안전하게 만든다."""
    if isinstance(value, str):
        return value.replace("\x00", "") if "\x00" in value else value
    if isinstance(value, list):
        return [_strip_nul_bytes(v) for v in value]
    if isinstance(value, dict):
        return {k: _strip_nul_bytes(v) for k, v in value.items()}
    return value


class TextExtractBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "text_extract"

    @property
    def block_version(self) -> str:
        # Bumped: detect_implicit_tables/extract_font_signals are now real
        # config toggles forwarded to the adapter, not just always-on — the
        # same document can produce different output depending on config, so
        # a cached result keyed only by config_hash must still be safe (it is,
        # since config_hash already includes these new fields), but the
        # *shape* of a pre-upgrade cached result (no toggles considered) must
        # not replay as if it reflects the current config.
        #
        # 1.5.0: docx_adapter now walks the document body in true order
        # (paragraphs interleaved with tables) instead of emitting all
        # paragraph text before all table text — a cached pre-1.5.0 docx
        # result has content in the wrong order relative to the source and
        # must not be reused (문서 파싱 고도화 회고, 2026-07-23).
        #
        # 1.6.0: pdf_adapter's list-marker-vs-table heuristic no longer
        # requires column 2 to be long prose, and matches font-substituted
        # bullet glyphs / bare unpunctuated numbers as markers too — found by
        # reprocessing a real 988-page document and seeing numbered section
        # indexes with short labels ("01. 색상") still misdetected as tables.
        #
        # 1.7.0: new engine="docling" config option (PDF only) routes through
        # DoclingAdapter, which additionally populates Document.elements — a
        # cached pre-1.7.0 result never has elements set, so it must not be
        # replayed as if it reflects the current config (Docling 도입
        # 설계서, 2026-07-23 Phase 1).
        #
        # 1.8.0: doc.elements[*] now carries span_start/span_end computed
        # deterministically from the same offset math that builds full_text —
        # a cached pre-1.8.0 result's elements have no spans, so
        # structure_analyze (Phase 2) could not build DocumentNodes from them
        # correctly and must not treat such a cached result as current
        # (Docling 도입 설계서, 2026-07-23 Phase 2).
        #
        # 1.9.0: now also stamps Document.page_count/language — a cached
        # pre-1.9.0 result never set these, so it must not be replayed as if
        # it reflects the current config (메타 정보 생성 설계서, 2026-07-23
        # Phase 1).
        #
        # 1.10.0: doc.elements[*] now also carries order/is_caption/
        # table_rows/table_cols/image_path/style(always None) — a cached
        # pre-1.10.0 result's elements lack these keys (메타 정보 생성
        # 설계서, 2026-07-23 Phase 3).
        #
        # 1.11.0: docx_adapter/pdf_adapter now render table text via the
        # shared rows_to_markdown() (escaped cell newlines/pipes + header
        # separator row) instead of a naive " | ".join — a cached
        # pre-1.11.0 result's table text_blocks can have broken row
        # structure whenever a cell contains an embedded newline (9항목
        # 펀치리스트 #6, 2026-07-24).
        #
        # 1.12.0: docx_adapter/pdf_adapter now also extract
        # Document.document_created_at from file core properties/info dict —
        # a cached pre-1.12.0 result never set this (메타 정보 생성.txt 1절,
        # 2026-07-24).
        #
        # 1.13.0: docx_adapter/pdf_adapter's line_layout entries now also
        # carry font_name — a cached pre-1.13.0 result's line_layout lacks
        # this key, so structure_analyze's DocumentNode.style would be
        # missing font_name even though the document was actually re-parsed
        # (메타 정보 생성.txt 2절, 2026-07-24).
        #
        # 1.14.0: docling_adapter now sets pipeline_options.generate_picture_images
        # and passes real PNG bytes into RawImageRegion — previously image_bytes
        # was always None for docling-engine PDFs, so _recognize_document_images
        # silently skipped every picture and Document.images stayed empty even
        # though 구조/요소 tabs correctly showed picture elements (그림 탭 표출
        # 버그, 2026-07-25). A cached pre-1.14.0 docling result has no images and
        # must be reprocessed to pick this up.
        #
        # 1.15.0: docling_adapter now escalates low-text-coverage pages to the
        # same BYOK cloud-VLM-OCR path pdf_adapter.py already had (only when a
        # project/user has a registered OpenAI/Anthropic key — otherwise a
        # no-op, same as before). Docling's own VLM pipeline preset
        # (granite-docling-258M) was evaluated directly against a real
        # infographic-heavy Korean PDF and rejected — it produced repetition-
        # loop garbage and its model card doesn't support Korean at all
        # (Docling VLM 통합 조사, 2026-07-29). A cached pre-1.15.0 docling
        # result never attempted this escalation even when a key is now
        # registered, so it must be reprocessed to pick this up.
        return "1.15.0"

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
                    adapter = get_adapter(tmp_path, doc.mime_type or "", engine=cfg.engine)
                except UnsupportedFileTypeError as exc:
                    raise BlockExecutionError(
                        str(exc), error_code="FILE_UNSUPPORTED", permanent=True
                    ) from exc
                vision_options = _resolve_vision_credentials(db, doc)
                adapter_options = {
                    **vision_options,
                    "detect_implicit_tables": cfg.detect_implicit_tables,
                    "extract_font_signals": cfg.extract_font_signals,
                }
                parsed = adapter.extract(tmp_path, adapter_options)
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
                    logger.exception("image recognition failed", extra={"document_id": str(doc.id)})
                    image_records = []

            excluded_lines = (
                _detect_header_footer_footnote_lines(parsed)
                if cfg.exclude_headers_footers else set()
            )
            full_text, element_spans = _assemble_full_text(parsed.pages, excluded_lines)
            table_count = sum(len(page.table_candidates) for page in parsed.pages)
            complete_job(
                db, current_job,
                f"텍스트 {len(full_text):,}자, 표 {table_count}개, 그림 {len(image_records)}개 추출"
                f" ({len(parsed.pages)}페이지)",
            )

            doc.parsed_text = full_text
            doc.page_map = _build_page_map(parsed.pages)
            doc.extraction_layout = _strip_nul_bytes(parsed.metadata.get("line_layout")) or None
            # Docling 도입 설계서(2026-07-23) Phase 1 — Docling 경로에서만 채워지는
            # 통합 요소 JSON. legacy 어댑터(HWP/HWPX, engine=="legacy")는 이 키를
            # 채우지 않으므로 None으로 남고, structure_analyze(Phase 2)는 그 경우
            # 기존 정규식 경로로 폴백한다.
            raw_elements = _strip_nul_bytes(parsed.metadata.get("elements"))
            if raw_elements:
                # Phase 2 — 위에서 계산한 element_spans로 각 element에
                # span_start/span_end를 붙인다. 매칭되는 span이 없는 요소
                # (예: text_blocks에 항목을 남기지 않는 picture)는 None으로
                # 남아 structure_analyze가 본문 span 없이 처리한다.
                for el in raw_elements:
                    span = element_spans.get(el.get("id"))
                    el["span_start"], el["span_end"] = span if span else (None, None)
                # 메타 정보 생성 설계서(2026-07-23) Phase 3 — image_path는
                # image_records가 방금 계산된 지금에서야 채울 수 있다.
                _match_image_paths(raw_elements, image_records)
            doc.elements = raw_elements or None
            doc.ocr_used = bool(parsed.metadata.get("ocr_used", False))
            doc.ocr_page_confidence = [
                {
                    "page_number": page.page_number,
                    "confidence": page.ocr_confidence,
                    "word_count": page.ocr_word_count,
                }
                for page in parsed.pages
                if page.ocr_confidence is not None
            ] or None
            doc.tables = _strip_nul_bytes([
                {
                    "page_number": page.page_number, "rows": table.rows,
                    "id": table.id, "confidence": table.confidence,
                    "detected_as": table.detected_as,
                }
                for page in parsed.pages
                for table in page.table_candidates
            ]) or None
            doc.images = _strip_nul_bytes(image_records) or None
            # 메타 정보 생성 설계서(2026-07-23) Phase 1 — 문서 내용에서 자동
            # 유도되는 Document 레벨 필드. title은 구조분석(structure_blocks.py)
            # 이후가 더 정확해 여기서는 채우지 않는다.
            doc.page_count = len(parsed.pages)
            doc.language = _detect_language(full_text)
            # 메타 정보 생성.txt 1절 document_created_at — docx/pdf 어댑터만
            # 채울 수 있다(hwp/hwpx는 None). None이면 절대 덮어쓰지 않아
            # hwp/hwpx 문서에 사용자가 PATCH /documents/{id}/metadata로
            # 직접 입력해둔 값이 재처리 시 지워지지 않게 한다.
            extracted_created_at = parsed.metadata.get("document_created_at")
            if extracted_created_at is not None:
                doc.document_created_at = extracted_created_at
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
