from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class DocumentUploadResponse(BaseModel):
    id: UUID
    filename: str
    status: str
    created_at: datetime


class DocumentResponse(BaseModel):
    id: UUID
    filename: str
    original_filename: str
    file_size: int
    mime_type: str
    status: str
    collection_id: UUID | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    error_message: str | None
    parsed_text: str | None
    ocr_used: bool
    summary: str | None
    summary_status: str
    tags: list[str] | None = None
    suggested_tags: list[str] | None = None
    metadata_status: str
    # DAG 실행기가 세팅하는, 이 문서를 현재(혹은 가장 최근) 구동 중인 WorkflowRun —
    # 프런트가 "전처리 단계" 패널을 ProcessingJob 대신 이 run의 실제 스텝별 진행
    # 상황(StepTimeline)으로 보여주는 데 쓴다(전처리 블록 13종 중 text_extract만
    # ProcessingJob을 기록해 그 외 블록 진행이 전혀 안 보이던 문제의 수정).
    active_run_id: UUID | None = None
    # 메타 정보 생성 설계서(2026-07-23) — title/language/category/page_count는
    # 문서 내용에서 자동 생성(Phase 1), author/organization/security_level/
    # source_system은 자동 생성 불가라 PATCH /documents/{id}/metadata로 사용자가
    # 직접 입력해야만 채워진다(Phase 2). 전부 None이 기본값.
    title: str | None = None
    language: str | None = None
    category: str | None = None
    page_count: int | None = None
    author: str | None = None
    organization: str | None = None
    security_level: str | None = None
    source_system: str | None = None
    # checksum/parser_version은 이미 Document.file_hash/pipeline_version으로
    # 존재하지만 응답에 노출된 적이 없어 UI에서 확인할 방법이 없었다 — 신규
    # 컬럼 없이 스펙 필드명으로만 노출.
    checksum: str | None = Field(default=None, validation_alias="file_hash")
    parser_version: dict | None = None
    # source_path/file_type은 각각 기존 minio_key/mime_type 컬럼과 동일한 값 —
    # 신규 컬럼 없이 메타 정보 생성.txt 스펙 필드명으로만 별칭 노출.
    source_path: str | None = Field(default=None, validation_alias="minio_key")
    file_type: str | None = Field(default=None, validation_alias="mime_type")
    # 문서 자체의 작성일(파일 내부 메타데이터에서 추출) — DB 저장 시각인 created_at과는
    # 별개 개념(메타 정보 생성.txt: created_at=작성일 vs ingestion_time=DB 저장 시각).
    document_created_at: datetime | None = None

    class Config:
        from_attributes = True


class DocumentProceedRequest(BaseModel):
    edited_text: str | None = Field(None, max_length=200_000)


class DocumentReprocessRequest(BaseModel):
    # 레거시 경로 — 기존 고정 파이프라인(continue_processing)으로 텍스트를
    # 통째로 교체해 재실행. start_block_type/start_block_instance_id와는
    # 상호배타.
    edited_text: str | None = Field(None, max_length=200_000)
    # 신규 경로 — 통합 설계서 §8: 이 블록부터 하류만 다시 실행하고 상류는
    # 이전 실행 결과를 그대로 재사용. 타입당 블록이 여럿인 커스텀 워크플로우는
    # start_block_instance_id로 모호함을 없앤다.
    start_block_type: str | None = Field(None, max_length=50)
    start_block_instance_id: UUID | None = None
    reason: str | None = Field(None, max_length=500)
    # {block_type: timeoutSeconds} — 이 재처리 run에만 적용되는 시간 제한 오버라이드.
    # 셀러리 hard time limit에 걸려 멈췄던 run을 더 긴 제한으로 재시도할 때 쓴다.
    timeout_overrides: dict[str, int] | None = None

    @model_validator(mode="after")
    def _check_timeout_overrides_bounds(self) -> "DocumentReprocessRequest":
        for block_type, seconds in (self.timeout_overrides or {}).items():
            if not (1 <= seconds <= 7200):
                raise ValueError(f"timeout_overrides['{block_type}']는 1~7200초 사이여야 합니다.")
        return self

    @model_validator(mode="after")
    def _check_exclusive_mode(self) -> "DocumentReprocessRequest":
        has_legacy = self.edited_text is not None
        has_partial = self.start_block_type is not None or self.start_block_instance_id is not None
        if has_legacy and has_partial:
            raise ValueError("edited_text와 start_block_type/start_block_instance_id는 함께 지정할 수 없습니다.")
        if not has_legacy and not has_partial:
            raise ValueError("edited_text 또는 start_block_type/start_block_instance_id 중 하나를 지정해야 합니다.")
        return self


class DocumentRunItem(BaseModel):
    id: UUID
    trigger: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    dictionary_version: int | None
    parent_run_id: UUID | None
    started_block_id: UUID | None
    impact: dict | None


class DocumentRunsResponse(BaseModel):
    document_id: str
    runs: list[DocumentRunItem]


