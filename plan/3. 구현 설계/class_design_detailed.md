# class_design_detailed.md
# DocVec - ORM 모델 & 서비스 클래스 상세 설계

## 1. ORM 모델 (db/models/)

### Document
```python
class Document:
    id: UUID
    filename: str
    original_filename: str
    collection_id: UUID
    status: str  # “INDEXED”, “PROCESSING”, “FAILED”
    minio_key: str
    parsed_structure: dict  # JSON: pages, tables, images
    page_count: int
    tables: dict  # JSON: 구조화된 표 데이터
    summary: str | None
    images: list[dict] | None
    pages: list[dict] | None  # 페이지별 텍스트
    page_map: dict  # 편집 후 페이지 매핑
    ocr_used: bool
```

### Collection
```python
class Collection:
    id: UUID
    name: str
    embedding_model: str
    reembed_status: str | None  # “PENDING”, “RUNNING”, “COMPLETED”, “FAILED”
    reembed_progress: str | None  # “10/50”
```

### GoldenQuery & GoldenEvalRun (신규)
```python
class GoldenQuery:
    id: UUID
    collection_id: UUID
    query: str
    expected_document_ids: list[str]  # JSON
    created_by: UUID

class GoldenEvalRun:
    id: UUID
    collection_id: UUID
    top_k: int
    mean_precision: float  # 0.0-1.0
    mean_recall: float  # 0.0-1.0
    results: list[dict]  # JSON: 쿼리별 precision/recall
```

---

## 2. 서비스 클래스

### EmbeddingProvider
```python
class EmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        # 모델별 구현: OpenAI, Anthropic, Ollama, HuggingFace
        pass
```

### QdrantService
```python
class QdrantService:
    def search(self, collection: str, vector: list[float], limit: int) -> list[dict]:
        # Qdrant 검색, payload에서 document_id 반환
        pass
    
    def upsert_points(self, collection: str, points: list[PointStruct]) -> None:
        # 동일 ID인 경우 벡터만 업데이트 (재임베딩)
        pass
```

### GoldenQueryEvaluationService (신규)
```python
class GoldenQueryEvaluation:
    def evaluate(self, golden_queries: list[GoldenQuery], collection_id: str, top_k: int) -> GoldenEvalRun:
        # 각 쿼리를 임베드 → Qdrant 검색 → precision/recall 계산
        # Document 레벨 평가 (청크 히트 → 문서로 디뎁)
        pass
```

### ChatService (의도 라우팅)
```python
class ChatService:
    def _classify_intent(self, provider, query: str) -> str:
        # LLM으로 “CHUNK_SEARCH” | “TABLE_QUERY” | “SUMMARY_LOOKUP” 분류
        pass
    
    def _retrieve_table_chunks(self, query, collection_id) -> list[dict]:
        # Document.tables JSON에서 BM25 검색
        pass
    
    def _retrieve_summary_chunks(self, query, collection_id) -> list[dict]:
        # Document.summary에서 검색
        pass
```

---

## 3. Celery 작업 클래스 (pipeline/tasks/)

### ReembedTask (신규)
```python
@celery_app.task(queue=”low”)
def reembed_collection(collection_id: str, embedding_model: str) -> dict:
    # 1. Collection.reembed_status = “RUNNING”
    # 2. 모든 INDEXED Document 순회
    # 3. 청크 재임베드 → Qdrant upsert (동일 ID, 새 벡터)
    # 4. reembed_status = “COMPLETED” 또는 “FAILED”
    return {“status”: “COMPLETED”}
```

---

## 4. 설계 원칙

- ORM 모델 = 순수 데이터 (SQL 스키마 반영)
- 서비스 = 비즈니스 로직 (DI 패턴)
- 스키마 = Pydantic 요청/응답 모델
```python
class InputDocument:
    document_id: str
    source: SourceMetadata
    options: dict[str, object]
```

---

## 3.3 RawWord

