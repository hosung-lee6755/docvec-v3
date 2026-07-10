# execution_architecture.md
# Document Structuring Solution - Execution Architecture

## 1. 문서 목적

본 문서는 Document Structuring Solution의 전체 실행 아키텍처를 정의한다.  
이 문서는 기존의 구조 규칙, schema, refinement, review 규칙을 “어떤 실행 모듈과 상태 객체로 묶을 것인가”를 다룬다.

본 문서는 구현 순서가 아니라 최종 아키텍처의 정답 상태를 정의한다.

---

## 2. 아키텍처 목적

본 아키텍처는 다음을 만족해야 한다.

- 포맷별 parser는 달라도 출력 구조는 동일
- 자동 구조화와 사용자 정제의 경계가 명확
- canonical 이전과 이후 계층 분리
- review와 export 책임 분리
- refinement와 recompute 분리
- 코드 재구성 / 신규 생성의 기준 제공

---

## 3. 상태 객체 흐름

전체 상태 흐름은 아래와 같다.

```text
InputDocument
  ↓
RawParsedDocument
  ↓
StructuredDocument
  ↓
ReviewBundle
  ↓
RefinedDocument
  ↓
CanonicalDocument
  ↓
ExportBundle
```

### 3.1 InputDocument
입력 파일을 시스템 내부 처리 단위로 표현한 객체

### 3.2 RawParsedDocument
포맷별 parser가 만든 원시 추출 결과

### 3.3 StructuredDocument
구조 복원 결과

### 3.4 ReviewBundle
사용자 검토용 패키지

### 3.5 RefinedDocument
refinement 적용 결과

### 3.6 CanonicalDocument
semantic normalization 완료 결과

### 3.7 ExportBundle
외부 저장/활용용 최종 산출물

---

## 4. 최상위 실행 흐름

```text
Document Ingest
  → Adapter Resolution
  → Native Parse
  → Structure Reconstruction
  → Review Bundle Generation
  → Refinement Application
  → Post-Refinement Recompute
  → Semantic Normalization
  → Quality Evaluation
  → Chunk / Record / Fact Generation
  → Export
```

---

## 5. 모듈 구조

### 5.1 DocumentIngestModule
입력 파일을 식별하고 처리 컨텍스트를 생성한다.

#### 입력
- file path
- optional binary stream

#### 출력
- InputDocument

#### 책임
- file hash 생성
- mime type 판별
- source metadata 생성

---

### 5.2 AdapterResolutionModule
입력 포맷에 따라 adapter를 선택한다.

#### 입력
- InputDocument

#### 출력
- adapter descriptor / adapter instance

#### 책임
- PDF / HWP / HWPX / DOCX 분기
- 포맷별 capability 확인

---

### 5.3 NativeParseModule
원본 문서 포맷의 native 구조를 최대한 추출한다.

#### 입력
- InputDocument
- adapter

#### 출력
- RawParsedDocument

#### 책임
- raw text / line / span / bbox 추출
- raw images / drawings 추출
- raw table candidates 추출
- OCR candidate signal 수집

#### 비책임
- section tree 확정
- semantic normalization
- chunk 생성

---

### 5.4 StructureReconstructionModule
RawParsedDocument를 StructuredDocument로 변환한다.

#### 입력
- RawParsedDocument

#### 출력
- StructuredDocument

#### 책임
- block segmentation
- heading/caption/header/footer 판정
- reading order 복원
- section tree 구성
- table reconstruction
- figure/caption 연결
- OCR assist 병합
- provenance 유지
- **HWP/HWPX 실제 페이지 분할** (`_repaginate_hwp_like`): Preview PDF의 per-page 텍스트와 매칭하여 단일 page_number=1에서 실제 페이지로 재파악 (monotonic cursor, 60char anchor, table 특수 처리)

---

### 5.5 ReviewBundleGenerationModule
StructuredDocument를 사람이 검토 가능한 ReviewBundle로 변환한다.

#### 입력
- StructuredDocument

#### 출력
- ReviewBundle

#### 책임
- review json 생성
- review markdown 생성
- diagnostics summary 생성
- refinement template 생성

---

### 5.6 RefinementApplicationModule
사용자 refinement를 StructuredDocument에 적용한다.