class QualityReportResponse(BaseModel):
    id: UUID
    run_id: UUID
    overall_score: float | None
    scores: dict | None
    metrics: dict | None
    warnings: list | None
    warning_categories: list | None
    status: str
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    review_note: str | None
    created_at: datetime


class ReprocessImpactResponse(BaseModel):
    reason: str | None
    changeType: str
    affectedBlocks: list[str]
    affectedNodeCount: int
    affectedChunkCount: int
    fullReprocessingRequired: bool


class DocumentListResponse(BaseModel):
    total: int
    page: int
    limit: int
    items: list[DocumentResponse]


class DocumentChunkItem(BaseModel):
    chunk_index: int
    text: str


class DocumentContentResponse(BaseModel):
    document_id: str
    chunks: list[DocumentChunkItem]
    full_text: str
    chunk_count: int = 0


class DocumentDownloadResponse(BaseModel):
    url: str


class DocumentTableItem(BaseModel):
    page_number: int
    rows: list[list[str]]


class DocumentTablesResponse(BaseModel):
    document_id: str
    tables: list[DocumentTableItem]


class DocumentImageItem(BaseModel):
    page_number: int
    text: str
    url: str


class DocumentImagesResponse(BaseModel):
    document_id: str
    images: list[DocumentImageItem]


class DocumentChunkDetail(BaseModel):
    id: str
    chunk_index: int
    text: str
    page_number: int | None = None
    disabled: bool = False
    edited: bool = False
    hit_count: int = 0
    embedded: bool = True
    # 메타 정보 생성 설계서(2026-07-23) Phase 4 — token_count/chunk_type/
    # keywords/embedding_model/element_id/prev_chunk_id/next_chunk_id/
    # workflow_version/dictionary_version은 DocumentChunk(Postgres) 행에서만
    # 가져올 수 있어(Qdrant 페이로드에는 없음), Qdrant 히트 경로에서도
    # document_id+run_id로 별도 조회해 병합한다. total_chunks/char_count는
    # DB 컬럼이 아니라 응답 조립 시점에 계산(저장 비용 대비 이득이 낮음).
    token_count: int | None = None
    chunk_type: str | None = None
    keywords: list[str] | None = None
    embedding_model: str | None = None
    element_id: str | None = None
    prev_chunk_id: str | None = None
    next_chunk_id: str | None = None
    workflow_version: int | None = None
    dictionary_version: int | None = None
    total_chunks: int = 0
    char_count: int = 0
    # 트리 기반 청킹 전략(paragraph/section_aware/table_unit)에서만 채워짐
    # (다른 필드들과 동일한 제약).
    section_path: list[str] | None = None
    # heading_path는 section_path와 동일한 데이터를 스펙 필드명으로 노출한
    # 것(중복 컬럼 아님).
    heading_path: list[str] | None = None
    language: str | None = None
    source_file: str | None = None
    version: str | None = None
    # Chunk 계층형 Parent Retrieval — "상위 청크 보기" 토글용. parent 자체는
    # 이 목록에 별도 항목으로 나타나지 않는다.
    parent_chunk_text: str | None = None


class DocumentChunksResponse(BaseModel):
    document_id: str
    chunks: list[DocumentChunkDetail]


class ChunkUpdateRequest(BaseModel):
    text: str | None = Field(None, min_length=1, max_length=20_000)
    disabled: bool | None = None


class DocumentRevisionItem(BaseModel):
    id: UUID
    source: str
    created_by: UUID | None
    created_at: datetime
    text_length: int
    preview: str


class DocumentRevisionsResponse(BaseModel):
    document_id: str
    revisions: list[DocumentRevisionItem]


class DocumentTagsUpdateRequest(BaseModel):
    tags: list[str] = Field(..., max_length=20)


class DocumentTagSuggestionRequest(BaseModel):
    tag: str = Field(..., min_length=1, max_length=100)


class DocumentMetadataUpdateRequest(BaseModel):
    """author/organization/security_level/source_system은 문서 내용에서
    신뢰성 있게 자동 추출할 수 없어, 사용자가 직접 입력해야만 채워지는
    필드다. 전달된 필드만 갱신하고(부분 업데이트), None을 명시적으로
    보내면 값을 지운다. security_level만 자유 텍스트가 아니라 고정된
    3단계 값으로 검증한다."""
    author: str | None = Field(None, max_length=255)
    organization: str | None = Field(None, max_length=255)
    security_level: Literal["Public", "Internal", "Confidential"] | None = None
    source_system: str | None = Field(None, max_length=100)
    # 문서 자체의 작성일(파일 내부 core properties). docx/pdf는 자동
    # 추출되지만, hwp/hwpx는 파싱 라이브러리가 생성일 메타데이터를
    # 노출하지 않아 자동 불가 → 수동 입력.
    document_created_at: datetime | None = None

    model_config = {"extra": "forbid"}


