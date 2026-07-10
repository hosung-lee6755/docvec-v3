# file_structure_design.md
# Document Structuring Solution - 파일 단위 설계

## 1. 문서 목적

본 문서는 최종 폴더 구조를 실제 구현 가능한 **파일 단위 구조**로 구체화한다.  
디렉터리 수준 설계만으로는 코드 작성 시 책임이 다시 섞일 가능성이 높기 때문에,  
각 디렉터리 안에 어떤 파일이 존재해야 하는지, 각 파일이 어떤 책임을 갖는지,  
어떤 파일이 어떤 파일을 참조할 수 있는지를 명시적으로 정의한다.

본 문서는 다음을 포함한다.

- 최종 프로젝트 파일 트리
- 각 파일의 역할
- 파일 간 의존 방향 원칙
- 공통 모델 배치 원칙
- 파이프라인 / 서비스 / 저장 계층 분리 원칙

본 문서는 구현 순서를 다루지 않는다.  
최종 구현 구조의 정답 상태를 정의한다.

---

## 2. 실제 파일 구조 (DocVec 플랫폼)

```text
project_root/
├─ backend/
│  ├─ app/
│  │  ├─ api/v1/
│  │  │  ├─ endpoints/
│  │  │  │  ├─ auth.py
│  │  │  │  ├─ documents.py
│  │  │  │  ├─ collections.py
│  │  │  │  ├─ projects.py
│  │  │  │  ├─ search.py
│  │  │  │  ├─ chat.py
│  │  │  │  ├─ golden_queries.py (신규: 골든 쿼리 평가)
│  │  │  │  ├─ stats.py
│  │  │  │  └─ users.py
│  │  │  ├─ deps.py
│  │  │  ├─ permissions.py
│  │  │  └─ router.py
│  │  ├─ pipeline/
│  │  │  ├─ adapters/
│  │  │  │  ├─ base.py
│  │  │  │  ├─ pdf_adapter.py
│  │  │  │  ├─ docx_adapter.py
│  │  │  │  ├─ hwp_adapter.py
│  │  │  │  └─ hwpx_adapter.py
│  │  │  ├─ tasks/
│  │  │  │  ├─ ingest.py
│  │  │  │  ├─ process.py (HWP/HWPX 실페이지 분할 포함)
│  │  │  │  ├─ chunks.py
│  │  │  │  ├─ summary.py
│  │  │  │  ├─ chat.py (의도 분류 라우팅 포함)
│  │  │  │  ├─ reembed.py (신규: 컬렉션 재임베딩)
│  │  │  │  ├─ pipeline.py
│  │  │  │  └─ __init__.py
│  │  │  ├─ celery_app.py
│  │  │  └─ job_tracker.py
│  │  ├─ db/
│  │  │  ├─ models/
│  │  │  │  ├─ user.py
│  │  │  │  ├─ document.py
│  │  │  │  ├─ collection.py
│  │  │  │  ├─ chat_conversation.py
│  │  │  │  ├─ chat_message.py
│  │  │  │  ├─ project.py
│  │  │  │  ├─ project_api_key.py
│  │  │  │  ├─ golden_query.py (신규)
│  │  │  │  ├─ golden_eval_run.py (신규)
│  │  │  │  ├─ processing_job.py
│  │  │  │  └─ __init__.py
│  │  │  ├─ session.py
│  │  │  └─ base.py
│  │  ├─ services/
│  │  │  ├─ embedding.py
│  │  │  ├─ qdrant_service.py
│  │  │  ├─ bm25_service.py
│  │  │  ├─ reranker.py
│  │  │  ├─ llm.py
│  │  │  ├─ search_service.py
│  │  │  ├─ document_service.py
│  │  │  ├─ preview_service.py
│  │  │  ├─ chunk_stats.py
│  │  │  └─ storage.py
│  │  ├─ schemas/
│  │  │  ├─ auth.py
│  │  │  ├─ document.py
│  │  │  ├─ search.py
│  │  │  ├─ processing_job.py
│  │  │  ├─ golden_query.py (신규)
│  │  │  └─ __init__.py
│  │  ├─ core/
│  │  │  ├─ config.py
│  │  │  ├─ security.py
│  │  │  ├─ logging.py
│  │  │  ├─ crypto.py
│  │  │  └─ __init__.py
│  │  └─ main.py
│  ├─ alembic/
│  │  └─ versions/
│  │      ├─ a3c5d7e9f1b2_add_reembed_status_to_collections.py (신규)
│  │      └─ b4d6e8f0a2c3_add_golden_queries_and_eval_runs.py (신규)
│  ├─ pyproject.toml
│  └─ poetry.lock
├─ frontend/
│  ├─ src/
│  │  ├─ pages/
│  │  │  ├─ DashboardPage.tsx
│  │  │  ├─ DocumentsPage.tsx
│  │  │  ├─ DocumentDetailPage.tsx (청크 히트카운트 배지 포함)
│  │  │  ├─ CollectionsPage.tsx (골든 쿼리 평가 버튼 포함)
│  │  │  ├─ ChatPage.tsx
│  │  │  ├─ SearchPage.tsx
│  │  │  ├─ ProjectsPage.tsx
│  │  │  ├─ SettingsPage.tsx
│  │  │  ├─ UsersPage.tsx
│  │  │  ├─ LoginPage.tsx
│  │  │  └─ RegisterPage.tsx
│  │  ├─ components/
│  │  │  ├─ Layout.tsx
│  │  │  ├─ GoldenEvalModal.tsx (신규: 골든 쿼리 평가 모달)
│  │  │  ├─ ui/
│  │  │  │  ├─ Spinner.tsx
│  │  │  │  └─ Badge.tsx
│  │  │  └─ __init__.ts
│  │  ├─ hooks/
│  │  │  ├─ useDocuments.ts
│  │  │  ├─ useCollections.ts
│  │  │  ├─ useChat.ts
│  │  │  ├─ useGoldenQueries.ts (신규)
│  │  │  ├─ useSearchHistory.ts
│  │  │  ├─ useProcessingJobs.ts
│  │  │  ├─ useApiKeys.ts
│  │  │  ├─ useProfile.ts
│  │  │  ├─ useUsers.ts
│  │  │  ├─ useProjects.ts
│  │  │  └─ __init__.ts
│  │  ├─ lib/
│  │  │  ├─ apiClient.ts
│  │  │  ├─ documentStatus.ts
│  │  │  └─ __init__.ts
│  │  ├─ store/
│  │  │  └─ authStore.ts
│  │  ├─ types/
│  │  │  └─ index.ts
│  │  ├─ main.tsx
│  │  ├─ App.tsx
│  │  └─ test/
│  │      ├─ setup.ts
│  │      ├─ authStore.test.ts
│  │      └─ __init__.ts
│  ├─ package.json
│  ├─ tsconfig.json
│  ├─ vite.config.ts
│  └─ index.html
├─ docker-compose.yml
├─ .gitignore
└─ README.md
```

