from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Index,
    UniqueConstraint,
    event,
    text,
    String,
    Integer,
    Boolean,
    Enum as SQLEnum,
    ForeignKey,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.db.types import UTCDateTime

from app.db.base import Base


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        # v3 마일스톤 7: 계보마다 현재 버전은 하나, 버전 번호는 겹치지 않는다
        Index("uq_documents_lineage_current", "lineage_id", unique=True,
              postgresql_where=text("lifecycle_state = 'current'")),
        UniqueConstraint("lineage_id", "version_number", name="uq_documents_lineage_version"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    filename: Mapped[str] = mapped_column(String(512))
    original_filename: Mapped[str] = mapped_column(String(512))
    file_size: Mapped[int] = mapped_column(Integer)
    mime_type: Mapped[str] = mapped_column(String(100))
    file_hash: Mapped[str] = mapped_column(String(128), index=True)
    minio_key: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(
        SQLEnum(
            "QUEUED",
            "INGESTING",
            "PARSING",
            "STRUCTURING",
            "REVIEW_PENDING",
            "REFINING",
            "NORMALIZING",
            "CHUNKING",
            "EMBEDDING",
            "UPLOADING",
            "INDEXED",
            "FAILED",
            "CANCELLED",
            # Added for the workflow-driven preprocessing pipeline (전처리
            # 워크플로우 통합 설계서 §7.2 status mapping) — VALIDATING covers
            # file_validate/format_detect, MASKING covers pii_detect,
            # WAITING_REVIEW is the quality_check review gate.
            "VALIDATING",
            "MASKING",
            "WAITING_REVIEW",
            # An AUTO_ANALYSIS run's block types aren't in _STATUS_FOR_BLOCK_TYPE
            # (workflow.py), so without this the document kept showing the stale
            # "INDEXED" label for the run's whole duration.
            "ANALYZING",
            name="document_status",
        ),
        default="QUEUED",
        index=True,
    )
    collection_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collections.id"), nullable=True
    )
    created_by: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # List of [end_offset, page_number] pairs marking cumulative character offsets
    # into parsed_text where each source page ends — see _build_page_map in
    # app/pipeline/tasks/process.py. Used to attribute chunks to a page number for
    # RAG citations; may drift after a manual REVIEW_PENDING text edit.
    page_map: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Per-visual-line font/position signals from the adapter (문서 파싱 고도화
    # Phase 1) — a side artifact alongside parsed_text, not a replacement for
    # it. Shape: [{page_number, text, bbox, font_size, is_bold, is_italic,
    # style_name, role}], role is "header"/"footer"/"footnote"/None (see
    # extraction_blocks.py::_detect_header_footer_footnote_lines). None for
    # documents with no per-line font signal source (HWP/HWPX) or parsed
    # before this field existed — structure_analyze falls back to its
    # regex-only path in that case.
    extraction_layout: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Per-page OCR quality (문서 파싱 고도화 Phase 3), populated only for pages
    # that actually went through Tesseract (not cloud VLM, which exposes no
    # word-level confidence, and not natively-extracted pages). Shape:
    # [{page_number, confidence (0-1 mean word confidence), word_count}].
    # None when ocr_used is False or no page's OCR produced confidence data.
    # Consumed by quality_check in place of format_detect's page-level
    # approximation.
    ocr_page_confidence: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Docling 도입 설계서(2026-07-23) Phase 1 — DoclingAdapter(engine="docling",
    # PDF 전용)로 처리된 문서에서만 채워지는 통합 요소 JSON. 형태:
    # [{id, page, type, bbox, content: {text, markdown},
    # metadata: {section_path, is_header, is_footer, confidence, detected_as,
    # user_corrected, correction_notes}}]. legacy 엔진(기존 pdf/docx/hwp/hwpx
    # 어댑터)로 처리된 문서는 None — GET/PATCH /documents/{id}/elements와
    # structure_analyze(Phase 2)가 None이면 각각 표 탭/정규식 폴백 경로로
    # 동작한다.
    elements: Mapped[list | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Plain string, not SQLEnum: PENDING -> GENERATING -> DONE | FAILED, set by
    # app/pipeline/tasks/summary.py::generate_summary, triggered automatically
    # once a document reaches INDEXED (see process.py::continue_processing).
    summary_status: Mapped[str] = mapped_column(
        String(20), default="PENDING", server_default="PENDING"
    )
    # Structured table data extracted alongside parsed_text, independent of the
    # flattened "[표 N]" text blocks embedded in parsed_text/chunks — see
    # RawTableCandidate. Shape: [{"page_number": int, "rows": list[list[str]]}].
    # Exposed via GET /documents/{id}/tables and the "표 데이터" tab.
    tables: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Embedded figure/image records extracted at parse time — see
    # _recognize_document_images in app/pipeline/tasks/process.py.
    # Shape: [{"page_number": int, "storage_key": str, "text": str}], where
    # storage_key points into the artifacts MinIO bucket and text holds the
    # OCR/VLM-recognized content (empty string when recognition found nothing).
    images: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # User-managed labels (list[str]) copied into each chunk's Qdrant payload at
    # index time so retrieval can filter by tag — see continue_processing.
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # LLM-proposed labels (list[str]) awaiting user accept/dismiss — never
    # written to Qdrant directly; a suggestion only reaches the chunk payload
    # once promoted into `tags` via POST /{id}/tags/accept-suggestion. See
    # app/pipeline/tasks/metadata.py::extract_metadata.
    suggested_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Plain string, not SQLEnum: PENDING -> GENERATING -> DONE | FAILED, set by
    # app/pipeline/tasks/metadata.py::extract_metadata, triggered automatically
    # alongside generate_summary once a document reaches INDEXED.
    metadata_status: Mapped[str] = mapped_column(
        String(20), default="PENDING", server_default="PENDING"
    )
    # The workflow run currently driving this document's status, or the most
    # recent one once the run finishes — see 전처리 워크플로우 통합 설계서 §7.2.
    # SET NULL (not CASCADE): deleting a run must not delete the document.
    active_run_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True
    )
    # Copy of the latest QualityReport.status for this document, kept here so
    # the document list can filter/sort by quality without a join.
    quality_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Snapshot of {block_type: block_version, embedding_model, ...} from the
    # last successful run — 설계서 §16.2 처리 버전 예시.
    pipeline_version: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 메타 정보 생성 설계서(2026-07-23) Document 레벨 자동 생성 필드 — 문서
    # 내용에서 유도되며 structure_analyze/extraction_blocks/output_blocks가
    # 채운다. None이면 아직 처리되지 않았거나(구버전 재처리 전) 추출 실패.
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 원본 파일이 스스로 가진 제목 속성(PDF info dict/DOCX core.title) — text_extract 가 기록하고
    # structure_analyze 의 제목 판정(title_resolver)이 후보로 쓴다. 신뢰할 수 없는 값은 판정 쪽에서 거른다.
    source_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 사용자가 직접 고친 자동 생성 필드 이름(title/language/category). 여기 있는 필드는 재처리가
    # 덮어쓰지 않는다 — PATCH /documents/{id}/metadata 의 reset_fields 로만 해제된다.
    user_edited_fields: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 문서 내용에서 신뢰성 있게 자동 추출할 수 없어, 자동 생성 로직 없이
    # PATCH /documents/{id}/metadata를 통해 사용자가 직접 입력해야만 채워지는 필드.
    # 기본값은 항상 None.
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    organization: Mapped[str | None] = mapped_column(String(255), nullable=True)
    security_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_system: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 메타 정보 생성.txt 1절 — 문서 자체의 작성일(파일 내부 core properties에서
    # 추출). 위 created_at은 DB row 생성/업로드 시각(ingestion_time 개념)이라
    # 별개다. docx/pdf는 extraction_blocks.py가 자동 채우고, hwp/hwpx는 자동
    # 불가해 PATCH /documents/{id}/metadata로 사용자가 직접 입력해야 한다.
    document_created_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # v3 마일스톤 7 문서 버전과 수명주기(services/document_lifecycle.py).
    # lineage_id: 같은 문서의 모든 버전이 공유한다. 첫 버전은 자기 id다(아래 before_insert).
    # lifecycle_state: pending(처리 중인 새 버전) → current → superseded(이전 버전) / archived(보관).
    # 검색과 답변에는 current이면서 만료일이 지나지 않은 문서만 쓴다.
    lineage_id: Mapped[str] = mapped_column(UUID(as_uuid=True), index=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    lifecycle_state: Mapped[str] = mapped_column(String(20), default="current", server_default="current")
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


@event.listens_for(Document, "before_insert")
def _default_lineage(_mapper, _connection, target: Document) -> None:
    """첫 버전은 자기 id를 계보 id로 쓴다. 새 버전은 만드는 쪽이 이전 버전의 계보 id를 넣는다."""
    if target.id is None:
        target.id = uuid4()
    if target.lineage_id is None:
        target.lineage_id = target.id
