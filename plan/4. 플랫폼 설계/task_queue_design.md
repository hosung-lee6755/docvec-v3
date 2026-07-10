# Celery 태스크 큐 설계

## 1. 개요

문서 처리 파이프라인은 시간이 오래 걸리는 CPU/IO 집약적 작업이므로  
API 서버와 분리된 **Celery Worker**에서 비동기 실행한다.  
태스크 정의는 파이프라인 스테이지와 1:1 대응하며, **Celery Chain**으로 순서 보장.

---

## 2. 인프라 구성

```
FastAPI → Redis Broker → Celery Worker(s)
                    ↑
              Result Backend (Redis)
              
채널 구성:
  - redis://redis:6379/0   # Celery Broker
  - redis://redis:6379/1   # Celery Result Backend
  - redis://redis:6379/2   # WebSocket PubSub (진행 상황 push)
```

---

## 3. 큐(Queue) 설계

| 큐 이름 | 우선순위 | 워커 유형 | 용도 |
|---------|---------|----------|------|
| `critical` | 0 (최고) | CPU | 긴급 우선 처리 |
| `high` | 1 | CPU | 단일 문서 즉시 처리 요청 |
| `normal` | 2 | CPU | 일반 문서 처리 |
| `embed` | 2 | GPU/CPU | 임베딩 생성 + 재임베딩 (task #63) |
| `low` | 4 (최저) | CPU | 배경 작업 (재임베딩, 요약) |

**주의:** `default` 큐는 존재하지 않습니다. 작업이 `queue="default"`로 선언되면 실행되지 않는 버그가 발생합니다 (task #63에서 수정됨).

**Celery 설정:**
```python
CELERY_TASK_ROUTES = {
    'tasks.embed_task': {'queue': 'embedding'},
    'tasks.qdrant_upload_task': {'queue': 'upload'},
    'tasks.*': {'queue': 'default'},
}

CELERY_WORKER_CONCURRENCY = 4       # CPU 워커
CELERY_WORKER_CONCURRENCY_GPU = 1   # GPU 워커 (임베딩)
```

---

## 4. 태스크 정의

### 4-1. `ingest_task`

```python
@app.task(
    name='tasks.ingest_task',
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    acks_late=True
)
def ingest_task(self, doc_id: str) -> dict:
    """
    입력:  doc_id (documents.id)
    출력:  {"doc_id": str, "raw_doc_path": str, "format": str}
    
    처리:
    1. DB에서 document 조회 (storage_path)
    2. MinIO에서 원본 파일 다운로드
    3. DocumentIngestModule.ingest() → InputDocument
    4. AdapterResolutionModule → 포맷별 어댑터 선택
    5. NativeParseModule.parse() → RawParsedDocument
    6. RawParsedDocument → MinIO /artifacts/{doc_id}/raw_parsed.json 저장
    7. DB: status=PARSING 업데이트
    """
```

**재시도 조건:**
- 파일 읽기 오류 (네트워크 일시 오류): 자동 재시도 3회
- 지원 불가 포맷: 재시도 없이 FAILED

---

### 4-2. `structure_task`

```python
@app.task(
    name='tasks.structure_task',
    bind=True,
    max_retries=2,
    soft_time_limit=300,   # 5분 소프트 제한
    time_limit=360         # 6분 하드 제한
)
def structure_task(self, ingest_result: dict) -> dict:
    """
    입력:  ingest_task 결과 dict
    출력:  {"doc_id": str, "structured_doc_path": str}
    
    처리:
    1. RawParsedDocument MinIO에서 로드
    2. StructureReconstructionModule.reconstruct()
       - BlockSegmenter → BlockClassifier → ReadingOrderResolver
       - SectionTreeBuilder → TableReconstructor → FigureLinker
    3. StructuredDocument → MinIO /artifacts/{doc_id}/structured.json
    4. DB: status=STRUCTURING → REVIEW_PENDING (또는 REFINING if FULL_AUTO)
    """
```

**시간 제한 처리:**
- `SoftTimeLimitExceeded` 발생 시: 현재까지 처리된 결과 저장 후 종료
- 하드 제한 초과 시: FAILED 처리, 에러 코드 `TIMEOUT_STRUCTURE`

---

### 4-3. `review_prep_task`

```python
@app.task(name='tasks.review_prep_task', bind=True)
def review_prep_task(self, structure_result: dict) -> dict:
    """
    입력:  structure_task 결과 dict
    출력:  {"doc_id": str, "review_bundle_path": str, "low_confidence_count": int}
    
    처리:
    1. StructuredDocument 로드
    2. ReviewBundleGenerationModule.generate() → ReviewBundle
    3. ReviewBundle → MinIO /artifacts/{doc_id}/review_bundle.json
    4. ReviewBundle의 review.md → MinIO /artifacts/{doc_id}/review.md
    5. DB: status=REVIEW_PENDING
    6. Redis PubSub: publish("doc:{doc_id}", {"status": "REVIEW_PENDING"})
    """
```

**FULL_AUTO 모드:**
- 이 태스크를 건너뛰고 `refine_task`(빈 RefinementSet으로)로 직행

---

### 4-4. `refine_task`

```python
@app.task(name='tasks.refine_task', bind=True, max_retries=2)
def refine_task(self, doc_id: str, refinement_set_id: str = None) -> dict:
    """
    입력:  doc_id, refinement_set_id (None이면 빈 RefinementSet 사용)
    출력:  {"doc_id": str, "refined_doc_path": str}
    
    처리:
    1. StructuredDocument + RefinementSet 로드
    2. RefinementApplicationModule.apply()
    3. PostRefinementRecomputeModule.recompute()
    4. RefinedDocument → MinIO /artifacts/{doc_id}/refined.json
    5. DB: status=NORMALIZING
    """
```

---

### 4-5. `normalize_task`

```python
@app.task(name='tasks.normalize_task', bind=True, soft_time_limit=180)
def normalize_task(self, refine_result: dict) -> dict:
    """
    입력:  refine_task 결과 dict
    출력:  {"doc_id": str, "canonical_doc_path": str}
    
    처리:
    1. RefinedDocument 로드
    2. SemanticNormalizationModule.normalize()
       - TextNormalizer, NumericNormalizer, DateNormalizer
       - HeaderPathBuilder, RecordBuilder, FactBuilder, EntityExtractor
    3. QualityEvaluationModule.evaluate() → DocumentQuality
    4. CanonicalDocument → MinIO /artifacts/{doc_id}/canonical.json
    5. DB: quality_score, status=CHUNKING 업데이트
    """
```

---

### 4-6. `chunk_task`

```python
@app.task(name='tasks.chunk_task', bind=True)
def chunk_task(self, normalize_result: dict) -> dict:
    """
    입력:  normalize_task 결과 dict
    출력:  {"doc_id": str, "chunks_path": str, "chunk_count": int}
    
    처리:
    1. CanonicalDocument 로드
    2. ChunkGenerationModule.generate()
       - SectionChunker, ParagraphChunker, TableChunker, FigureChunker, FactChunker
    3. Chunks[] → MinIO /artifacts/{doc_id}/chunks.jsonl
    4. DB: total_chunks 업데이트, status=EMBEDDING
    """
```

---

### 4-7. `embed_task`

임베딩 전용 큐에서 실행. GPU 워커 지원.

```python
@app.task(
    name='tasks.embed_task',
    bind=True,
    queue='embedding',
    soft_time_limit=600,   # 10분
    max_retries=2
)
def embed_task(self, chunk_result: dict, collection_id: str) -> dict:
    """
    입력:  chunk_task 결과 dict, collection_id
    출력:  {"doc_id": str, "embedded_chunks_path": str, "chunk_count": int}
    
    처리:
    1. Collection 조회 → embedding_provider, embedding_model 확인
    2. EmbeddingPluginRegistry.get(provider) → EmbeddingProvider
    3. chunks.jsonl 로드
    4. EmbeddingProvider.embed_batch(texts, batch_size=64)
    5. 각 청크에 vector 필드 추가
    6. embedded_chunks.jsonl → MinIO /artifacts/{doc_id}/embedded_chunks.jsonl
    7. DB: status=UPLOADING
    
    배치 처리:
    - 배치 크기: 64 (설정 가능)
    - 진행률 업데이트: 배치마다 Redis PubSub publish
    """
```

---

### 4-8. `qdrant_upload_task`

```python
@app.task(
    name='tasks.qdrant_upload_task',
    bind=True,
    queue='upload',
    max_retries=3,
    default_retry_delay=60
)
def qdrant_upload_task(self, embed_result: dict, collection_id: str) -> dict:
    """
    입력:  embed_task 결과 dict, collection_id
    출력:  {"doc_id": str, "uploaded_count": int}
    
    처리:
    1. Collection 조회 → qdrant_collection_name
    2. embedded_chunks.jsonl 로드
    3. QdrantClient.upsert(
           collection_name=...,
           points=[PointStruct(
               id=chunk.chunk_id,       # UUID
               vector=chunk.vector,
               payload={
                   "doc_id": ...,
                   "collection_id": ...,
                   "chunk_type": ...,
                   "text": ...,
                   "section_title": ...,
                   "page_numbers": [...],
                   "block_ids": [...],
                   "metadata": {...}
               }
           )]
       )
    4. chunks_meta 테이블에 메타데이터 삽입 (배치)
    5. collection_documents.status = INDEXED
    6. collections.chunk_count, vector_count 업데이트
    7. DB: documents.status = INDEXED
    8. Redis PubSub: publish("doc:{doc_id}", {"status": "INDEXED"})
    
    업로드 배치 크기: 100 points/batch
    """
```

---

## 5. 파이프라인 체이닝

Celery Chain으로 스테이지 순서 보장.

```python
def create_processing_chain(doc_id: str, collection_id: str, mode: str) -> chain:
    """문서 처리 Chain 생성"""

    if mode == 'FULL_AUTO':
        return chain(
            ingest_task.s(doc_id),
            structure_task.s(),
            refine_task.s(doc_id, refinement_set_id=None),  # 빈 정제
            normalize_task.s(),
            chunk_task.s(),
            embed_task.s(collection_id),
            qdrant_upload_task.s(collection_id)
        )
    
    elif mode == 'REVIEW_REQUIRED':
        # review_prep_task 이후 중단 → 사용자 정제 완료 후 refine_task부터 재개
        return chain(
            ingest_task.s(doc_id),
            structure_task.s(),
            review_prep_task.s()
        )
    
    # 정제 제출 후 이어서 실행하는 체인
def create_post_review_chain(doc_id: str, refinement_set_id: str, collection_id: str) -> chain:
    return chain(
        refine_task.s(doc_id, refinement_set_id),
        normalize_task.s(),
        chunk_task.s(),
        embed_task.s(collection_id),
        qdrant_upload_task.s(collection_id)
    )
```

---

## 6. 실패 처리 전략

### 6-1. 재시도 가능 오류

| 오류 유형 | 재시도 | 간격 |
|-----------|--------|------|
| 네트워크 오류 (MinIO, Qdrant) | 3회 | 30s, 60s, 120s (지수 백오프) |
| 임베딩 API 오류 (Rate Limit) | 3회 | 60s, 120s, 300s |
| DB 연결 오류 | 3회 | 5s |

### 6-2. 재시도 불가 오류

| 오류 유형 | 처리 |
|-----------|------|
| 지원 불가 파일 포맷 | FAILED, `ERR_FORMAT_UNSUPPORTED` |
| 파일 손상 | FAILED, `ERR_FILE_CORRUPTED` |
| 처리 시간 초과 | FAILED, `ERR_TIMEOUT_*` |
| 메모리 부족 | FAILED, `ERR_OOM` |

### 6-3. 부분 실패 복구

```
문서 처리 중 Stage 3에서 실패한 경우:
1. 해당 Stage까지의 artifact는 MinIO에 보존
2. documents.failed_stage = 'normalize'로 기록
3. 관리자/사용자가 해당 Stage부터 재시작 가능
   → POST /api/v1/documents/{id}/retry?from_stage=normalize
```

---

## 7. 진행률 실시간 전달

```python
# 태스크 내에서 진행률 업데이트
def _publish_progress(doc_id: str, stage: str, progress: float, message: str):
    redis_client.publish(
        f"doc_progress:{doc_id}",
        json.dumps({
            "doc_id": doc_id,
            "stage": stage,
            "progress": progress,      # 0.0 ~ 1.0
            "message": message,
            "timestamp": time.time()
        })
    )

# FastAPI WebSocket 엔드포인트에서 구독
@app.websocket("/ws/documents/{doc_id}/progress")
async def document_progress(websocket: WebSocket, doc_id: str):
    await websocket.accept()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(f"doc_progress:{doc_id}")
    async for message in pubsub.listen():
        if message['type'] == 'message':
            await websocket.send_text(message['data'])
```

---

## 8. 배치 처리

여러 문서를 한 번에 처리하는 배치 작업.

```python
@app.task(name='tasks.batch_process_task', queue='batch')
def batch_process_task(doc_ids: list[str], collection_id: str, mode: str):
    """
    여러 문서를 병렬로 처리 (Celery Group + Chord)
    
    처리:
    1. 각 doc_id에 대한 processing chain 생성
    2. Celery group으로 병렬 실행 (최대 동시 실행: CELERY_WORKER_CONCURRENCY)
    3. 전체 완료 후 batch_summary_task 실행 (Chord)
    """
    job_group = group(
        create_processing_chain(doc_id, collection_id, mode)
        for doc_id in doc_ids
    )
    chord(job_group)(batch_summary_task.s(doc_ids, collection_id))
```

---

## 9. 모니터링

| 도구 | 목적 | 접근 |
|------|------|------|
| **Flower** | Celery 태스크 실시간 모니터링 | `http://localhost:5555` |
| **Redis Monitor** | 큐 길이, 메모리 사용량 | Redis CLI / 관리 UI |
| **DB processing_jobs** | 히스토리 조회, 실패 분석 | API `GET /api/v1/admin/jobs` |