### 2.1 최상위 디렉터리 원칙
- `src/`는 실제 애플리케이션 코드
- `configs/`는 실행/정책 설정
- `data/`는 입력 및 중간 산출물
- `outputs/`는 최종 export 결과
- `tests/`는 단위 / 통합 테스트
- `scripts/`는 실행 보조 스크립트
- `main.py`는 단일 진입점 또는 CLI 진입점

---

## 3. src/ 전체 파일 구조

```text
src/
├─ ingest/
│  ├─ __init__.py
│  ├─ input_document_builder.py
│  └─ mime_detector.py
│
├─ adapters/
│  ├─ __init__.py
│  ├─ base_adapter.py
│  ├─ pdf_adapter.py
│  ├─ hwp_adapter.py
│  ├─ hwpx_adapter.py
│  └─ docx_adapter.py
│
├─ parser/
│  ├─ __init__.py
│  ├─ parser_facade.py
│  ├─ raw_document_builder.py
│  ├─ pdf_native_parser.py
│  ├─ ocr_assist.py
│  ├─ visual_region_detector.py
│  └─ table_candidate_detector.py
│
├─ structurer/
│  ├─ __init__.py
│  ├─ structuring_engine.py
│  ├─ block_segmenter.py
│  ├─ block_classifier.py
│  ├─ reading_order_resolver.py
│  ├─ section_tree_builder.py
│  ├─ table_reconstructor.py
│  ├─ figure_linker.py
│  ├─ header_footer_detector.py
│  └─ provenance_builder.py
│
├─ review/
│  ├─ __init__.py
│  ├─ review_bundle_builder.py
│  ├─ review_json_builder.py
│  ├─ review_markdown_renderer.py
│  ├─ diagnostics_summarizer.py
│  └─ refinement_template_builder.py
│
├─ refinement/
│  ├─ __init__.py
│  ├─ refinement_engine.py
│  ├─ refinement_validator.py
│  ├─ refinement_operations.py
│  ├─ refinement_history.py
│  └─ target_resolver.py
│
├─ recompute/
│  ├─ __init__.py
│  ├─ recompute_engine.py
│  ├─ recompute_planner.py
│  ├─ section_recompute.py
│  ├─ table_recompute.py
│  ├─ chunk_recompute.py
│  └─ quality_recompute.py
│
├─ normalization/
│  ├─ __init__.py
│  ├─ semantic_normalizer.py
│  ├─ text_normalizer.py
│  ├─ numeric_parser.py
│  ├─ unit_normalizer.py
│  ├─ date_normalizer.py
│  ├─ header_path_builder.py
│  ├─ record_builder.py
│  ├─ fact_builder.py
│  └─ entity_extractor.py
│
├─ quality/
│  ├─ __init__.py
│  ├─ quality_evaluator.py
│  ├─ document_quality.py
│  ├─ page_quality.py
│  ├─ block_quality.py
│  ├─ table_quality.py
│  ├─ figure_quality.py
│  └─ warning_builder.py
│
├─ chunking/
│  ├─ __init__.py
│  ├─ chunk_engine.py
│  ├─ section_chunker.py
│  ├─ paragraph_chunker.py
│  ├─ table_chunker.py
│  ├─ figure_chunker.py
│  ├─ fact_chunker.py
│  └─ chunk_metadata_builder.py
│
├─ export/
│  ├─ __init__.py
│  ├─ export_bundle_writer.py
│  ├─ canonical_json_writer.py
│  ├─ raw_json_writer.py
│  ├─ review_bundle_writer.py
│  ├─ chunk_jsonl_writer.py
│  ├─ record_jsonl_writer.py
│  ├─ fact_jsonl_writer.py
│  └─ diagnostics_writer.py
│
├─ models/
│  ├─ __init__.py
│  ├─ input_models.py
│  ├─ raw_models.py
│  ├─ structured_models.py
│  ├─ review_models.py
│  ├─ refinement_models.py
│  ├─ canonical_models.py
│  ├─ chunk_models.py
│  ├─ quality_models.py
│  └─ export_models.py
│
├─ repositories/
│  ├─ __init__.py
│  ├─ review_repository.py
│  ├─ refinement_repository.py
│  ├─ document_repository.py
│  └─ export_repository.py
│
├─ services/
│  ├─ __init__.py
│  ├─ document_structuring_service.py
│  ├─ review_service.py
│  ├─ refinement_service.py
│  └─ export_service.py
│
├─ pipelines/
│  ├─ __init__.py
│  ├─ structuring_pipeline.py
│  ├─ review_pipeline.py
│  ├─ refinement_pipeline.py
│  └─ full_pipeline.py
│
├─ common/
│  ├─ __init__.py
│  ├─ config.py
│  ├─ constants.py
│  ├─ enums.py
│  ├─ errors.py
│  └─ logging.py
│
└─ utils/
   ├─ __init__.py
   ├─ file_utils.py
   ├─ bbox_utils.py
   ├─ text_utils.py
   ├─ json_utils.py
   └─ id_utils.py
```

