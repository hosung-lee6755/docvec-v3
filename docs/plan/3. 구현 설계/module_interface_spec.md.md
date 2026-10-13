# module_interface_spec.md
# DocVec - 모듈 인터페이스 설계 (FastAPI + Celery + Services)

## 1. 문서 목적

본 문서는 DocVec 플랫폼의 모듈 간 인터페이스를 정의한다.
- API 엔드포인트 계약 (요청/응답 스키마)
- Celery 작업 인터페이스
- 서비스 계층 인터페이스
- ORM 모델 스키마

---

## 2. API 엔드포인트 모듈 (api/v1/endpoints/)

### documents.py
- POST /upload-zip: 여러 파일을 ZIP으로 일괄 업로드
- GET /documents: 문서 목록
- DELETE /documents/{id}: 문서 삭제

### collections.py
- GET /collections: 컬렉션 목록
- POST /collections: 새 컬렉션 생성
- PATCH /collections/{id}: 컬렉션 임베딩 모델 변경 → reembed 작업 트리거

### golden_queries.py (신규)
- POST /collections/{id}/golden-queries: 골든 쿼리 생성
- GET /collections/{id}/golden-queries: 골든 쿼리 목록
- POST /collections/{id}/golden-eval-runs: 평가 실행 → Precision/Recall 계산

### chat.py
- POST /chat/{conversation_id}/message: 의도 분류 및 의도별 라우팅 (문서 검색 / 표 데이터 / 요약)

---

## 3. Celery 작업 모듈 (pipeline/tasks/)

### tasks.ingest_document
- 입력: file_path, collection_id
- 출력: Document ORM 객체
- 다음: tasks.process_document

### tasks.process_document
- 입력: document_id
- 구현: HWP/HWPX 실페이지 분할 (LibreOffice 미리보기 PDF 기반)
- 다음: tasks.generate_chunks

### tasks.generate_chunks
- 입력: document_id
- 구현: 청크 생성, 청크별 히트 카운트 추적
- 다음: tasks.embed_and_index

### tasks.reembed_collection (신규)
- 입력: collection_id, new_embedding_model
- 구현: 모든 문서 재임베딩, Qdrant 벡터 업데이트
- 상태: RUNNING → COMPLETED/FAILED

---

## 4. 서비스 계층 (services/)

### EmbeddingProvider
- embed(texts: list[str]) -> list[list[float]]

### QdrantService
- search(collection_name, vector, limit) -> hits
- upsert_points(collection_name, points) → 동일 ID 기존 벡터 대체

### BM25Service
- rank(documents, query, top_k) → ranked

### LLMProvider
- generate(prompt, system_prompt, model) → response
- 지원: OpenAI, Anthropic (BYOK), Ollama

### SearchService & ChatService
- perform_search(query, collection_id, intent: “CHUNK_SEARCH” | “TABLE_QUERY” | “SUMMARY_LOOKUP”) → intent별 라우팅

---

## 5. 설계 원칙

- 각 모듈은 단일 책임
- 입출력은 명시적 스키마(Pydantic) 사용
- 상향 의존 금지 (서비스는 엔드포인트를 모름)

## 4.1 InputDocument
역할:
- 입력 파일을 시스템 내부 처리 단위로 표현

포함 필드 예:
- document_id
- file_name
- file_type
- mime_type
- source_path
- file_hash
- ingested_at

---

## 4.2 RawParsedDocument
역할:
- parser가 생성한 raw extraction 결과

포함 필드 예:
- raw_pages
- raw_text_blocks
- raw_lines
- raw_spans
- raw_words
- raw_images
- raw_drawings
- raw_table_candidates
- diagnostics

---

## 4.3 StructuredDocument
역할:
- 구조 복원 결과

포함 필드 예:
- pages
- blocks
- sections
- tables
- figures
- warnings
- diagnostics
- provenance

---

## 4.4 ReviewBundle
역할:
- review json + markdown + diagnostics + refinement template를 묶은 검토 패키지

---

## 4.5 RefinedDocument
역할:
- refinement delta가 적용된 구조 문서

---

## 4.6 CanonicalDocument
역할:
- semantic normalization이 완료된 최종 표준 문서

---

## 4.7 ExportBundle
역할:
- 외부 저장/전달용 산출물 집합

---

## 5. 모듈별 인터페이스 설계

## 5.1 DocumentIngestModule

### 역할
- 입력 파일을 식별하고 `InputDocument`를 생성

### 입력
- `source_path: str | Path`
- optional upload metadata

### 출력
- `InputDocument`