#### 입력
- StructuredDocument
- refinement json

#### 출력
- RefinedDocument

#### 책임
- block/table/ocr 관련 명령 적용
- validity 검사
- audit 기록
- recompute target 계산

---

### 5.7 PostRefinementRecomputeModule
refinement 이후 영향 받은 영역만 다시 계산한다.

#### 입력
- RefinedDocument

#### 출력
- recomputed RefinedDocument

#### 책임
- section tree 재구성
- table header path 재생성
- record/fact 대상 재생성
- chunk 대상 재계산
- quality 대상 재평가

---

### 5.8 SemanticNormalizationModule
구조 문서를 기계 활용 친화적인 canonical 의미 구조로 정규화한다.

#### 입력
- RefinedDocument

#### 출력
- CanonicalDocument

#### 책임
- text normalization
- numeric / unit / date normalization
- header path 안정화
- record 생성
- fact 생성
- entity extraction

---

### 5.9 QualityEvaluationModule
문서와 객체의 품질을 평가한다.

#### 입력
- StructuredDocument 또는 CanonicalDocument
- diagnostics
- refinement 결과

#### 출력
- quality annotations
- warning list

#### 책임
- document/page/block/table/figure quality
- grade 계산
- warning 생성

---

### 5.10 ChunkGenerationModule
검색과 추론 단위를 생성한다.

#### 입력
- CanonicalDocument

#### 출력
- chunks
- records
- facts

#### 책임
- section chunk
- paragraph chunk
- heading-context chunk
- table summary chunk
- table record chunk
- figure-caption chunk
- fact chunk

---

### 5.11 ExportModule
최종 산출물을 저장하고 배포 가능한 형태로 내보낸다.

#### 입력
- StructuredDocument(optional)
- CanonicalDocument
- chunks / records / facts
- diagnostics
- review bundle

#### 출력
- ExportBundle
- persisted files

#### 책임
- canonical json 저장
- review markdown 저장
- review json 저장
- chunk/record/fact jsonl 저장
- diagnostics 저장
- aggregate outputs 저장

---

## 6. 모듈 간 인터페이스 원칙

### 6.1 불변성
모듈은 입력 객체를 직접 파괴적으로 수정하지 않는다.

### 6.2 단일 책임
- parser는 parse만
- structurer는 구조 복원만
- refinement engine은 수정 적용만
- exporter는 저장만

### 6.3 계층 의존성 제한
- 상위는 하위를 사용할 수 있다.
- 하위는 상위를 몰라야 한다.
- canonical 이전/이후 계층은 분리한다.

---

## 7. review와 refinement의 실행 위치

### 7.1 review bundle 생성 시점
반드시 StructuredDocument 생성 직후다.

이유:
- review 대상은 구조화 결과다.
- canonical 이후에는 raw 구조 단서가 약해진다.
- 사람이 검토해야 할 대상은 block / table / caption 같은 구조 객체다.

### 7.2 refinement 적용 시점
review 이후, semantic normalization 이전이다.

### 7.3 recompute 시점
refinement 직후 즉시 수행한다.

---

## 8. canonical 이전과 이후의 분리

### 8.1 canonical 이전
- raw parse
- structure reconstruction
- review
- refinement
- recompute

### 8.2 canonical 이후
- semantic normalization
- quality evaluation
- chunk/record/fact generation
- export

### 8.3 이유
구조 복원 계층과 의미 활용 계층을 섞으면 책임이 흐려진다.

---

## 9. review-required / auto-pass 실행 모드

### 9.1 review-required
- review bundle 생성 후 정지
- refinement 입력 대기
- 이후 재개

### 9.2 auto-pass
- refinement가 없으면 빈 refinement로 간주
- 다음 단계로 진행

이 설계는 UI 여부와 무관하게 유지된다.

---

## 10. 부분 재실행 원칙

1. refinement 이후 전체 파이프라인 재실행을 기본 금지
2. 영향 범위 기반 recompute 우선
3. raw parse / structure reconstruction 결과는 최대한 재사용
4. export는 변경 범위만 갱신 가능해야 한다.

### 10.1 Celery 비동기 태스크 통합