---

## 4. 디렉터리별 파일 상세 설계

## 4.1 ingest/

### `input_document_builder.py`
역할:
- 입력 파일을 `InputDocument`로 생성
- file hash, source path, file type 등 메타 구성

입력:
- 파일 경로 또는 업로드 자원

출력:
- `InputDocument`

비책임:
- adapter 선택
- parsing
- structure reconstruction

### `mime_detector.py`
역할:
- MIME type, 확장자, 포맷 판별 보조

---

## 4.2 adapters/

### `base_adapter.py`
역할:
- 모든 adapter의 공통 인터페이스 정의

포함:
- `identify()`
- `supports()`
- `build_parse_context()`

### `pdf_adapter.py`
역할:
- PDF 처리 컨텍스트 생성
- PDF 전용 parser 설정 제공

### `hwp_adapter.py`
역할:
- HWP 처리 컨텍스트 생성

### `hwpx_adapter.py`
역할:
- HWPX 처리 컨텍스트 생성

### `docx_adapter.py`
역할:
- DOCX 처리 컨텍스트 생성

원칙:
- adapter는 raw parsing 이전의 포맷별 준비만 담당
- structure reconstruction이나 semantic normalization 책임을 갖지 않는다

---

## 4.3 parser/

### `parser_facade.py`
역할:
- adapter와 parser를 조합해 parse entry를 제공
- 외부에서는 이 파일을 통해 parser 계층을 호출

