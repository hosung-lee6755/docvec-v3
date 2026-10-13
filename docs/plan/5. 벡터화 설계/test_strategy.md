# test_strategy.md
# Document Vectorization Platform - Test Strategy

## 1. 문서 목적

본 문서는 문서 벡터화 플랫폼의 단위/통합/E2E 테스트 전략, 커버리지 목표,
픽스처 설계, CI/CD 연동 방식을 정의한다.

---

## 2. 테스트 목표 및 현황

### 2.1 목표

| 목표 | 기준 |
|------|------|
| 코드 커버리지 | ≥ 80% (전체) |
| 핵심 파이프라인 커버리지 | ≥ 90% (parse, structure, chunk, embed 모듈) |
| API 엔드포인트 커버리지 | 100% (모든 라우트 포함) |
| 에러 코드 커버리지 | ≥ 70% (주요 에러 코드 시나리오) |

### 2.2 현황 (2026-07-10)

**후행 상태:** 테스트 커버리지가 목표에 한참 미달.

- **Backend 단위 테스트:** 6개 파일 (conftest.py, test_security.py, test_config.py, test_bm25_service.py, test_search_service.py)
- **Backend 통합 테스트:** 1개 파일 (test_health.py)
- **Frontend 테스트:** 0개 파일 (미구현)
- **전체 추정 커버리지:** < 20% (주요 utility 모듈만, 파이프라인/API 엔드포인트 대부분 미검증)

**권장 조치:** 향후 반복에서 우선순위 높음. 현재는 라이브 엔드투엔드 검증 및 수동 테스트에 의존.

---

## 3. 테스트 계층

### 3.1 단위 테스트 (Unit Tests)

**대상:** 개별 함수, 메서드, 모듈 (외부 의존성 목업)

**프레임워크:** `pytest` + `pytest-cov`

**범위:**

| 모듈 | 테스트 대상 |
|------|-----------|
| 어댑터 (PDF/HWP/HWPX/DOCX) | 텍스트 추출, 표 파싱, OCR 신호 계산 |
| `StructureReconstructionModule` | 헤딩 판정, 섹션 트리, 읽기 순서 |
| `RefinementApplicationModule` | 명령 적용, 불변 조건, 충돌 감지 |
| `SemanticNormalizationModule` | 수치/날짜/단위 정규화 규칙 |
| `ChunkGenerationModule` | 청크 분할, 토큰 계산, 오버랩 |
| `EmbeddingProvider` 어댑터 | 배치 처리, 벡터 차원, 재시도 로직 |
| `QualityEvaluationModule` | 품질 등급 계산, 경고 생성 |
| 에러 코드 분류기 | 코드 매핑, 심각도 판단 |

**예시:**

```python
# AAA 패턴
def test_date_normalization_korean():
    # Arrange
    normalizer = SemanticNormalizer()
    input_text = "2026년 1월 1일 회의가 있습니다."

    # Act
    result = normalizer.normalize(input_text)

    # Assert
    assert "2026-01-01" in result.normalized

def test_chunk_splits_at_max_tokens():
    # Arrange
    chunker = ChunkGenerator(options=ChunkingOptions(max_tokens=512))
    long_section = create_section_with_tokens(600)

    # Act
    chunks = chunker.generate_chunks(long_section)

    # Assert
    assert all(count_tokens(c.text) <= 512 for c in chunks)
    assert len(chunks) >= 2
```

### 3.2 통합 테스트 (Integration Tests)

**대상:** 모듈 간 연동, 데이터베이스, Celery 태스크, Redis, Qdrant

**프레임워크:** `pytest` + `pytest-asyncio` + `testcontainers`

**범위:**

| 테스트 그룹 | 범위 |
|-----------|------|
| 파이프라인 스테이지 연결 | ingest → parse → structure (실제 파일로 검증) |
| Celery 태스크 실행 | `task.delay()` → 완료 대기 → 결과 검증 |
| PostgreSQL CRUD | 8개 테이블 CRUD 연산 |
| Qdrant 연동 | 컬렉션 생성 → 업로드 → 검색 → 삭제 |
| FastAPI 엔드포인트 | `TestClient`로 모든 라우트 검증 |
| JWT 인증 흐름 | 로그인 → 토큰 발급 → 보호 라우트 접근 |
| MinIO 파일 저장 | 업로드 → 다운로드 → 삭제 |