```python
class RawWord:
    word_id: str
    text: str
    bbox: tuple[float, float, float, float]
    page_num: int
    source: str
```

---

## 3.4 RawSpan

```python
class RawSpan:
    span_id: str
    text: str
    bbox: tuple[float, float, float, float]
    page_num: int
    font_name: str | None
    font_size: float | None
    font_weight: str | None
    is_italic: bool | None
    source: str
```

---

## 3.5 RawLine

```python
class RawLine:
    line_id: str
    text: str
    bbox: tuple[float, float, float, float]
    page_num: int
    span_ids: list[str]
    source: str
```

---

## 3.6 RawTextBlock

```python
class RawTextBlock:
    raw_block_id: str
    text: str
    bbox: tuple[float, float, float, float]
    page_num: int
    line_ids: list[str]
    source: str
```

---

## 3.7 RawImage / RawDrawing / RawTableCandidate

```python
class RawImage:
    image_id: str
    page_num: int
    bbox: tuple[float, float, float, float]
    image_path: str | None

class RawDrawing:
    drawing_id: str
    page_num: int
    bbox: tuple[float, float, float, float]
    drawing_type: str | None

class RawTableCandidate:
    candidate_id: str
    page_num: int
    bbox: tuple[float, float, float, float]
    detection_source: str
    score: float | None
```

---

## 3.8 RawPage

```python
class RawPage:
    raw_page_id: str
    page_num: int
    width: float
    height: float
    rotation: int
    raw_text_block_ids: list[str]
    raw_line_ids: list[str]
    raw_span_ids: list[str]
    raw_word_ids: list[str]
    raw_image_ids: list[str]
    raw_drawing_ids: list[str]
    raw_table_candidate_ids: list[str]
    diagnostics: dict[str, object]
```

---

## 3.9 RawParsedDocument

```python
class RawParsedDocument:
    document_id: str
    source: SourceMetadata
    raw_pages: list[RawPage]
    raw_text_blocks: list[RawTextBlock]
    raw_lines: list[RawLine]
    raw_spans: list[RawSpan]
    raw_words: list[RawWord]
    raw_images: list[RawImage]
    raw_drawings: list[RawDrawing]
    raw_table_candidates: list[RawTableCandidate]
    diagnostics: dict[str, object]
    warnings: list[str]
```

---

## 3.10 BlockStyle

```python
class BlockStyle:
    font_size: float | None
    font_weight: str | None
    alignment: str | None
    indent: float | None
    line_spacing: float | None
```

---

## 3.11 BlockConfidence

```python
class BlockConfidence:
    type_confidence: float | None
    role_confidence: float | None
```

---

## 3.12 Block

```python
class Block:
    block_id: str
    page_id: str
    type: str
    role: str
    bbox: tuple[float, float, float, float]
    text: str
    normalized_text: str | None
    style: BlockStyle | None
    reading_order: int | None
    section_id: str | None
    source: str
    confidence: BlockConfidence | None
    review_hint: str | None
```

---

## 3.13 Section

```python
class Section:
    section_id: str
    title: str
    normalized_title: str | None
    level: int
    parent_section_id: str | None
    child_section_ids: list[str]
    block_ids: list[str]
    page_range: tuple[int, int] | None
    section_path: list[str]
```

---

## 3.14 Cell

```python
class Cell:
    cell_id: str
    table_id: str
    row: int
    col: int
    rowspan: int
    colspan: int
    bbox: tuple[float, float, float, float] | None
    text: str
    normalized_text: str | None
    cell_type: str
    source: str
    confidence: float | None
    parsed_value: int | float | str | None
    unit: str | None
```

---

## 3.15 TableQuality

```python
class TableQuality:
    score: float | None
    cell_fill_rate: float | None
    header_validated: bool | None
    numeric_parse_success_rate: float | None
```

---

## 3.16 Table