### `raw_document_builder.py`
역할:
- native parse 결과를 `RawParsedDocument` 객체로 조립

### `pdf_native_parser.py`
역할:
- PDF native text / span / line / bbox 추출
- raw page, raw text block, raw image, raw drawing, raw table candidate 생성

### `ocr_assist.py`
역할:
- OCR 적용 조건 판단
- page / region / cell OCR 수행
- OCR 결과를 raw metadata로 부착

### `visual_region_detector.py`
역할:
- image-heavy / chart-like / table-like 영역 후보 검출

### `table_candidate_detector.py`
역할:
- raw table candidate 추출
- explicit / implicit table 후보 힌트 제공

원칙:
- parser 디렉터리는 raw parse까지만 담당
- section tree, heading, caption, chunk는 생성하지 않는다

---

## 4.4 structurer/

### `structuring_engine.py`
역할:
- structurer 계층의 상위 엔트리
- raw → structured 변환 전체 orchestrate

### `block_segmenter.py`
역할:
- line/span 기반 block segmentation

### `block_classifier.py`
역할:
- block type / role 판정
- heading, caption, header/footer 후보 분류

### `reading_order_resolver.py`
역할:
- multi-column 포함 reading order 복원

### `section_tree_builder.py`
역할:
- heading block 기반 section tree 생성

### `table_reconstructor.py`
역할:
- raw table candidate를 table/cell/expanded_grid/header_paths 구조로 복원

### `figure_linker.py`
역할:
- figure candidate와 caption block 연결
- figure kind 판정

### `header_footer_detector.py`
역할:
- 반복 블록 기반 header/footer/page number 판정

### `provenance_builder.py`
역할:
- structured object별 provenance 생성

원칙:
- structurer는 semantic normalization을 하지 않는다
- structurer는 refinement를 적용하지 않는다

---

## 4.5 review/

### `review_bundle_builder.py`
역할:
- review bundle 전체 조립
- review json, markdown, diagnostics summary, refinement template를 묶음 생성

### `review_json_builder.py`
역할:
- StructuredDocument를 review 대상 JSON으로 변환

### `review_markdown_renderer.py`
역할:
- review markdown 출력 생성
- block/table/figure/ocr/source/review_hint 표시 규칙 적용

### `diagnostics_summarizer.py`
역할:
- warnings / quality / OCR / table review 대상 요약

### `refinement_template_builder.py`
역할:
- 빈 refinement template 생성

원칙:
- review는 “표현” 계층
- 실제 refinement 적용은 하지 않는다

---

## 4.6 refinement/

### `refinement_engine.py`
역할:
- refinement 전체 적용 엔트리

### `refinement_validator.py`
역할:
- target_id 존재 여부, payload 형식, 충돌 여부 검사

### `refinement_operations.py`
역할:
- block_remove, block_role_change, table_remove, table_header_override, ocr_source_preference 등 실제 명령 처리

### `refinement_history.py`
역할:
- refinement audit / before-after 기록

### `target_resolver.py`
역할:
- target_id를 실제 객체에 resolve

원칙:
- refinement는 non-destructive
- 직접 export하지 않는다
- recompute는 별도 계층이 담당한다

---

## 4.7 recompute/

### `recompute_engine.py`
역할:
- recompute 전체 실행 엔트리

