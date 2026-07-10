# performance_spec.md
# Document Vectorization Platform - Performance Specification

## 1. 문서 목적

본 문서는 문서 처리 파이프라인과 플랫폼 전반에 대한 SLA(Service Level Agreement) 목표,
동시성 모델, 리소스 제한, 성능 측정 지표를 정의한다.

---

## 2. 문서 처리 SLA 목표

### 2.1 파이프라인 처리 시간 (단일 문서, 우선순위 normal)

| 문서 유형 | 크기 기준 | 목표 처리 시간 (P95) | 최대 허용 시간 |
|---------|---------|---------------------|--------------|
| PDF (텍스트 레이어) | ≤ 10페이지 | ≤ 30초 | 120초 |
| PDF (텍스트 레이어) | 11–50페이지 | ≤ 90초 | 300초 |
| PDF (텍스트 레이어) | 51–200페이지 | ≤ 300초 | 600초 |
| PDF (스캔본 — OCR 필요) | ≤ 10페이지 | ≤ 120초 | 300초 |
| PDF (스캔본 — OCR 필요) | 11–50페이지 | ≤ 400초 | 900초 |
| HWP/HWPX | ≤ 50페이지 | ≤ 60초 | 180초 |
| HWP/HWPX | 51–200페이지 | ≤ 180초 | 600초 |
| DOCX | ≤ 50페이지 | ≤ 45초 | 120초 |
| DOCX | 51–200페이지 | ≤ 120초 | 360초 |

**P95**: 95번째 백분위수 — 전체 요청 중 95%가 해당 시간 이내 완료.

### 2.2 스테이지별 처리 시간 목표

| 스테이지 | 담당 태스크 | 목표 시간 (P95, 50페이지 기준) |
|---------|-----------|------------------------------|
| Ingest + Parse | `ingest_task` | ≤ 15초 |
| Structure | `structure_task` | ≤ 20초 |
| Review Prep | `review_prep_task` | ≤ 10초 |
| Refine | `refine_task` | ≤ 10초 |
| Normalize | `normalize_task` | ≤ 15초 |
| Chunk | `chunk_task` | ≤ 5초 |
| Embed (BGE-m3, CPU) | `embed_task` | ≤ 60초 |
| Embed (BGE-m3, GPU) | `embed_task` | ≤ 10초 |
| Qdrant Upload | `qdrant_upload_task` | ≤ 15초 |

---

## 3. API 응답 시간 SLA

| 엔드포인트 유형 | 목표 (P95) | 최대 허용 |
|--------------|-----------|---------|
| 문서 업로드 (`POST /documents`) | ≤ 500ms | 2초 |
| 문서 목록 조회 | ≤ 200ms | 1초 |
| 문서 상태 조회 | ≤ 100ms | 500ms |
| 검색 쿼리 (Qdrant) | ≤ 300ms | 1초 |
| WebSocket 연결 수립 | ≤ 200ms | 1초 |
| 정제 명령 제출 | ≤ 300ms | 1초 |
| 컬렉션 관리 | ≤ 200ms | 1초 |

---

## 4. 동시성 모델

### 4.1 Celery Worker 구성

```
[Celery Queues]
  critical  (priority 10) ← 관리자 요청, 소형 문서
  high      (priority 8)  ← 빠른 처리 플랜
  normal    (priority 5)  ← 기본
  low       (priority 3)  ← 배치 처리
  embed     (priority 5)  ← 임베딩 전용 (GPU 워커 분리 가능)
```

### 4.2 Worker 인스턴스 권장 사양

| Worker 유형 | 수량 (기본) | Concurrency | 큐 구독 |
|------------|-----------|-------------|--------|
| General Worker | 2–4 | prefork, 4 processes | critical, high, normal, low |
| Embed Worker (CPU) | 1–2 | solo (1 process) | embed |
| Embed Worker (GPU) | 0–1 (옵션) | solo (1 process) | embed |

**Concurrency 선택 근거:**
- Ingest/Structure/Normalize는 CPU-bound I/O 혼합 → prefork
- Embed는 모델 로딩 후 배치 처리 → solo (메모리 공유 불필요, 모델 재로딩 방지)

### 4.3 동시 처리 문서 수 제한

| 큐 | 동시 처리 문서 수 | 비고 |
|----|-----------------|------|
| critical | 최대 4 | 빠른 응답 보장 |
| normal | 최대 8 | 일반 처리 |
| embed | 최대 2 (CPU) / 1 (GPU) | 메모리 초과 방지 |