```python
class Table:
    table_id: str
    page_id: str
    section_id: str | None
    title: str | None
    bbox: tuple[float, float, float, float] | None
    table_type: str
    structure: dict[str, object]
    cells: list[Cell]
    expanded_grid: list[list[str]]
    header_rows: list[int]
    header_paths: list[list[str]]
    record_ids: list[str]
    notes: list[str]
    source_priority: str
    quality: TableQuality | None
```

---

## 3.17 FigureQuality

```python
class FigureQuality:
    caption_link_confidence: float | None
    ocr_text_confidence: float | None
```

---

## 3.18 Figure

```python
class Figure:
    figure_id: str
    page_id: str
    section_id: str | None
    bbox: tuple[float, float, float, float] | None
    figure_kind: str
    caption: str | None
    caption_block_id: str | None
    ocr_text: str | None
    image_path: str | None
    source: str
    quality: FigureQuality | None
```

---

## 3.19 ProvenanceEntry

```python
class ProvenanceEntry:
    object_id: str
    source: str
    page_num: int | None
    bbox: tuple[float, float, float, float] | None
    upstream_object_ids: list[str]
    decision: str | None
```

---

## 3.20 WarningEntry

```python
class WarningEntry:
    code: str
    severity: str
    scope: str
    target_id: str | None
    message: str
```

---

## 3.21 StructuredDocument

```python
class StructuredDocument:
    document_id: str
    source: SourceMetadata
    meta: dict[str, object]
    pages: list[dict[str, object]]
    blocks: list[Block]
    sections: list[Section]
    tables: list[Table]
    figures: list[Figure]
    warnings: list[WarningEntry]
    diagnostics: dict[str, object]
    provenance: list[ProvenanceEntry]
```

---

## 3.22 ReviewSummary

```python
class ReviewSummary:
    block_count: int
    section_count: int
    table_count: int
    figure_count: int
    warning_count: int
    ocr_applied_pages: int
```

---

## 3.23 ReviewBundle

```python
class ReviewBundle:
    document_id: str
    review_json: dict[str, object]
    review_markdown: str
    diagnostics_summary: dict[str, object]
    refinement_template: dict[str, object]
    summary: ReviewSummary | None
```

---

## 3.24 RefinementOperation

```python
class RefinementOperation:
    op_id: str
    type: str
    target_id: str
    payload: dict[str, object]
    author: str
    created_at: str
```

---

## 3.25 RefinementSet

```python
class RefinementSet:
    document_id: str
    refinements: list[RefinementOperation]
```

---

## 3.26 RefinementHistoryEntry

```python
class RefinementHistoryEntry:
    op_id: str
    target_id: str
    type: str
    before: dict[str, object] | None
    after: dict[str, object] | None
    author: str
    created_at: str
```

---

## 3.27 RefinedDocument

```python
class RefinedDocument:
    document_id: str
    base_structured_document_id: str
    structured_document: StructuredDocument
    applied_refinements: list[RefinementOperation]
    refinement_history: list[RefinementHistoryEntry]
    recompute_targets: dict[str, object]
```

---

## 3.28 Record

```python
class Record:
    record_id: str
    table_id: str
    row_index: int
    stub_value: str | None
    values: dict[str, object]
    confidence: float | None
```

---

## 3.29 Fact

```python
class Fact:
    fact_id: str
    subject: str
    predicate: str
    object: object
    unit: str | None
    qualifiers: dict[str, object]
    confidence: float | None
```

---

## 3.30 Entity

```python
class Entity:
    entity_id: str
    entity_type: str
    value: str
    normalized_value: str | None
    source_object_ids: list[str]
```

---

## 3.31 ChunkMetadata

```python
class ChunkMetadata:
    page_num: int | None
    page_range: tuple[int, int] | None
    section_path: list[str]
    block_ids: list[str]
    table_id: str | None
    figure_id: str | None
    source_types: list[str]
    confidence: float | None
    semantic_tags: list[str]
    provenance_refs: list[str]
```

---

## 3.32 Chunk

