# PostgreSQL 메타데이터 스키마 설계

## 1. 설계 원칙

- **소프트 삭제**: 모든 주요 엔티티에 `deleted_at` 컬럼 사용 (데이터 복구 가능성)
- **Enum 타입**: Python Enum과 1:1 매핑하는 PostgreSQL ENUM 사용
- **JSON 컬럼**: 가변 메타데이터는 `JSONB`에 저장 (인덱스 가능)
- **타임스탬프**: 모든 테이블에 `created_at`, `updated_at` (자동 갱신 트리거)
- **UUID PK**: 분산 환경 확장성을 위해 UUID v7 (시간 정렬 가능) 사용

---

## 2. ERD 개요

```
users ──────────────────────────────┐
  │                                  │
  │ (uploaded_by)                    │ (owned_by)
  ▼                                  ▼
documents ──────────────► collections
  │           (M:N via               │
  │            collection_documents) │
  │                                  │
  ▼                                  │
processing_jobs                      │
  │                                  │
  ▼                                  │
chunks_meta ─────────────────────────┘
  (qdrant_point_id refs)

documents
  │
  ├── refinement_sets (1:N)
  └── export_artifacts (1:N)
```

---

## 3. 테이블 정의

### 3-1. `users`

```sql
CREATE TYPE user_role AS ENUM ('viewer', 'editor', 'admin');

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    display_name    VARCHAR(100),
    role            user_role NOT NULL DEFAULT 'editor',
    is_active       BOOLEAN NOT NULL DEFAULT true,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX idx_users_email ON users(email) WHERE deleted_at IS NULL;
```

---

### 3-2. `documents`

문서 업로드 및 처리 상태의 중심 엔티티.

```sql
CREATE TYPE document_status AS ENUM (
    'QUEUED',
    'INGESTING',
    'PARSING',
    'STRUCTURING',
    'REVIEW_PENDING',
    'REFINING',
    'NORMALIZING',
    'CHUNKING',
    'EMBEDDING',
    'UPLOADING',
    'INDEXED',
    'FAILED',
    'CANCELLED'
);

CREATE TYPE pipeline_mode AS ENUM (
    'FULL_AUTO',
    'REVIEW_REQUIRED',
    'AUTO_WITH_LOW_CONFIDENCE'
);

CREATE TYPE document_format AS ENUM ('PDF', 'HWP', 'HWPX', 'DOCX');

CREATE TABLE documents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    uploaded_by         UUID NOT NULL REFERENCES users(id),

    -- 원본 파일 정보
    original_filename   VARCHAR(500) NOT NULL,
    file_format         document_format NOT NULL,
    file_size_bytes     BIGINT NOT NULL,
    file_hash_sha256    CHAR(64) NOT NULL,
    storage_path        VARCHAR(1000) NOT NULL,   -- MinIO 경로 (originals/{id}/...)

    -- 처리 설정
    pipeline_mode       pipeline_mode NOT NULL DEFAULT 'REVIEW_REQUIRED',
    target_collection_id UUID REFERENCES collections(id),

    -- 처리 상태
    status              document_status NOT NULL DEFAULT 'QUEUED',
    current_stage       VARCHAR(50),              -- 현재 실행 중인 Stage 이름
    failed_stage        VARCHAR(50),              -- 실패한 Stage 이름
    error_code          VARCHAR(50),
    error_message       TEXT,
    retry_count         SMALLINT NOT NULL DEFAULT 0,
    max_retries         SMALLINT NOT NULL DEFAULT 3,

    -- 처리 결과 경로 (MinIO)
    artifact_base_path  VARCHAR(1000),            -- artifacts/{id}/

    -- 품질 지표 (처리 완료 후 채움)
    total_pages         INTEGER,
    total_blocks        INTEGER,
    total_chunks        INTEGER,
    quality_score       NUMERIC(4,3),             -- 0.000 ~ 1.000
    ocr_page_count      INTEGER,                  -- OCR 처리된 페이지 수
    low_confidence_count INTEGER,                 -- 낮은 신뢰도 블록 수

    -- 문서 메타데이터 (추출된 값)
    doc_title           VARCHAR(500),
    doc_language        VARCHAR(10),              -- 'ko', 'en', 'ja', ...
    doc_metadata        JSONB,                    -- {author, created_date, page_count, ...}

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ
);

CREATE INDEX idx_documents_uploaded_by ON documents(uploaded_by) WHERE deleted_at IS NULL;
CREATE INDEX idx_documents_status ON documents(status) WHERE deleted_at IS NULL;
CREATE INDEX idx_documents_collection ON documents(target_collection_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_documents_hash ON documents(file_hash_sha256);
```

---

### 3-3. `processing_jobs`

Celery 작업 추적. 문서당 파이프라인 Stage 하나에 대응.