**테스트 픽스처 (testcontainers 기반):**

```python
@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:16") as pg:
        yield pg

@pytest.fixture(scope="session")
def redis_container():
    with RedisContainer("redis:7") as redis:
        yield redis

@pytest.fixture(scope="session")
def qdrant_container():
    with QdrantContainer("qdrant/qdrant:latest") as qdrant:
        yield qdrant

@pytest.fixture(scope="session")
def minio_container():
    with MinioContainer("minio/minio:latest") as minio:
        yield minio
```

### 3.3 E2E 테스트 (End-to-End Tests)

**대상:** 사용자 중심 전체 플로우 (UI 포함 또는 API 레벨)

**프레임워크:**
- API 레벨 E2E: `pytest` + `httpx`
- UI 레벨 E2E: `Playwright`

**핵심 플로우:**

| 시나리오 | 검증 포인트 |
|---------|-----------|
| 문서 전체 처리 (FULL_AUTO) | 업로드 → INDEXED 상태 → Qdrant 벡터 존재 확인 |
| 문서 처리 (REVIEW_REQUIRED) | 업로드 → REVIEW_PENDING → 정제 제출 → INDEXED |
| 문서 검색 | Qdrant 검색 → 결과 반환 → 메타데이터 일치 |
| 인증 플로우 | 로그인 → 토큰 → 보호 리소스 접근 → 토큰 만료 → 갱신 |
| 컬렉션 관리 | 컬렉션 생성 → 문서 추가 → 검색 → 문서 제거 |
| 처리 실패 복구 | 의도적 실패 주입 → retry API → 재처리 완료 |

**API 레벨 E2E 예시:**

```python
async def test_full_auto_pipeline(async_client, sample_pdf_path):
    # 1. 문서 업로드
    with open(sample_pdf_path, "rb") as f:
        response = await async_client.post(
            "/api/v1/documents",
            files={"file": f},
            data={"pipeline_mode": "FULL_AUTO"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    assert response.status_code == 202
    doc_id = response.json()["data"]["document_id"]

    # 2. INDEXED 상태 대기 (폴링)
    await wait_for_status(async_client, doc_id, "INDEXED", timeout=300)

    # 3. Qdrant 검색 검증
    search_resp = await async_client.post(
        "/api/v1/search",
        json={"query": "테스트 문서 내용", "collection_ids": []},
    )
    results = search_resp.json()["data"]["results"]
    assert any(r["document_id"] == doc_id for r in results)
```

---

## 4. 테스트 픽스처 설계

### 4.1 테스트 문서 픽스처

`tests/fixtures/documents/` 디렉토리에 아래 파일을 보관한다.

| 파일 | 유형 | 목적 |
|------|------|------|
| `simple_text.pdf` | PDF (텍스트) | 기본 파싱 검증 |
| `scan_image.pdf` | PDF (스캔본) | OCR 트리거 검증 |
| `multipage_50.pdf` | PDF 50페이지 | 성능 기준 검증 |
| `complex_table.pdf` | PDF (복잡한 표) | 표 파싱 검증 |
| `korean_document.hwp` | HWP | HWP 어댑터 검증 |
| `modern_document.hwpx` | HWPX | HWPX 어댑터 검증 |
| `word_document.docx` | DOCX | DOCX 어댑터 검증 |
| `corrupted.pdf` | 손상된 PDF | 오류 처리 검증 |
| `empty.pdf` | 빈 PDF | 에지 케이스 검증 |
| `password_protected.pdf` | 암호화 PDF | 암호 오류 검증 |

### 4.2 RawParsedDocument 픽스처