```python
class Chunk:
    chunk_id: str
    document_id: str
    chunk_type: str
    text: str
    metadata: ChunkMetadata
```

---

## 3.33 DocumentQuality

```python
class DocumentQuality:
    structure_score: float | None
    table_quality_score: float | None
    text_integrity_score: float | None
    ocr_dependency_ratio: float | None
    grade: str | None
```

---

## 3.34 CanonicalDocument

```python
class CanonicalDocument:
    document_id: str
    source: SourceMetadata
    meta: dict[str, object]
    pages: list[dict[str, object]]
    blocks: list[Block]
    sections: list[Section]
    tables: list[Table]
    figures: list[Figure]
    records: list[Record]
    facts: list[Fact]
    entities: list[Entity]
    chunks: list[Chunk]
    quality: DocumentQuality | None
    warnings: list[WarningEntry]
    diagnostics: dict[str, object]
    provenance: list[ProvenanceEntry]
```

---

## 3.35 ExportArtifact

```python
class ExportArtifact:
    artifact_type: str
    path: str
```

---

## 3.36 ExportBundle

```python
class ExportBundle:
    document_id: str
    artifacts: list[ExportArtifact]
    output_dir: str
```

---

## 4. 엔진 클래스 설계

## 4.1 DocumentIngestModule

```python
class DocumentIngestModule:
    def __init__(self, mime_detector, id_generator, hash_service) -> None:
        ...

    def build(self, source_path: str, options: dict[str, object] | None = None) -> InputDocument:
        ...
```

---

## 4.2 AdapterResolutionModule

```python
class AdapterResolutionModule:
    def __init__(self, adapters: list[object]) -> None:
        ...

    def resolve(self, input_doc: InputDocument):
        ...
```

---

## 4.3 NativeParseModule

```python
class NativeParseModule:
    def __init__(self, parser_facade, raw_document_builder) -> None:
        ...

    def parse(self, input_doc: InputDocument, adapter) -> RawParsedDocument:
        ...
```

---

## 4.4 StructureReconstructionModule

```python
class StructureReconstructionModule:
    def __init__(
        self,
        block_segmenter,
        block_classifier,
        reading_order_resolver,
        section_tree_builder,
        table_reconstructor,
        figure_linker,
        header_footer_detector,
        provenance_builder,
    ) -> None:
        ...

    def reconstruct(self, raw_doc: RawParsedDocument) -> StructuredDocument:
        ...
```

---

## 4.5 ReviewBundleGenerationModule

```python
class ReviewBundleGenerationModule:
    def __init__(
        self,
        review_json_builder,
        review_markdown_renderer,
        diagnostics_summarizer,
        refinement_template_builder,
    ) -> None:
        ...

    def build(self, structured_doc: StructuredDocument) -> ReviewBundle:
        ...
```

---

## 4.6 RefinementApplicationModule

```python
class RefinementApplicationModule:
    def __init__(
        self,
        refinement_validator,
        target_resolver,
        refinement_operations,
        refinement_history_builder,
    ) -> None:
        ...

    def apply(self, structured_doc: StructuredDocument, refinements: RefinementSet) -> RefinedDocument:
        ...
```

---

## 4.7 PostRefinementRecomputeModule

```python
class PostRefinementRecomputeModule:
    def __init__(
        self,
        recompute_planner,
        section_recompute,
        table_recompute,
        chunk_recompute,
        quality_recompute,
    ) -> None:
        ...

    def recompute(self, refined_doc: RefinedDocument) -> RefinedDocument:
        ...
```

---

## 4.8 SemanticNormalizationModule

```python
class SemanticNormalizationModule:
    def __init__(
        self,
        text_normalizer,
        numeric_parser,
        unit_normalizer,
        date_normalizer,
        header_path_builder,
        record_builder,
        fact_builder,
        entity_extractor,
    ) -> None:
        ...

    def normalize(self, refined_doc: RefinedDocument) -> CanonicalDocument:
        ...
```

---

