from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class DocumentChunk(Base):
    """The RAG chunk as a first-class DB row — 전처리 워크플로우 통합 설계서 §4.6.
    Promotes what previously lived only in the Qdrant point payload into the
    database, so the 청크 tab can list/edit/trace chunks without querying
    Qdrant, and so document deletion, chunk edits, and page/section
    attribution all have one source of truth. `id` is reused verbatim as the
    Qdrant point id at upsert time — see rag_store block (Phase 6)."""

    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    chunk_order: Mapped[int] = mapped_column(Integer)
    # Cleaned/normalized/masked text — what actually gets embedded.
    chunk_text: Mapped[str] = mapped_column(Text)
    # The corresponding raw parsed_text span, kept for diff/원문 대조.
    original_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_path: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_node_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    prev_chunk_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True
    )
    next_chunk_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True
    )
    span_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    span_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    edited: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    excluded_pii: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    workflow_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dictionary_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 메타 정보 생성 설계서(2026-07-23) — chunk_type은 source node의 node_type을
    # 그대로 복사(별도 분류 로직 없음), keywords는 문서 레벨 키워드와의 substring
    # 매칭 결과(추가 LLM 호출 없음), embedding_model은 RagStoreBlock이 이미
    # 계산한 값을 DB에도 스탬프, element_id는 DocumentNode.element_id를 청크까지
    # 전파한 연결 컬럼.
    chunk_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    keywords: Mapped[list | None] = mapped_column(JSON, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    element_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 메타 정보 생성.txt 3절 후속(2026-07-24) — 스펙의 heading_path(제목 경로)는
    # 위 section_path와 동일한 데이터다(chunk_strategies.py의 조상 헤딩 텍스트
    # 스택 — DocumentNode id가 아니라 이미 헤딩 텍스트 배열). 신규 컬럼을 또
    # 만들면 완전한 중복이라 만들지 않고, 응답 스키마에서 스펙 필드명으로만
    # 노출한다. char_count/language/source_file은 이미 로드된 값을 그대로
    # 복사, version은 임베딩 차원수(사용자 결정, 2026-07-24)를 문자열로 스탬프.
    char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    source_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Chunk 계층형 Parent Retrieval(메타 정보 생성.txt 3절, Phase 9) — child가
    # 속한 parent 청크. parent 행 자신은 항상 None. chunk_tier로 parent/child
    # 구분(임베딩 대상은 child만 — RagStoreBlock이 parent를 건너뜀).
    parent_chunk_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True
    )
    chunk_tier: Mapped[str] = mapped_column(String(10), default="child", server_default="child")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