### public interface 예시
```python
class DocumentIngestModule:
    def build(self, source_path: str) -> InputDocument:
        ...
```

### 의존 모듈
- common.config
- utils.file_utils
- models.input_models

### 금지 의존
- parser
- structurer
- review
- refinement

### 불변 조건
- document_id는 생성 즉시 부여되어야 한다
- file_hash는 항상 계산 가능해야 한다
- file_type / mime_type은 비어 있으면 안 된다

---

## 5.2 AdapterResolutionModule

### 역할
- 입력 문서에 맞는 adapter 선택

### 입력
- `InputDocument`

### 출력
- `BaseAdapter`

### public interface 예시
```python
class AdapterResolutionModule:
    def resolve(self, input_doc: InputDocument) -> BaseAdapter:
        ...
```

### 의존 모듈
- adapters.base_adapter
- adapters.pdf_adapter
- adapters.hwp_adapter
- adapters.hwpx_adapter
- adapters.docx_adapter

### 금지 의존
- parser internals
- structurer
- review
- refinement

### 불변 조건
- 선택된 adapter는 반드시 `supports()`를 통과해야 한다
- adapter가 없으면 명시적 예외를 발생시켜야 한다

---

## 5.3 NativeParseModule

### 역할
- adapter를 통해 raw extraction을 수행

### 입력
- `InputDocument`
- `BaseAdapter`

### 출력
- `RawParsedDocument`

### public interface 예시
```python
class NativeParseModule:
    def parse(self, input_doc: InputDocument, adapter: BaseAdapter) -> RawParsedDocument:
        ...
```

### 내부 하위 모듈
- `pdf_native_parser`
- `ocr_assist`
- `visual_region_detector`
- `table_candidate_detector`
- `raw_document_builder`

### 의존 모듈
- adapters
- models.raw_models
- utils
- common.enums
- common.errors

### 금지 의존
- structurer
- review
- refinement
- export

### 불변 조건
- raw 결과는 포맷 의존성이 남아도 된다
- semantic normalization을 수행하면 안 된다
- section/block/table 확정을 하면 안 된다
- diagnostics는 가능한 한 많이 남겨야 한다

---

## 5.4 StructureReconstructionModule

### 역할
- RawParsedDocument를 StructuredDocument로 변환

### 입력
- `RawParsedDocument`

### 출력
- `StructuredDocument`

### public interface 예시
```python
class StructureReconstructionModule:
    def reconstruct(self, raw_doc: RawParsedDocument) -> StructuredDocument:
        ...
```

### 내부 하위 모듈
- `block_segmenter`
- `block_classifier`
- `reading_order_resolver`
- `section_tree_builder`
- `table_reconstructor`
- `figure_linker`
- `header_footer_detector`
- `provenance_builder`

### 의존 모듈
- parser outputs
- models.structured_models
- utils.bbox_utils
- common.enums

### 금지 의존
- review
- refinement
- normalization
- export

### 불변 조건
- stable block_id / table_id / section_id가 생성되어야 한다
- OCR source와 native source를 구분해야 한다
- provenance와 warnings를 유지해야 한다
- semantic record/fact를 직접 만들지 않는다

---

## 5.5 ReviewBundleGenerationModule

### 역할
- StructuredDocument를 사용자 검토용 ReviewBundle로 변환

### 입력
- `StructuredDocument`

### 출력
- `ReviewBundle`

### public interface 예시
```python
class ReviewBundleGenerationModule:
    def build(self, structured_doc: StructuredDocument) -> ReviewBundle:
        ...
```

### 내부 하위 모듈
- `review_json_builder`
- `review_markdown_renderer`
- `diagnostics_summarizer`
- `refinement_template_builder`

### 의존 모듈
- models.review_models
- models.structured_models
- common.enums
- utils.text_utils

### 금지 의존
- refinement apply
- normalization
- chunking
- export 저장 로직

### 불변 조건
- review markdown의 id는 structured_doc의 id와 동일해야 한다
- refinement template는 빈 상태로 항상 생성 가능해야 한다
- review는 표현 계층이지 수정 계층이 아니다

---

## 5.6 RefinementApplicationModule

### 역할
- StructuredDocument에 refinement를 적용하여 RefinedDocument 생성

### 입력
- `StructuredDocument`
- `RefinementSet`

### 출력
- `RefinedDocument`

### public interface 예시
```python
class RefinementApplicationModule:
    def apply(self, structured_doc: StructuredDocument, refinements: RefinementSet) -> RefinedDocument:
        ...
```

### 내부 하위 모듈
- `refinement_validator`
- `refinement_operations`
- `target_resolver`
- `refinement_history`