## 4.9 QualityEvaluationModule

```python
class QualityEvaluationModule:
    def __init__(
        self,
        document_quality_evaluator,
        page_quality_evaluator,
        block_quality_evaluator,
        table_quality_evaluator,
        figure_quality_evaluator,
        warning_builder,
    ) -> None:
        ...

    def evaluate(self, canonical_doc: CanonicalDocument) -> CanonicalDocument:
        ...
```

---

## 4.10 ChunkGenerationModule

```python
class ChunkGenerationModule:
    def __init__(
        self,
        section_chunker,
        paragraph_chunker,
        table_chunker,
        figure_chunker,
        fact_chunker,
        chunk_metadata_builder,
    ) -> None:
        ...

    def generate(self, canonical_doc: CanonicalDocument) -> CanonicalDocument:
        ...
```

---

## 4.11 ExportModule

```python
class ExportModule:
    def __init__(
        self,
        export_bundle_writer,
        canonical_json_writer,
        raw_json_writer,
        review_bundle_writer,
        chunk_jsonl_writer,
        record_jsonl_writer,
        fact_jsonl_writer,
        diagnostics_writer,
    ) -> None:
        ...

    def export(
        self,
        canonical_doc: CanonicalDocument,
        review_bundle: ReviewBundle | None = None,
        structured_doc: StructuredDocument | None = None,
    ) -> ExportBundle:
        ...
```

---

## 5. 서비스 클래스 설계

## 5.1 DocumentStructuringService

```python
class DocumentStructuringService:
    def __init__(
        self,
        ingest_module: DocumentIngestModule,
        adapter_resolution_module: AdapterResolutionModule,
        parse_module: NativeParseModule,
        structure_module: StructureReconstructionModule,
        review_module: ReviewBundleGenerationModule,
        refinement_module: RefinementApplicationModule,
        recompute_module: PostRefinementRecomputeModule,
        normalization_module: SemanticNormalizationModule,
        quality_module: QualityEvaluationModule,
        chunk_module: ChunkGenerationModule,
        export_module: ExportModule,
    ) -> None:
        ...

    def process_document(
        self,
        source_path: str,
        refinements: RefinementSet | None = None,
        build_review_bundle: bool = False,
        export: bool = False,
    ) -> ExportBundle | CanonicalDocument | ReviewBundle:
        ...
```

---

## 5.2 ReviewService

```python
class ReviewService:
    def __init__(self, review_module: ReviewBundleGenerationModule, review_repository) -> None:
        ...

    def build_review_bundle(self, structured_doc: StructuredDocument) -> ReviewBundle:
        ...

    def save_review_bundle(self, review_bundle: ReviewBundle) -> None:
        ...
```

---

## 5.3 RefinementService

```python
class RefinementService:
    def __init__(
        self,
        refinement_module: RefinementApplicationModule,
        recompute_module: PostRefinementRecomputeModule,
        refinement_repository,
    ) -> None:
        ...

    def apply_refinement(
        self,
        structured_doc: StructuredDocument,
        refinements: RefinementSet,
    ) -> RefinedDocument:
        ...
```

---

## 5.4 ExportService

```python
class ExportService:
    def __init__(self, export_module: ExportModule, export_repository) -> None:
        ...

    def export_bundle(
        self,
        canonical_doc: CanonicalDocument,
        review_bundle: ReviewBundle | None = None,
        structured_doc: StructuredDocument | None = None,
    ) -> ExportBundle:
        ...
```

---

## 6. 파이프라인 클래스 설계

## 6.1 StructuringPipeline

```python
class StructuringPipeline:
    def __init__(
        self,
        ingest_module: DocumentIngestModule,
        adapter_resolution_module: AdapterResolutionModule,
        parse_module: NativeParseModule,
        structure_module: StructureReconstructionModule,
    ) -> None:
        ...

    def run(self, source_path: str) -> StructuredDocument:
        ...
```

---

## 6.2 ReviewPipeline