문서 처리 파이프라인은 FastAPI 요청 스레드 안에서 직접 실행되지 않는다.  
각 스테이지는 Celery Worker로 위임되어 비동기 실행된다.

**11개 모듈과 8개 Celery 태스크 매핑:**

| Celery 태스크 | 담당 모듈 |
|-------------|----------|
| `ingest_task` | DocumentIngestModule + AdapterResolutionModule + NativeParseModule |
| `structure_task` | StructureReconstructionModule |
| `review_prep_task` | ReviewBundleGenerationModule |
| `refine_task` | RefinementApplicationModule + PostRefinementRecomputeModule |
| `normalize_task` | SemanticNormalizationModule + QualityEvaluationModule |
| `chunk_task` | ChunkGenerationModule |
| `embed_task` | EmbeddingProvider (플러그인) |
| `qdrant_upload_task` | ExportModule (Qdrant 업로드) |

**태스크 체이닝:**
- `FULL_AUTO` 모드: 8개 태스크를 Celery Chain으로 순서 보장하여 자동 실행
- `REVIEW_REQUIRED` 모드: `ingest → structure → review_prep`까지 실행 후 대기,  
  사용자 정제 완료 후 `refine_task`부터 별도 Chain 재개
- 진행 상황은 Redis PubSub → FastAPI WebSocket을 통해 실시간 전달

상세 태스크 정의는 `task_queue_design.md` 참조.

### 10.2 부분 실패 복구 및 재시작

파이프라인 스테이지 중 하나가 실패해도 이전 단계 결과물은 MinIO에 보존된다.

**실패 기록:**
- `documents.failed_stage` 필드에 실패한 스테이지 이름을 기록한다 (예: `'normalize'`).
- `processing_jobs` 테이블에 에러 코드 및 에러 메시지가 저장된다.

**재시작 흐름:**
```
POST /api/v1/documents/{id}/retry?from_stage=normalize
  → FastAPI: from_stage에 해당하는 태스크부터 Chain 재구성
  → documents.status = NORMALIZING으로 재설정
  → Celery: normalize_task → chunk_task → embed_task → qdrant_upload_task 순 실행
```

**재시작 가능 스테이지:**

| from_stage | 재시작 태스크 |
|-----------|-------------|
| `ingest` | `ingest_task` → 전체 체인 |
| `structure` | `structure_task` → 이후 전체 |
| `review` | `review_prep_task` → 이후 전체 |
| `refine` | `refine_task` → 이후 전체 |
| `normalize` | `normalize_task` → 이후 전체 |
| `chunk` | `chunk_task` → 이후 전체 |
| `embed` | `embed_task` → 이후 전체 |
| `upload` | `qdrant_upload_task` 단독 재실행 |

---

## 11. Export 계층

### 11.1 Raw / Debug Export
- raw parsed json
- low-level diagnostics
- visual region artifacts

### 11.2 Review Export
- review markdown
- review json
- refinement template
- warning summary

### 11.3 Canonical Export
- canonical json

### 11.4 Retrieval / Reasoning Export
- chunks jsonl
- records jsonl
- facts jsonl

### 11.5 Aggregate Export
- documents.json
- chunks.jsonl
- records.jsonl
- facts.jsonl

---

## 12. 현재 코드 재구성의 기준

이 문서는 현재 코드 형태를 유지하라고 요구하지 않는다.  
대신 아래 질문을 기준으로 코드 구조를 판단한다.

- 이 기능은 어느 모듈 책임인가
- 현재 파일은 한 가지 책임만 갖는가
- review와 export가 섞여 있지 않은가
- refinement와 pruning이 혼재되어 있지 않은가
- canonical 이전과 이후가 섞여 있지 않은가

즉, 리팩토링 기준은 “현재 파일 보존”이 아니라 “책임 재배치”다.

---

## 13. 최종 결론

Execution Architecture는 기존 상세 설계를 버리는 문서가 아니다.  
오히려 아래 상세 설계를 실제 실행 구조로 연결하는 상위 기준이다.

- engine design
- canonical schema
- refinement specification
- review specification
- task_queue_design (Celery 태스크 정의, 체이닝, 실패 처리)

이 문서가 고정되어야 이후 폴더 구조, 모듈 구조, 클래스 설계도 일관되게 결정할 수 있다.