### 4.4 태스크 타임아웃 설정

| 태스크 | soft_time_limit | hard_time_limit |
|--------|----------------|-----------------|
| `ingest_task` | 300초 | 360초 |
| `structure_task` | 600초 | 720초 |
| `review_prep_task` | 120초 | 150초 |
| `refine_task` | 180초 | 240초 |
| `normalize_task` | 300초 | 360초 |
| `chunk_task` | 120초 | 150초 |
| `embed_task` | 1800초 | 2100초 |
| `qdrant_upload_task` | 300초 | 360초 |

- `soft_time_limit`: `SoftTimeLimitExceeded` 예외 발생 → 정상 종료 처리
- `hard_time_limit`: 강제 프로세스 종료

---

## 5. 리소스 제한

### 5.1 파일 크기 제한

| 포맷 | 최대 파일 크기 | 최대 페이지 수 |
|------|--------------|--------------|
| PDF | 200 MB | 500페이지 |
| HWP | 100 MB | 300페이지 |
| HWPX | 100 MB | 300페이지 |
| DOCX | 100 MB | 300페이지 |

- 제한 초과 시: `VALID_E_002` (파일 크기 초과) 에러 반환
- 대형 문서 처리가 필요한 경우: 관리자 설정으로 상한 조정 가능

### 5.2 메모리 사용 제한

| 컴포넌트 | 메모리 제한 |
|---------|-----------|
| General Worker 프로세스 1개 | 2 GB |
| Embed Worker (BGE-m3 CPU) | 6 GB |
| Embed Worker (BGE-m3 GPU) | GPU VRAM 4 GB |
| FastAPI 프로세스 1개 | 1 GB |
| Qdrant | 권장 8 GB (인덱스 크기에 따라 증가) |

### 5.3 청크 수 제한

| 항목 | 제한값 |
|------|--------|
| 문서당 최대 청크 수 | 5,000개 |
| 문서당 최대 레코드 수 | 50,000개 |
| 문서당 최대 팩트 수 | 10,000개 |
| Qdrant 배치 업로드 크기 | 100개 포인트 |

---

## 6. Qdrant 성능 기준

### 6.1 검색 성능 목표

| 컬렉션 크기 | 검색 지연 (P95) | 설정 |
|------------|--------------|------|
| ≤ 100k 벡터 | ≤ 50ms | HNSW default |
| 100k–1M 벡터 | ≤ 100ms | HNSW m=16, ef=128 |
| 1M–10M 벡터 | ≤ 200ms | HNSW m=16, ef=64 |

### 6.2 HNSW 파라미터 권장값

```python
# qdrant_integration.md에서 정의된 파라미터
hnsw_config = HnswConfigDiff(
    m=16,              # 연결 수 — 메모리 vs 검색 품질 균형
    ef_construct=100,  # 인덱스 구성 시 탐색 깊이
)
# 검색 시 ef (ef_search) = 128 (precision) / 64 (speed)
```

### 6.3 페이로드 인덱스 활용 필터링 성능

| 필터 조합 | 예상 성능 |
|----------|---------|
| `doc_id` 단독 | ≤ 10ms |
| `collection_id` + `chunk_type` | ≤ 20ms |
| `doc_language` + `quality_score ≥ 0.7` | ≤ 30ms |
| `page_numbers` 범위 쿼리 | ≤ 50ms |

---

## 7. 성능 모니터링 지표

### 7.1 파이프라인 지표

| 지표 | 설명 | 알림 임계값 |
|------|------|-----------|
| `pipeline.task_duration_seconds` | 스테이지별 처리 시간 | P95 > 목표 2배 |
| `pipeline.queue_depth` | 큐별 대기 중 태스크 수 | > 50 |
| `pipeline.failure_rate` | 태스크 실패율 | > 5% (5분 평균) |
| `pipeline.retry_rate` | 재시도율 | > 10% |

### 7.2 임베딩 지표

| 지표 | 설명 | 알림 임계값 |
|------|------|-----------|
| `embed.tokens_per_second` | 임베딩 처리 속도 | < 500 tok/s (CPU 기준) |
| `embed.batch_queue_depth` | 임베딩 대기 배치 수 | > 10 |

### 7.3 API 지표

| 지표 | 설명 | 알림 임계값 |
|------|------|-----------|
| `api.request_duration_seconds` | API 응답 시간 | P95 > SLA 목표 |
| `api.error_rate_5xx` | 서버 오류율 | > 1% |
| `api.active_websocket_connections` | 활성 WebSocket 수 | > 500 |