### 의존 모듈
- models.refinement_models
- models.structured_models
- common.errors
- common.enums

### 금지 의존
- export
- review rendering
- normalization
- chunking 직접 수행

### 불변 조건
- refinement는 non-destructive여야 한다
- 잘못된 target_id는 검증 단계에서 차단해야 한다
- before/after 또는 audit trail이 남아야 한다

---

## 5.7 PostRefinementRecomputeModule

### 역할
- refinement 이후 영향 받은 구조와 산출물을 부분 재계산

### 입력
- `RefinedDocument`

### 출력
- `RefinedDocument` (recompute 반영 버전)

### public interface 예시
```python
class PostRefinementRecomputeModule:
    def recompute(self, refined_doc: RefinedDocument) -> RefinedDocument:
        ...
```

### 내부 하위 모듈
- `recompute_planner`
- `section_recompute`
- `table_recompute`
- `chunk_recompute`
- `quality_recompute`

### 의존 모듈
- refinement outputs
- structurer logic 일부 재사용 가능
- normalization / quality / chunking 하위 빌더 일부 재사용 가능

### 금지 의존
- parser
- ingest
- adapter resolution

### 불변 조건
- 전체 재계산 대신 영향 범위 우선
- section/table/chunk/quality 영향 그래프가 유지되어야 함
- recompute 결과는 deterministic해야 한다

---

## 5.8 SemanticNormalizationModule

### 역할
- RefinedDocument를 CanonicalDocument로 정규화

### 입력
- `RefinedDocument`

### 출력
- `CanonicalDocument`

### public interface 예시
```python
class SemanticNormalizationModule:
    def normalize(self, refined_doc: RefinedDocument) -> CanonicalDocument:
        ...
```

### 내부 하위 모듈
- `text_normalizer`
- `numeric_parser`
- `unit_normalizer`
- `date_normalizer`
- `header_path_builder`
- `record_builder`
- `fact_builder`
- `entity_extractor`

### 의존 모듈
- models.canonical_models
- models.refinement_models
- common.enums
- utils.text_utils

### 금지 의존
- review
- exporter
- parser internals

### 불변 조건
- 원문 text와 normalized_text를 분리해야 한다
- record/fact/entity는 canonical 계층에서 생성한다
- 구조 판단을 새로 하지 않는다

---

## 5.9 QualityEvaluationModule

### 역할
- 문서/객체 수준 품질 점수와 warnings 계산

### 입력
- `StructuredDocument` 또는 `CanonicalDocument`
- diagnostics
- refinement 결과(optional)

### 출력
- 품질 주석이 반영된 문서 객체 또는 `QualityResult`

### public interface 예시
```python
class QualityEvaluationModule:
    def evaluate(self, canonical_doc: CanonicalDocument) -> CanonicalDocument:
        ...
```

### 내부 하위 모듈
- `document_quality`
- `page_quality`
- `block_quality`
- `table_quality`
- `figure_quality`
- `warning_builder`

### 의존 모듈
- models.quality_models
- models.structured_models
- models.canonical_models

### 금지 의존
- review rendering
- export writing
- parser

### 불변 조건
- quality는 explainable해야 한다
- score와 warning code가 함께 생성되어야 한다

---

## 5.10 ChunkGenerationModule

### 역할
- CanonicalDocument에서 chunk / record / fact 출력 생성

### 입력
- `CanonicalDocument`

### 출력
- `ChunkSet` 또는 `CanonicalDocument`에 포함된 chunk/record/fact

### public interface 예시
```python
class ChunkGenerationModule:
    def generate(self, canonical_doc: CanonicalDocument) -> CanonicalDocument:
        ...
```

### 내부 하위 모듈
- `section_chunker`
- `paragraph_chunker`
- `table_chunker`
- `figure_chunker`
- `fact_chunker`
- `chunk_metadata_builder`

### 의존 모듈
- models.chunk_models
- models.canonical_models

### 금지 의존
- parser
- structurer
- review
- refinement

### 불변 조건
- chunk는 canonical 결과에만 의존해야 한다
- target metadata와 provenance refs를 포함해야 한다

---

## 5.11 ExportModule

### 역할
- 최종 산출물을 파일/저장소에 기록

### 입력
- `StructuredDocument`(optional)
- `ReviewBundle`(optional)
- `CanonicalDocument`
- `ExportOptions`

### 출력
- `ExportBundle`

### public interface 예시
```python
class ExportModule:
    def export(
        self,
        canonical_doc: CanonicalDocument,
        review_bundle: ReviewBundle | None = None,
        structured_doc: StructuredDocument | None = None,
    ) -> ExportBundle:
        ...
```