### `recompute_planner.py`
역할:
- refinement 결과를 바탕으로 영향 범위 계산

### `section_recompute.py`
역할:
- section tree 재계산

### `table_recompute.py`
역할:
- header_paths, expanded_grid, records, facts 관련 재계산

### `chunk_recompute.py`
역할:
- 영향 받은 chunks 재생성

### `quality_recompute.py`
역할:
- 영향 받은 quality score / warning 재평가

---

## 4.8 normalization/

### `semantic_normalizer.py`
역할:
- normalization 계층의 상위 엔트리

### `text_normalizer.py`
역할:
- 줄바꿈, 공백, 하이픈, 특수문자 정리

### `numeric_parser.py`
역할:
- 숫자, 퍼센트, 괄호 음수, 쉼표 포함 값 파싱

### `unit_normalizer.py`
역할:
- 단위 분리 및 표준화

### `date_normalizer.py`
역할:
- 날짜/연월/분기 표준화

### `header_path_builder.py`
역할:
- 다단 헤더 경로 생성/안정화

### `record_builder.py`
역할:
- row record 생성

### `fact_builder.py`
역할:
- subject-predicate-object fact 생성

### `entity_extractor.py`
역할:
- 날짜, 지표명, 조직명 등 entity 추출

---

## 4.9 quality/

### `quality_evaluator.py`
역할:
- 전체 품질 평가 엔트리

### `document_quality.py`
역할:
- document 수준 평가

### `page_quality.py`
역할:
- page 수준 평가

### `block_quality.py`
역할:
- block 수준 평가

### `table_quality.py`
역할:
- table 수준 평가

### `figure_quality.py`
역할:
- figure 수준 평가

### `warning_builder.py`
역할:
- warning code 생성

---

## 4.10 chunking/

### `chunk_engine.py`
역할:
- chunk 계층 상위 엔트리

### `section_chunker.py`
역할:
- section chunk 생성

### `paragraph_chunker.py`
역할:
- paragraph chunk 생성

### `table_chunker.py`
역할:
- table summary / record chunk 생성

### `figure_chunker.py`
역할:
- figure-caption chunk 생성

### `fact_chunker.py`
역할:
- fact chunk 생성

### `chunk_metadata_builder.py`
역할:
- chunk metadata 통일 생성

---

## 4.11 export/

### `export_bundle_writer.py`
역할:
- export 전체 orchestrate

### `canonical_json_writer.py`
역할:
- canonical json 저장

### `raw_json_writer.py`
역할:
- raw / structured debug json 저장

### `review_bundle_writer.py`
역할:
- review markdown/json/diagnostics/template 저장

### `chunk_jsonl_writer.py`
역할:
- chunk jsonl 저장

### `record_jsonl_writer.py`
역할:
- record jsonl 저장

### `fact_jsonl_writer.py`
역할:
- fact jsonl 저장

### `diagnostics_writer.py`
역할:
- diagnostics 저장

원칙:
- exporter는 “저장/출력”만 담당
- review 내용을 생성하지 않는다

---

## 4.12 models/

### `input_models.py`
정의:
- InputDocument
- SourceMetadata

### `raw_models.py`
정의:
- RawParsedDocument
- RawPage
- RawTextBlock
- RawLine
- RawSpan
- RawWord
- RawImage
- RawDrawing
- RawTableCandidate

### `structured_models.py`
정의:
- StructuredDocument
- Page
- Block
- Section
- Table
- Cell
- Figure
- ProvenanceEntry
- WarningEntry
- DiagnosticsEntry

### `review_models.py`
정의:
- ReviewBundle
- ReviewSummary
- ReviewHint

### `refinement_models.py`
정의:
- RefinementSet
- RefinementOperation
- RefinedDocument
- RefinementHistoryEntry

### `canonical_models.py`
정의:
- CanonicalDocument
- Record
- Fact
- Entity

### `chunk_models.py`
정의:
- Chunk
- ChunkMetadata

### `quality_models.py`
정의:
- DocumentQuality
- PageQuality
- BlockQuality
- TableQuality
- FigureQuality

### `export_models.py`
정의:
- ExportBundle

원칙:
- 데이터 객체는 models로 집중
- 서비스/엔진 로직은 포함하지 않는다