class DocumentNodeItem(BaseModel):
    id: UUID
    node_type: str
    level: int | None
    sort_order: int
    parent_node_id: UUID | None
    page_number: int | None
    span_start: int | None
    span_end: int | None
    text: str | None
    style: dict | None
    user_corrected: bool
    correction_type: str | None = None
    correction_notes: str | None = None


class DocumentNodesResponse(BaseModel):
    document_id: str
    run_id: str | None
    nodes: list[DocumentNodeItem]


class NodeCorrectionRequest(BaseModel):
    level: int | None = None
    node_type: str | None = Field(None, max_length=50)
    # 왜 고쳤는지 남기는 선택적 감사 메모. correction_type(무엇을 고쳤는지)은
    # 서버가 level/node_type 중 실제로 값이 온 필드로부터 자동으로 채운다.
    correction_notes: str | None = Field(None, max_length=2000)
    # HWP/HWPX(extraction_layout 미제공) 및 Docling 경로(라이브러리 한계)
    # 문서의 노드는 style_name/font_size/font_name을 자동 생성할 수 없어
    # 수동 입력으로 채운다. node.style에 부분 병합(기존 값 유지, 전달된
    # 키만 덮어씀).
    style_name: str | None = Field(None, max_length=100)
    font_size: float | None = None
    font_name: str | None = Field(None, max_length=100)

    @model_validator(mode="after")
    def _check_at_least_one(self) -> "NodeCorrectionRequest":
        if self.level is None and self.node_type is None and self.style_name is None \
                and self.font_size is None and self.font_name is None:
            raise ValueError("level 또는 node_type 중 하나를 지정해야 합니다.")
        return self


# Document.elements(JSON 컬럼, Docling 경로에서만 채워짐)를 그대로 노출한다.
# DocumentNode처럼 정규화된 테이블이 아니라 딕셔너리 그대로라 스키마도 dict
# 그대로 통과시킨다(어댑터가 만드는 {id, page, type, bbox, content, metadata}
# 형태 — docling_adapter.py 참고).
class DocumentElementItem(BaseModel):
    id: str
    page: int | None = None
    type: str
    bbox: list[float] | tuple[float, float, float, float] | None = None
    content: dict
    metadata: dict
    span_start: int | None = None
    span_end: int | None = None
    user_corrected: bool = False
    correction_notes: str | None = None


class DocumentElementsResponse(BaseModel):
    document_id: str
    elements: list[DocumentElementItem]


class ElementCorrectionRequest(BaseModel):
    markdown: str = Field(..., max_length=50_000)
    correction_notes: str | None = Field(None, max_length=2000)
    # Docling 라이브러리가 폰트 정보를 노출하지 않아 style/font_size/font_name은
    # 이 요소들에 한해 자동 생성이 불가능하다. 전달된 필드만 el["metadata"]에
    # 병합(부분 업데이트).
    style: str | None = Field(None, max_length=100)
    font_size: float | None = None
    font_name: str | None = Field(None, max_length=100)


class CleaningChangeItem(BaseModel):
    id: UUID
    rule_id: UUID | None
    rule_key: str | None
    rule_name: str | None
    node_id: UUID | None
    before_sample: str | None
    after_sample: str | None
    change_count: int
    sample_matches: list[str] | None
    created_at: datetime


class CleaningChangesResponse(BaseModel):
    document_id: str
    run_id: str | None
    total_changes: int
    distinct_rule_count: int
    changes: list[CleaningChangeItem]


class DictionaryApplicationItem(BaseModel):
    id: UUID
    dictionary_type: str
    entry_id: UUID | None
    dictionary_version: int
    original_text: str
    normalized_text: str | None
    node_id: UUID | None
    chunk_id: UUID | None
    start_offset: int | None
    end_offset: int | None
    reverted: bool
    created_at: datetime


class DictionaryApplicationsResponse(BaseModel):
    document_id: str
    run_id: str | None
    pending_revert_count: int
    applications: list[DictionaryApplicationItem]


class PiiDetectionItem(BaseModel):
    id: UUID
    entity_type: str
    action: str
    masked_value: str | None
    page_number: int | None
    node_id: UUID | None
    start_offset: int | None
    end_offset: int | None
    confidence: float | None
    approved_by: UUID | None
    approved_at: datetime | None
    rejected: bool
    created_at: datetime


class PiiDetectionsResponse(BaseModel):
    document_id: str
    run_id: str | None
    detections: list[PiiDetectionItem]


class DocumentSummarySearchRequest(BaseModel):
    """메타 정보 생성 설계서(2026-07-23) Phase 5 — Summary Index 검색. 청크
    검색(`POST /search`)과 달리 collection_id 스코프/BM25/MMR 없이 문서 요약
    벡터만으로 top-k 문서를 찾는 가벼운 전용 엔드포인트."""
    query: str = Field(..., min_length=1, max_length=2000)
    limit: int = Field(10, gt=0, le=50)


class DocumentSummarySearchResultItem(BaseModel):
    document_id: str
    score: float
    summary: str


class DocumentSummarySearchResponse(BaseModel):
    items: list[DocumentSummarySearchResultItem]