```python
class ReviewPipeline:
    def __init__(self, review_module: ReviewBundleGenerationModule) -> None:
        ...

    def run(self, structured_doc: StructuredDocument) -> ReviewBundle:
        ...
```

---

## 6.3 RefinementPipeline

```python
class RefinementPipeline:
    def __init__(
        self,
        refinement_module: RefinementApplicationModule,
        recompute_module: PostRefinementRecomputeModule,
        normalization_module: SemanticNormalizationModule,
        quality_module: QualityEvaluationModule,
        chunk_module: ChunkGenerationModule,
    ) -> None:
        ...

    def run(self, structured_doc: StructuredDocument, refinements: RefinementSet) -> CanonicalDocument:
        ...
```

---

## 6.4 FullPipeline

```python
class FullPipeline:
    def __init__(
        self,
        structuring_pipeline: StructuringPipeline,
        review_pipeline: ReviewPipeline,
        refinement_pipeline: RefinementPipeline,
        export_service: ExportService,
    ) -> None:
        ...

    def run(
        self,
        source_path: str,
        refinements: RefinementSet | None = None,
        build_review_bundle: bool = False,
        export: bool = False,
    ) -> ExportBundle | CanonicalDocument | ReviewBundle:
        ...
```

---

## 7. 저장소 인터페이스 설계

## 7.1 ReviewRepository

```python
class ReviewRepository:
    def save(self, review_bundle: ReviewBundle) -> None:
        ...
    def load(self, document_id: str) -> ReviewBundle | None:
        ...
```

## 7.2 RefinementRepository

```python
class RefinementRepository:
    def save(self, refinements: RefinementSet) -> None:
        ...
    def load(self, document_id: str) -> RefinementSet | None:
        ...
    def save_history(self, document_id: str, history: list[RefinementHistoryEntry]) -> None:
        ...
```

## 7.3 ExportRepository

```python
class ExportRepository:
    def ensure_output_dir(self, document_id: str) -> str:
        ...
    def write_text(self, path: str, content: str) -> None:
        ...
    def write_json(self, path: str, payload: dict[str, object]) -> None:
        ...
```

---

## 8. 의존성 주입 구조

권장 조립 구조는 다음과 같다.

### 8.1 하위 빌더/헬퍼 생성
- text_normalizer
- numeric_parser
- block_segmenter
- section_tree_builder
- table_reconstructor
- review_markdown_renderer
- warning_builder
- etc.

### 8.2 엔진 생성
- NativeParseModule(...)
- StructureReconstructionModule(...)
- ReviewBundleGenerationModule(...)
- RefinementApplicationModule(...)
- PostRefinementRecomputeModule(...)
- SemanticNormalizationModule(...)
- QualityEvaluationModule(...)
- ChunkGenerationModule(...)
- ExportModule(...)

### 8.3 서비스 생성
- DocumentStructuringService(...)
- ReviewService(...)
- RefinementService(...)
- ExportService(...)

### 8.4 파이프라인 생성
- StructuringPipeline(...)
- ReviewPipeline(...)
- RefinementPipeline(...)
- FullPipeline(...)

---

## 9. 예외 반환 원칙

### 9.1 상태 객체 반환 우선
정상 흐름에서는 항상 typed object 반환

### 9.2 예외는 typed exception
- UnsupportedFileTypeError
- ParseFailureError
- RefinementValidationError
- RecomputeError
- ExportError

### 9.3 warning과 exception 구분
- warning: 계속 진행 가능
- exception: 단계 진행 불가

---

## 10. 클래스 설계 결론

이 문서는 단순히 클래스 이름만 나열하는 문서가 아니다.  
핵심은 아래 세 가지를 고정하는 것이다.

1. 상태 객체 필드
2. 엔진/서비스/파이프라인의 public method
3. 생성자 기반 의존성 주입 구조

이 문서가 완료되어야 이후 실제 코드 skeleton 작성 시 책임이 섞이지 않는다.