---

## 4.13 repositories/

### `review_repository.py`
역할:
- review bundle 로드/저장

### `refinement_repository.py`
역할:
- refinement json 로드/저장
- history 로드/저장

### `document_repository.py`
역할:
- structured/canonical 문서 저장소 추상화

### `export_repository.py`
역할:
- export 파일 경로 및 저장소 추상화

---

## 4.14 services/

### `document_structuring_service.py`
역할:
- 전체 구조화 서비스 façade
- 외부에서 가장 많이 호출하는 상위 서비스

### `review_service.py`
역할:
- review bundle 생성 및 조회 orchestration

### `refinement_service.py`
역할:
- refinement load/apply/recompute orchestration

### `export_service.py`
역할:
- export bundle 구성/저장 orchestration

---

## 4.15 pipelines/

### `structuring_pipeline.py`
역할:
- ingest → parse → structure 까지 실행

### `review_pipeline.py`
역할:
- structure → review bundle 생성

### `refinement_pipeline.py`
역할:
- structured + refinement → recompute → canonical

### `full_pipeline.py`
역할:
- 전체 end-to-end 실행

---

## 4.16 common/

### `config.py`
역할:
- 설정 로딩

### `constants.py`
역할:
- 공통 상수

### `enums.py`
역할:
- enum 정의

### `errors.py`
역할:
- 사용자 정의 예외

### `logging.py`
역할:
- 공통 로깅 초기화

---

## 4.17 utils/

### `file_utils.py`
역할:
- 파일 경로/해시/IO 보조

### `bbox_utils.py`
역할:
- bbox 계산 / overlap / distance

### `text_utils.py`
역할:
- 텍스트 보조 함수

### `json_utils.py`
역할:
- json dump/load helper

### `id_utils.py`
역할:
- stable id 생성

---

## 5. 파일 간 의존 방향 원칙

### 5.1 허용 방향
- ingest → models/common/utils
- adapters → models/common
- parser → adapters/models/common/utils
- structurer → parser outputs/models/common/utils
- review → structured models/common
- refinement → review/models/common
- recompute → refinement/models/common
- normalization → refined/models/common
- quality → canonical/structured/common
- chunking → canonical/models/common
- export → all finalized outputs/models/common
- services/pipelines → 각 엔진 계층 사용 가능

### 5.2 금지 방향
- parser가 structurer를 참조하면 안 된다.
- structurer가 exporter를 참조하면 안 된다.
- review가 refinement를 수행하면 안 된다.
- exporter가 semantic normalization을 수행하면 안 된다.
- models가 services를 참조하면 안 된다.

---

## 6. main.py와 scripts 역할

### `main.py`
역할:
- CLI / default pipeline entry
- 설정 로드
- 선택된 pipeline 실행

### `scripts/`
역할:
- 개발/검증/마이그레이션 보조 스크립트
- 테스트 데이터 생성
- 리뷰 번들 재생성
- 특정 단계 디버깅

---

## 7. 테스트 파일 구조 권장

```text
tests/
├─ unit/
│  ├─ test_block_segmenter.py
│  ├─ test_section_tree_builder.py
│  ├─ test_table_reconstructor.py
│  ├─ test_refinement_engine.py
│  ├─ test_review_markdown_renderer.py
│  └─ test_semantic_normalizer.py
├─ integration/
│  ├─ test_structuring_pipeline.py
│  ├─ test_review_pipeline.py
│  ├─ test_refinement_pipeline.py
│  └─ test_full_pipeline.py
└─ fixtures/
   ├─ sample_docs/
   ├─ raw_docs/
   └─ expected_outputs/
```

---

## 8. 파일 단위 설계 결론

최종 구현은 디렉터리 이름만으로는 충분하지 않다.  
어떤 파일이 어떤 책임을 갖는지, 어떤 파일이 어떤 계층에서만 존재해야 하는지까지 고정해야 이후 코드가 다시 섞이지 않는다.

이 문서는 다음 단계의 기반이 된다.

- module interface 설계
- class 상세 설계
- 실제 코드 skeleton 생성

즉, 이 문서는 폴더 구조 설계를 “실제 코드 작성 가능한 파일 구조”로 내린 구현 설계 문서다.