### 내부 하위 모듈
- `export_bundle_writer`
- `canonical_json_writer`
- `raw_json_writer`
- `review_bundle_writer`
- `chunk_jsonl_writer`
- `record_jsonl_writer`
- `fact_jsonl_writer`
- `diagnostics_writer`

### 의존 모듈
- models.export_models
- models.review_models
- models.canonical_models
- repositories.export_repository

### 금지 의존
- refinement apply
- parser logic
- structurer logic
- normalization logic

### 불변 조건
- exporter는 표현 생성이 아니라 저장/출력만 담당한다
- review markdown 생성 규칙은 review 모듈에 있어야 한다
- canonical writer는 schema를 임의로 바꾸면 안 된다

---

## 6. 서비스 계층 인터페이스

서비스 계층은 여러 엔진 모듈을 orchestration 한다.

## 6.1 DocumentStructuringService
```python
class DocumentStructuringService:
    def process_document(self, source_path: str) -> CanonicalDocument:
        ...
```

책임:
- ingest → adapter → parse → structure → refine(optional) → normalize → quality → chunk → export 흐름 orchestration

## 6.2 ReviewService
```python
class ReviewService:
    def build_review_bundle(self, structured_doc: StructuredDocument) -> ReviewBundle:
        ...
```

## 6.3 RefinementService
```python
class RefinementService:
    def apply_refinement(self, structured_doc: StructuredDocument, refinements: RefinementSet) -> RefinedDocument:
        ...
```

## 6.4 ExportService
```python
class ExportService:
    def export_bundle(self, canonical_doc: CanonicalDocument, review_bundle: ReviewBundle | None = None) -> ExportBundle:
        ...
```

---

## 7. 파이프라인 계층 인터페이스

## 7.1 StructuringPipeline
```python
class StructuringPipeline:
    def run(self, source_path: str) -> StructuredDocument:
        ...
```

## 7.2 ReviewPipeline
```python
class ReviewPipeline:
    def run(self, structured_doc: StructuredDocument) -> ReviewBundle:
        ...
```

## 7.3 RefinementPipeline
```python
class RefinementPipeline:
    def run(self, structured_doc: StructuredDocument, refinements: RefinementSet) -> CanonicalDocument:
        ...
```

## 7.4 FullPipeline
```python
class FullPipeline:
    def run(self, source_path: str, refinements: RefinementSet | None = None) -> ExportBundle:
        ...
```

---

## 8. 모듈 간 호출 순서 계약

### 8.1 review-required 모드
```text
Ingest
→ Adapter Resolution
→ Native Parse
→ Structure Reconstruction
→ Review Bundle Generation
→ 사용자 refinement 입력 대기
→ Refinement Apply
→ Recompute
→ Normalize
→ Quality
→ Chunk
→ Export
```

### 8.2 auto-pass 모드
```text
Ingest
→ Adapter Resolution
→ Native Parse
→ Structure Reconstruction
→ Normalize
→ Quality
→ Chunk
→ Export
```

---

## 9. 예외 / 오류 인터페이스 원칙

모듈은 가능한 한 typed exception을 사용한다.

예:
- `UnsupportedFileTypeError`
- `AdapterResolutionError`
- `ParseFailureError`
- `RefinementValidationError`
- `RecomputeError`
- `ExportError`

원칙:
- 예외는 common.errors에 정의
- 내부 예외는 가능하면 wrapping
- warning과 exception을 구분

---

## 10. 금지 설계 패턴

다음 패턴은 금지한다.

1. parser가 직접 chunk를 만드는 것
2. structurer가 review markdown을 렌더링하는 것
3. exporter가 canonical schema를 조립하는 것
4. refinement가 export 파일을 직접 수정하는 것
5. review 모듈이 refinement 적용을 수행하는 것
6. dict 기반 임시 데이터가 모듈 경계를 넘나드는 것

---

## 11. 모듈 인터페이스 설계 결론

이 문서의 목적은 “모듈 디렉터리 이름”을 정의하는 것이 아니다.  
진짜 목적은 각 모듈이 무엇을 받아 무엇을 내보내고, 어디까지 책임지며, 무엇을 하면 안 되는지를 고정하는 것이다.

이 문서가 완료되어야 이후 단계가 가능하다.

- 클래스 상세 설계 확장
- 실제 interface skeleton 코드 생성
- 구현 테스트 전략 수립

즉, 본 문서는 구현 직전 단계의 핵심 설계 문서다.