```python
@pytest.fixture
def raw_parsed_document():
    return RawParsedDocument(
        document_id="test-doc-001",
        source_format="pdf",
        file_hash="abc123",
        page_count=3,
        pages=[...],  # 테스트용 페이지 데이터
        document_metadata={"author": "Test Author"},
        adapter_id="pdf",
        parse_warnings=[],
    )
```

### 4.3 ProcessingOptions 픽스처

```python
@pytest.fixture
def default_options():
    return ProcessingOptions()

@pytest.fixture
def ocr_disabled_options():
    return ProcessingOptions(
        ocr=OcrOptions(engine=OcrEngine.DISABLED)
    )

@pytest.fixture
def review_required_options():
    return ProcessingOptions(
        pipeline_mode=PipelineMode.REVIEW_REQUIRED
    )
```

---

## 5. 모킹 전략

### 5.1 단위 테스트 모킹 원칙

- 외부 서비스(Qdrant, OpenAI API, MinIO)는 **항상 목업**
- 데이터베이스는 단위 테스트에서 **목업** (통합 테스트에서는 실제 컨테이너)
- 파일 시스템은 `tmp_path` fixture 활용

### 5.2 임베딩 모델 모킹

단위 테스트에서 BGE-m3 모델 로딩을 피하기 위해:

```python
@pytest.fixture
def mock_bge_provider(mocker):
    mock = mocker.patch("app.embedding.BgeM3Provider.encode")
    mock.return_value = np.random.rand(32, 1024).tolist()
    return mock
```

### 5.3 Celery 태스크 테스트

통합 테스트에서는 `CELERY_TASK_ALWAYS_EAGER=True` 설정으로 동기 실행:

```python
@pytest.fixture
def celery_config():
    return {"task_always_eager": True}
```

---

## 6. 어댑터별 테스트 요구 사항

각 어댑터는 아래 5개 케이스를 필수로 테스트한다.

| 케이스 | 검증 항목 |
|--------|---------|
| 정상 문서 | `RawParsedDocument` 필드 완전성, 텍스트 추출 정확도 |
| 빈 문서 | `EmptyDocumentError` 발생 또는 빈 페이지 반환 |
| 손상된 문서 | `CorruptedFileError` 발생 |
| 암호화된 문서 | `PasswordProtectedError` 발생 |
| OCR 필요 문서 | `native_text_coverage < 0.3` 신호 정확도 |

---

## 7. 정규화 규칙 테스트

### 7.1 한국어 정규화 규칙별 테스트 케이스

| 규칙 | 입력 예시 | 기대 출력 |
|------|---------|---------|
| 날짜 정규화 | `2026년 1월 1일` | `2026-01-01` |
| 날짜 정규화 | `26.1.1` | `2026-01-01` |
| 수치 정규화 | `1억 5천만` | `150000000` |
| 단위 정규화 | `100㎞` | `100 km` |
| 단위 정규화 | `30℃` | `30°C` |
| 전각 변환 | `１２３ＡＢＣ` | `123ABC` |
| 공백 정규화 | `A  B` | `A B` |

---

## 8. API 테스트 요구 사항

### 8.1 인증 테스트

- `POST /auth/login`: 올바른 자격 증명 → 200 + 토큰 반환
- `POST /auth/login`: 잘못된 자격 증명 → 401
- `POST /auth/refresh`: 유효한 리프레시 쿠키 → 새 액세스 토큰
- `POST /auth/refresh`: 만료된 쿠키 → 401
- 보호 라우트 → 토큰 없이 접근 → 401
- viewer 역할 → PATCH /documents 접근 → 403

### 8.2 문서 API 테스트

- 지원 포맷 업로드 → 202 + document_id
- 미지원 포맷 업로드 → 422 (VALID_E_003)
- 파일 크기 초과 → 422 (VALID_E_002)
- 존재하지 않는 document_id 조회 → 404
- 권한 없는 문서 조회 → 403

### 8.3 검색 API 테스트

- 정상 검색 → 200 + 결과 목록
- 빈 쿼리 → 422
- 존재하지 않는 collection_id 필터 → 200 + 빈 결과

---

## 9. 성능 테스트

### 9.1 부하 테스트 (Load Test)

**도구:** `locust`