```sql
CREATE TYPE job_status AS ENUM (
    'PENDING', 'RUNNING', 'SUCCESS', 'FAILURE', 'REVOKED', 'RETRY'
);

CREATE TABLE processing_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL REFERENCES documents(id),
    celery_task_id  VARCHAR(255) UNIQUE,          -- Celery task UUID
    stage_name      VARCHAR(50) NOT NULL,         -- 'ingest', 'structure', ...
    status          job_status NOT NULL DEFAULT 'PENDING',

    -- 진행률 (0.0 ~ 1.0)
    progress        NUMERIC(4,3) DEFAULT 0.0,
    progress_message VARCHAR(500),

    -- 실행 정보
    worker_hostname VARCHAR(255),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    duration_ms     INTEGER,                      -- finished - started

    -- 결과 / 오류
    result_summary  JSONB,                        -- {pages_processed, blocks_found, ...}
    error_code      VARCHAR(50),
    error_message   TEXT,
    error_traceback TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_jobs_document_id ON processing_jobs(document_id);
CREATE INDEX idx_jobs_celery_task_id ON processing_jobs(celery_task_id);
CREATE INDEX idx_jobs_status ON processing_jobs(status);
```

---

### 3-4. `collections`

Qdrant 컬렉션과 1:1 대응. 논리적 지식 베이스 단위.

```sql
CREATE TABLE collections (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owned_by            UUID NOT NULL REFERENCES users(id),

    -- 식별 정보
    name                VARCHAR(200) NOT NULL,
    slug                VARCHAR(200) UNIQUE NOT NULL,  -- URL-safe 이름
    description         TEXT,

    -- 임베딩 설정
    embedding_provider  VARCHAR(50) NOT NULL,          -- 'openai', 'bge_m3', 'e5_large'
    embedding_model     VARCHAR(100) NOT NULL,         -- 모델 식별자
    vector_dimension    INTEGER NOT NULL,              -- 벡터 차원수
    distance_metric     VARCHAR(20) NOT NULL DEFAULT 'Cosine',  -- Cosine | Dot | Euclid

    -- Qdrant 연결 정보
    qdrant_collection_name VARCHAR(200) NOT NULL,      -- Qdrant 내 실제 이름

    -- 통계 (캐시, 주기적 갱신)
    document_count      INTEGER NOT NULL DEFAULT 0,
    chunk_count         INTEGER NOT NULL DEFAULT 0,
    vector_count        INTEGER NOT NULL DEFAULT 0,
    last_indexed_at     TIMESTAMPTZ,

    -- 접근 제어
    is_public           BOOLEAN NOT NULL DEFAULT false,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ
);

CREATE UNIQUE INDEX idx_collections_slug ON collections(slug) WHERE deleted_at IS NULL;
CREATE INDEX idx_collections_owner ON collections(owned_by) WHERE deleted_at IS NULL;
```

---

### 3-5. `collection_documents`

컬렉션 ↔ 문서 M:N 관계. 문서 하나가 여러 컬렉션에 인덱싱될 수 있음.

```sql
CREATE TYPE index_status AS ENUM ('PENDING', 'INDEXED', 'FAILED', 'REMOVED');

CREATE TABLE collection_documents (
    collection_id   UUID NOT NULL REFERENCES collections(id),
    document_id     UUID NOT NULL REFERENCES documents(id),

    status          index_status NOT NULL DEFAULT 'PENDING',
    indexed_at      TIMESTAMPTZ,
    chunk_count     INTEGER,

    PRIMARY KEY (collection_id, document_id)
);

CREATE INDEX idx_col_docs_document ON collection_documents(document_id);
```

---

### 3-6. `chunks_meta`

청크 메타데이터 캐시. 실제 벡터는 Qdrant에 있고, 여기서는 검색 결과 조회 시 빠른 참조를 위한 메타만 저장.

```sql
CREATE TYPE chunk_type AS ENUM (
    'section', 'paragraph', 'table', 'figure', 'fact', 'record'
);

CREATE TABLE chunks_meta (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id         UUID NOT NULL REFERENCES documents(id),
    collection_id       UUID NOT NULL REFERENCES collections(id),

    chunk_index         INTEGER NOT NULL,             -- 문서 내 청크 순서
    chunk_type          chunk_type NOT NULL,
    qdrant_point_id     UUID NOT NULL,               -- Qdrant point ID (동일)

    -- 원본 위치 추적 (provenance)
    section_id          VARCHAR(50),                 -- 소속 섹션 ID
    block_ids           VARCHAR(50)[],               -- 소속 블록 ID 목록
    page_numbers        INTEGER[],                   -- 포함된 페이지 번호

    -- 청크 내용 요약 (전체 텍스트는 Qdrant payload에)
    text_preview        VARCHAR(500),                -- 처음 500자 미리보기
    token_count         INTEGER,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_chunks_document ON chunks_meta(document_id);
CREATE INDEX idx_chunks_collection ON chunks_meta(collection_id);
CREATE INDEX idx_chunks_qdrant ON chunks_meta(qdrant_point_id);
```

