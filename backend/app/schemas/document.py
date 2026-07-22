from datetime import datetime
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


class DocumentNodesResponse(BaseModel):
    document_id: str
    run_id: str | None
    nodes: list[DocumentNodeItem]


class NodeCorrectionRequest(BaseModel):
    level: int | None = None
    node_type: str | None = Field(None, max_length=50)

    @model_validator(mode="after")
    def _check_at_least_one(self) -> "NodeCorrectionRequest":
        if self.level is None and self.node_type is None:
            raise ValueError("level 또는 node_type 중 하나를 지정해야 합니다.")
        return self


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