---

## 8. 확장성 가이드라인

### 8.1 수평 확장

| 컴포넌트 | 수평 확장 방법 |
|---------|--------------|
| Celery General Worker | 인스턴스 추가 (stateless) |
| Celery Embed Worker | GPU 인스턴스 추가 |
| FastAPI | 인스턴스 추가 + 로드밸런서 |
| PostgreSQL | Read replica (읽기 부하 분산) |
| Qdrant | 클러스터 모드 (collection sharding) |
| Redis | Redis Sentinel (HA) |

### 8.2 처리량 예측 모델 (단일 General Worker 기준)

```
일일 처리 가능 문서 수 추정:
- 평균 문서: 50페이지 PDF (텍스트)
- 파이프라인 전체 시간: ~2분
- Worker 동시성: 4 processes
- 일 운영 시간: 24시간

  24 * 60 * 4 / 2 = 2,880 문서/일 (단일 워커)
  워커 4대: ~11,520 문서/일
```

### 8.3 임베딩 처리량 (BGE-m3)

| 환경 | 배치 크기 | 처리량 |
|------|---------|--------|
| CPU (4코어) | 32 | ~200 청크/분 |
| GPU (T4) | 128 | ~2,000 청크/분 |
| GPU (A100) | 256 | ~8,000 청크/분 |

---

## 9. 실제 구현 튜닝 상수

### 9.1 HWP/HWPX 페이지 재분할 (A10)

**`_REPAGINATE_ANCHOR_CHARS = 60`** (backend/app/pipeline/tasks/process.py:346)

LibreOffice 미리보기 PDF 텍스트와 매칭할 때 사용할 단락/표 텍스트의 선행 문자 수.
**이유:** 긴 앵커(예: 200자)는 HTML 재플로우 시 줄바꿈 차이로 매칭 실패 확률이 높음.
짧은 앵커(60자)는 재플로우 후에도 보존될 가능성이 높으면서도 평문 문서에서 충분히 고유함.

### 9.2 임베딩 및 청크 재중복 제거 (5c)

**`_DOC_DEDUP_MULTIPLIER = 5`** (backend/app/api/v1/endpoints/golden_queries.py:29)

청크 기반 Qdrant 검색에서 상위 `top_k * 5` 청크를 먼저 페치한 후,
같은 문서에 속한 중복을 제거하여 상위 `top_k` 개의 **서로 다른 문서**를 반환.
**이유:** 한 문서가 여러 상위 청크를 차지할 수 있으므로 나이브 limit=top_k로는 고유 문서 수가 부족.

### 9.3 ZIP 대량 업로드 안전 상한 (5a)

| 항목 | 값 |
|------|------|
| `_ZIP_MAX_ENTRIES` | 200개 |
| `_ZIP_MAX_ENTRY_UNCOMPRESSED_BYTES` | 200 MB |
| `_ZIP_MAX_TOTAL_UNCOMPRESSED_BYTES` | 2 GB |

(backend/app/api/v1/endpoints/documents.py:65-67)

**설계:** 집 폭탄(zip bomb) 및 경로 조회(path traversal) 공격 방지.
파일명은 `PurePosixPath(info.filename).name` 으로 정규화해 상위 디렉토리 탈출 차단.

---

## 10. 복잡도 상한 정의

### 10.1 단일 문서 복잡도 제한

| 측정 항목 | 경고 임계값 | 처리 중단 임계값 |
|---------|-----------|----------------|
| 총 블록 수 | 10,000개 | 50,000개 |
| 총 표 수 | 500개 | 2,000개 |
| 단일 표 셀 수 | 1,000개 | 5,000개 |
| 섹션 트리 깊이 | 10레벨 | 20레벨 |
| 총 이미지 수 | 200개 | 1,000개 |

### 10.2 복잡도 초과 시 처리

1. 경고 임계값 초과: `QUAL_W_*` 경고 기록, 처리 계속
2. 처리 중단 임계값 초과: `PARSE_E_005` (처리 타임아웃 초과) 에러로 처리
3. 권장 조치: 파일 분할 후 재업로드

---

## 11. 크로스레퍼런스

- task_queue_design (Celery 큐 우선순위, 태스크 정의)
- embedding_plugin_design (임베딩 배치 크기 설정)
- qdrant_integration (HNSW 파라미터, 인덱스 설정)
- config_schema (ProcessingOptions 타임아웃 설정)
- database_schema (processing_jobs 테이블 — 성능 이력 저장)