---

### 3-7. `golden_queries`

컬렉션별 검색 품질 평가를 위한 (질문, 기대 문서) 쌍 저장. (task #64)

```sql
CREATE TABLE golden_queries (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_id           UUID NOT NULL REFERENCES collections(id),
    query                   TEXT NOT NULL,
    expected_document_ids   JSON NOT NULL,  -- list[str] of Document UUIDs
    created_by              UUID NOT NULL REFERENCES users(id),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_golden_queries_collection ON golden_queries(collection_id);
```

---

### 3-8. `golden_eval_runs`

골든 쿼리 세트를 한 번 실행한 결과. 정밀도/재현율 기록. (task #64)

```sql
CREATE TABLE golden_eval_runs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_id     UUID NOT NULL REFERENCES collections(id),
    created_by        UUID NOT NULL REFERENCES users(id),
    top_k             INTEGER NOT NULL,               -- 평가 시 조회 상위 K개
    mean_precision    FLOAT NOT NULL,                -- 전체 쿼리의 정밀도 평균
    mean_recall       FLOAT NOT NULL,                -- 전체 쿼리의 재현율 평균
    results           JSON NOT NULL,  -- [{golden_query_id, query, expected_ids, retrieved_ids, precision, recall}, ...]
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_eval_runs_collection ON golden_eval_runs(collection_id);
```

---

### 3-7. `refinement_sets`

사용자가 제출한 정제 명령어 집합. 비파괴 원칙: 원본 StructuredDocument는 변경하지 않음.

```sql
CREATE TYPE refinement_status AS ENUM (
    'DRAFT',       -- 편집 중
    'SUBMITTED',   -- 제출됨, 처리 대기
    'APPLIED',     -- 적용 완료
    'FAILED'       -- 적용 실패
);

CREATE TABLE refinement_sets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL REFERENCES documents(id),
    submitted_by    UUID NOT NULL REFERENCES users(id),

    status          refinement_status NOT NULL DEFAULT 'DRAFT',
    version         INTEGER NOT NULL DEFAULT 1,    -- 동일 문서 여러 번 정제 시 증가

    -- 정제 명령어 목록 (refinement.md §6 명령어 형식)
    operations      JSONB NOT NULL DEFAULT '[]',

    -- 처리 결과
    applied_at      TIMESTAMPTZ,
    error_message   TEXT,
    affected_block_count INTEGER,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_refinements_document ON refinement_sets(document_id);
```

**operations JSONB 예시:**
```json
[
  {"op": "block_remove", "block_id": "blk_0042"},
  {"op": "block_role_change", "block_id": "blk_0043", "new_role": "heading"},
  {"op": "table_header_override", "table_id": "tbl_0001", "header_rows": 2}
]
```

---

### 3-8. `export_artifacts`

내보내기 번들 기록.

```sql
CREATE TYPE export_format AS ENUM (
    'canonical_json', 'review_md', 'chunks_jsonl',
    'records_jsonl', 'facts_jsonl', 'diagnostics_json', 'full_bundle'
);

CREATE TABLE export_artifacts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL REFERENCES documents(id),
    exported_by     UUID NOT NULL REFERENCES users(id),

    format          export_format NOT NULL,
    storage_path    VARCHAR(1000) NOT NULL,   -- MinIO 경로
    file_size_bytes BIGINT,
    checksum_md5    VARCHAR(32),

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_exports_document ON export_artifacts(document_id);
```

---

## 4. 공통 트리거

```sql
-- updated_at 자동 갱신 트리거 (모든 테이블에 적용)
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 각 테이블에 트리거 등록 (예시)
CREATE TRIGGER trg_documents_updated
    BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```

---

## 5. 인덱스 전략 요약

| 테이블 | 주요 조회 패턴 | 인덱스 |
|--------|--------------|--------|
| `documents` | status별 조회, 컬렉션별 조회 | `(status)`, `(target_collection_id)` |
| `processing_jobs` | document_id별 최신 job | `(document_id, created_at DESC)` |
| `collections` | slug 조회, owner 조회 | `(slug)` unique, `(owned_by)` |
| `chunks_meta` | document_id별 청크 목록 | `(document_id, chunk_index)` |
| `refinement_sets` | document_id별 최신 정제 | `(document_id, version DESC)` |

---

## 6. 마이그레이션 전략

- 마이그레이션 도구: **Alembic** (SQLAlchemy 연동)
- 마이그레이션 파일: `src/db/migrations/` 디렉토리
- 배포 시 자동 적용: `alembic upgrade head`
- 롤백: `alembic downgrade -1`
- 하위 호환성: 컬럼 추가는 DEFAULT 또는 NULLABLE로만
