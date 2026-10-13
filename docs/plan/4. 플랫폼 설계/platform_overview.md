# 플랫폼 전체 아키텍처 설계

## 1. 시스템 개요

이 플랫폼은 다양한 문서 형식(PDF, HWP, HWPX, DOCX)을 자동 파싱·정제하여  
벡터 DB(Qdrant)에 인덱싱하고, 이를 웹 UI에서 관리·검색할 수 있는 종합 시스템이다.

**핵심 가치 제안:**
- 비정형 문서 → 구조화 → 벡터 검색 가능한 지식 베이스로 변환
- 사람이 검토·수정할 수 있는 리뷰/정제 워크플로우 내장
- 임베딩 모델 교체 시 배경 재임베딩 (task #63), 골든 쿼리 세트로 검색 품질 평가 (task #64)
- 대량 ZIP 업로드 (task #62), 채팅 의도 라우팅 (task #59), 클라우드 검증 위임 (task #60)
- HWP/HWPX 실제 페이지 분할 (task #61), 청크 조회 통계 (task #58)

---

## 2. 시스템 컴포넌트

```
┌──────────────────────────────────────────────────────────────────┐
│                     Web Dashboard (React + TypeScript)            │
│                                                                    │
│  [문서 관리]  [리뷰/정제]  [컬렉션 관리]  [검색 테스트]  [시스템 관리]  │
└───────────────────────────┬──────────────────────────────────────┘
                            │ HTTPS / REST API
┌───────────────────────────▼──────────────────────────────────────┐
│                      FastAPI API Server                           │
│                                                                    │
│  /api/v1/documents    /api/v1/collections    /api/v1/search       │
│  /api/v1/jobs         /api/v1/refinements    /api/v1/admin        │
│                                                                    │
│  ┌─ Auth Middleware (JWT) ─┐  ┌─ CORS / Rate Limit ─┐           │
└──┬────────────────────────────────────────────────────┬───────────┘
   │                                                    │
   │ Celery Task Dispatch                               │ Direct Query
┌──▼──────────────────┐  ┌─────────────────┐  ┌───────▼──────────┐
│    Redis             │  │   PostgreSQL     │  │     Qdrant       │
│  ┌──────────────┐   │  │                  │  │                  │
│  │ Celery Broker│   │  │  documents       │  │  Collections     │
│  │ Task Queue   │   │  │  processing_jobs │  │  Vector Points   │
│  │ Result Store │   │  │  collections     │  │  Payload Filters │
│  │ WS PubSub    │   │  │  chunks_meta     │  │                  │
│  └──────────────┘   │  │  users           │  │                  │
└──────┬──────────────┘  │  refinement_sets │  └──────────────────┘
       │                 │  export_artifacts│
       │                 └─────────────────┘
┌──────▼──────────────────────────────────────────────────────────┐
│               Celery Workers (Document Processing)               │
│                                                                    │
│  Stage 1: Ingest      → RawParsedDocument                        │
│  Stage 2: Structure   → StructuredDocument                       │
│  Stage 3: Review Prep → ReviewBundle                             │
│  Stage 4: Refine      → RefinedDocument        ← 사용자 입력 대기  │
│  Stage 5: Normalize   → CanonicalDocument                        │
│  Stage 6: Chunk       → Chunks[]                                 │
│  Stage 7: Embed       → EmbeddedChunks[]  (EmbeddingPlugin)      │
│  Stage 8: Upload      → Qdrant Points                            │
└─────────────────────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────────┐
│                    File Storage (MinIO / Local FS)               │
│                                                                    │
│  /originals/    원본 문서                                          │
│  /artifacts/    중간 처리 결과 (JSON 상태 스냅샷)                    │
│  /exports/      최종 내보내기 번들                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 기술 스택 결정

| 레이어 | 기술 | 선택 근거 |
|--------|------|-----------|
| API 서버 | FastAPI 0.111+ | 문서 처리가 Python 기반, async 지원, OpenAPI 자동 생성 |
| Task Queue | Celery 5.x + Redis 7 | 파이프라인 체이닝, 재시도, 우선순위 큐 지원 |
| Metadata DB | PostgreSQL 16 + SQLAlchemy 2 | 복잡한 쿼리, JSON 컬럼 지원, 트랜잭션 안전성 |
| Vector DB | Qdrant 1.9+ | 고성능 필터링, 자체 호스팅, gRPC 지원. **중요:** 모든 app-level "컬렉션"은 하나의 물리적 Qdrant 컬렉션을 공유하며, collection_id 페이로드 필드로만 분할 |
| Embedding | 플러그인 방식 (BGE-m3 기본) | 모델 교체 시 파이프라인 무변경 |
| Frontend | React 18 + TypeScript + Vite | 컴포넌트 재사용, 생태계, TanStack Query |
| File Storage | MinIO (S3-compatible) | 로컬/클라우드 전환 투명, 멀티파트 업로드 |
| 인증 | JWT + Refresh Token | Stateless, 마이크로서비스 확장 용이 |
| 실시간 상태 | WebSocket (FastAPI native) | 작업 진행률 push |

---

## 4. 전체 데이터 흐름

### 4-1. 문서 처리 흐름 (자동 파이프라인)

```
사용자 업로드
    │
    ▼
POST /api/v1/documents
    ├─ 파일 → MinIO /originals/{doc_id}/
    ├─ DB: documents (status=QUEUED)
    └─ Celery: ingest_task.delay(doc_id)
         │
         ▼
     [Stage 1] ingest_task
         ├─ FormatDetection, Hash, Metadata
         ├─ InputDocument 생성
         └─ → structure_task.delay(doc_id, raw_doc)
              │
              ▼
          [Stage 2] structure_task
              ├─ Parse + StructureReconstitution
              ├─ StructuredDocument 저장 → MinIO /artifacts/{doc_id}/structured.json
              └─ → review_prep_task.delay(doc_id)
                   │
                   ▼
               [Stage 3] review_prep_task
                   ├─ ReviewBundle 생성
                   ├─ MinIO /artifacts/{doc_id}/review_bundle.json
                   ├─ DB: status=REVIEW_PENDING
                   └─ WebSocket push: {doc_id, status: "REVIEW_PENDING"}
                        │
                        │  (사용자가 리뷰 완료 후 정제 데이터 제출)
                        ▼
               POST /api/v1/refinements/{doc_id}
                   ├─ RefinementSet DB 저장
                   └─ → refine_task.delay(doc_id)
                        │
                        ▼
                    [Stage 4] refine_task
                        ├─ RefinementApplication + PostRecompute
                        └─ → normalize_task.delay(doc_id)
                             │
                             ▼
                         [Stage 5] normalize_task
                             ├─ SemanticNormalization
                             └─ → chunk_task.delay(doc_id)
                                  │
                                  ▼
                              [Stage 6] chunk_task
                                  ├─ ChunkGeneration
                                  └─ → embed_task.delay(doc_id, collection_id)
                                       │
                                       ▼
                                   [Stage 7] embed_task
                                       ├─ EmbeddingPlugin.embed_batch()
                                       └─ → qdrant_upload_task.delay(doc_id, collection_id)
                                            │
                                            ▼
                                        [Stage 8] qdrant_upload_task
                                            ├─ Qdrant upsert points
                                            ├─ DB: status=INDEXED, chunks_meta 업데이트
                                            └─ WebSocket push: {doc_id, status: "INDEXED"}
```

### 4-2. 검색 흐름

```
사용자 검색 쿼리
    │
    ▼
POST /api/v1/search
    ├─ EmbeddingPlugin.embed_single(query_text)
    ├─ Qdrant.search(collection_id, vector, filters, limit)
    ├─ 결과 + payload 조합 (doc_id, chunk_id, section_title, text, score)
    └─ → 응답 반환
```

### 4-3. 컬렉션 관리 흐름

```
POST /api/v1/collections         → Qdrant collection 생성 + DB 등록
POST /api/v1/collections/{id}/add-document   → embed_task + qdrant_upload_task 실행
DELETE /api/v1/collections/{id}  → Qdrant collection 삭제 + DB soft delete
GET /api/v1/collections/{id}/stats  → Qdrant count + DB 메타
```

---

## 5. 파이프라인 실행 모드

| 모드 | 설명 | 리뷰 단계 |
|------|------|-----------|
| `FULL_AUTO` | 리뷰 없이 전체 자동 실행 | 건너뜀 |
| `REVIEW_REQUIRED` | 구조화 후 사용자 리뷰 대기 | 필수 |
| `AUTO_WITH_LOW_CONFIDENCE` | 낮은 신뢰도 항목만 리뷰 | 조건부 |

모드는 컬렉션 단위 또는 문서 단위로 설정 가능. 기본값: `REVIEW_REQUIRED`.

---

## 6. 상태 머신 (문서 처리 상태)

```
QUEUED → INGESTING → PARSING → STRUCTURING
       → REVIEW_PENDING ←────────────────────
       → REFINING → NORMALIZING → CHUNKING
       → EMBEDDING → UPLOADING → INDEXED
       
실패 상태:
INGESTING/PARSING/... → FAILED (stage, error_code, message 포함)
FAILED → QUEUED (재시도)
```

---

## 7. 인증 & 권한

| 역할 | 권한 |
|------|------|
| `viewer` | 컬렉션 검색, 문서 목록 조회 |
| `editor` | 문서 업로드, 리뷰/정제, 컬렉션 추가 |
| `admin` | 컬렉션 생성/삭제, 사용자 관리, 시스템 설정 |

JWT 기반 인증. 토큰 만료: Access 30분, Refresh 7일.

---

## 8. 배포 토폴로지

### 로컬 단일 서버 (개발/소규모)
```
docker-compose up
  - api:     FastAPI (uvicorn)
  - worker:  Celery (4 concurrent)
  - redis:   Redis 7
  - db:      PostgreSQL 16
  - qdrant:  Qdrant 1.9
  - storage: MinIO
  - web:     Nginx (프론트엔드 정적 파일)
```

### 프로덕션 확장
```
- API 서버: 수평 확장 (무상태)
- Celery Worker: GPU 워커(임베딩) / CPU 워커(파이프라인) 분리
- DB: 읽기 복제본
- Qdrant: 클러스터 모드
- 파일 스토리지: S3 또는 외부 MinIO 클러스터
```

---

## 9. 관련 설계 문서

| 문서 | 내용 |
|------|------|
| `api_design.md` | REST 엔드포인트 상세 명세 |
| `database_schema.md` | PostgreSQL 테이블 스키마 |
| `task_queue_design.md` | Celery 태스크 정의 및 워크플로우 |
| `embedding_plugin_design.md` | 임베딩 플러그인 인터페이스 |
| `qdrant_integration.md` | Qdrant 컬렉션 스키마 및 전략 |
| `frontend_design.md` | 웹 대시보드 설계 |
| `execution_architecture.md` | 파이프라인 내부 모듈 상세 |