**시나리오:**

| 시나리오 | 목표 |
|---------|------|
| 동시 문서 업로드 10건 | 모두 202 응답, 큐 적재 확인 |
| 동시 검색 요청 50건 | P95 ≤ 300ms |
| WebSocket 동시 연결 100개 | 연결 유지, 메시지 손실 없음 |

### 9.2 기준 성능 테스트 (Baseline Test)

CI/CD에서 매 배포 시 자동 실행:

- 표준 50페이지 PDF 처리 시간 측정
- 이전 릴리즈 대비 20% 이상 저하 시 경고

---

## 10. CI/CD 통합

### 10.1 GitHub Actions 워크플로우

```yaml
# .github/workflows/test.yml
jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - pytest tests/unit/ --cov=app --cov-report=xml
      - coverage check --fail-under=80

  integration:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
      redis:
        image: redis:7
      qdrant:
        image: qdrant/qdrant:latest
      minio:
        image: minio/minio:latest
    steps:
      - pytest tests/integration/ --timeout=120

  e2e:
    runs-on: ubuntu-latest
    steps:
      - docker-compose up -d  # 전체 스택
      - pytest tests/e2e/ --timeout=300
      - docker-compose down
```

### 10.2 테스트 실행 환경 분리

| 환경 | 실행 조건 | 포함 테스트 |
|------|---------|-----------|
| local | 개발 중 수시 | unit |
| CI (PR) | PR 생성/업데이트 | unit + integration |
| CI (main) | main 브랜치 머지 | unit + integration + e2e |
| staging | 배포 전 | unit + integration + e2e + load |

---

## 11. 테스트 디렉토리 구조

### 11.1 설계 목표 구조 (aspirational)

```
tests/
├── unit/
│   ├── adapters/
│   │   ├── test_pdf_adapter.py
│   │   ├── test_hwp_adapter.py
│   │   ├── test_hwpx_adapter.py
│   │   └── test_docx_adapter.py
│   ├── modules/
│   │   ├── test_structure_reconstruction.py
│   │   ├── test_refinement_application.py
│   │   ├── test_semantic_normalization.py
│   │   ├── test_chunk_generation.py
│   │   └── test_quality_evaluation.py
│   ├── embedding/
│   │   ├── test_bge_provider.py
│   │   ├── test_openai_provider.py
│   │   └── test_e5_provider.py
│   └── utils/
│       ├── test_language_normalization.py
│       └── test_error_codes.py
├── integration/
│   ├── test_pipeline_stages.py
│   ├── test_celery_tasks.py
│   ├── test_api_documents.py
│   ├── test_api_auth.py
│   ├── test_api_search.py
│   ├── test_qdrant_integration.py
│   └── test_minio_storage.py
├── e2e/
│   ├── test_full_auto_pipeline.py
│   ├── test_review_required_pipeline.py
│   ├── test_search_flow.py
│   └── test_auth_flow.py
└── fixtures/
    ├── documents/
    │   ├── simple_text.pdf
    │   ├── scan_image.pdf
    │   └── ...
    ├── conftest.py      # 공통 픽스처
    └── factories.py     # 테스트 객체 팩토리
```

### 11.2 실제 구조 (2026-07-10)

```
backend/tests/
├── conftest.py
├── unit/
│   ├── test_security.py
│   ├── test_config.py
│   └── test_bm25_service.py
└── integration/
    ├── test_health.py
    └── test_search_service.py

frontend/
└── (테스트 없음 — 라이브 E2E 검증에만 의존)
```

**현황:** 어댑터, 파이프라인 모듈, API 엔드포인트에 대한 체계적인 테스트가 미구현 상태.
주로 utility (security, config, BM25) 모듈만 커버됨.

---

## 12. 크로스레퍼런스

- adapter_interface_spec (어댑터 테스트 요구 사항)
- error_codes (에러 코드 커버리지 목표)
- performance_spec (성능 기준 — P95 목표)
- api_design (API 엔드포인트 테스트 매핑)
- config_schema (테스트용 ProcessingOptions 픽스처)
