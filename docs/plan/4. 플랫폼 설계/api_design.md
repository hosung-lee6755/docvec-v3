# FastAPI REST API 설계

## 1. 공통 규칙

- **Base URL**: `/api/v1`
- **인증**: `Authorization: Bearer <JWT>` 헤더
- **응답 형식**: 모든 응답은 아래 Envelope 구조 준수

```json
// 성공
{
  "success": true,
  "data": { ... },
  "error": null
}

// 실패
{
  "success": false,
  "data": null,
  "error": { "code": "ERR_NOT_FOUND", "message": "문서를 찾을 수 없습니다." }
}

// 페이지네이션 응답
{
  "success": true,
  "data": [...],
  "meta": { "total": 150, "page": 1, "limit": 20 }
}
```

---

## 2. 인증 (`/auth`)

| Method | Path | 권한 | 설명 |
|--------|------|------|------|
| `POST` | `/auth/login` | 없음 | 이메일/비밀번호 로그인 |
| `POST` | `/auth/refresh` | 없음 | Access 토큰 갱신 |
| `POST` | `/auth/logout` | 인증 | Refresh 토큰 무효화 |
| `GET` | `/auth/me` | 인증 | 현재 사용자 정보 |

### `POST /auth/login`

**요청:**
```json
{ "email": "user@example.com", "password": "..." }
```

**응답:**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

---

## 3. 문서 (`/documents`)

| Method | Path | 권한 | 설명 |
|--------|------|------|------|
| `POST` | `/documents` | editor | 문서 업로드 (단일 파일) |
| `POST` | `/documents/upload-zip` | editor | 대량 ZIP 업로드 (task #62) |
| `GET` | `/documents` | viewer | 문서 목록 |
| `GET` | `/documents/{id}` | viewer | 문서 상세 |
| `DELETE` | `/documents/{id}` | editor | 문서 삭제 (소프트) |
| `GET` | `/documents/{id}/status` | viewer | 처리 상태 조회 |
| `POST` | `/documents/{id}/retry` | editor | 실패 문서 재처리 |
| `GET` | `/documents/{id}/artifacts/{artifact}` | viewer | 중간 결과물 다운로드 |

### `POST /documents`

**요청:** `multipart/form-data`
```
file: <업로드 파일>
pipeline_mode: FULL_AUTO | REVIEW_REQUIRED | AUTO_WITH_LOW_CONFIDENCE
collection_id: <UUID> (선택)
```

**응답:**
```json
{
  "id": "01926f8a-...",
  "status": "QUEUED",
  "original_filename": "계약서_2024.pdf",
  "file_format": "PDF",
  "pipeline_mode": "REVIEW_REQUIRED",
  "created_at": "2026-06-30T09:00:00Z"
}
```

### `GET /documents`

**쿼리 파라미터:**
- `status`: 상태 필터 (복수 가능 `?status=INDEXED&status=FAILED`)
- `collection_id`: 컬렉션 필터
- `format`: 파일 형식 필터
- `page`, `limit`: 페이지네이션 (기본 limit=20)
- `sort`: `created_at_desc` | `created_at_asc` | `status`

### `POST /documents/{id}/retry`

**쿼리 파라미터:**
- `from_stage`: 재시작할 스테이지 (기본: 처음부터)

---

## 4. 처리 작업 (`/jobs`)

| Method | Path | 권한 | 설명 |
|--------|------|------|------|
| `GET` | `/jobs` | viewer | 작업 목록 |
| `GET` | `/jobs/{id}` | viewer | 작업 상세 |
| `GET` | `/documents/{doc_id}/jobs` | viewer | 문서별 작업 이력 |

---

## 5. 리뷰 & 정제 (`/refinements`)

| Method | Path | 권한 | 설명 |
|--------|------|------|------|
| `GET` | `/documents/{id}/review` | viewer | 리뷰 번들 조회 |
| `POST` | `/documents/{id}/refinements` | editor | 정제 명령어 제출 |
| `GET` | `/documents/{id}/refinements` | viewer | 정제 이력 |
| `GET` | `/refinements/{id}` | viewer | 정제 상세 |

### `POST /documents/{id}/refinements`

**요청:**
```json
{
  "operations": [
    {"op": "block_remove", "block_id": "blk_0042"},
    {"op": "block_role_change", "block_id": "blk_0043", "new_role": "heading"},
    {"op": "table_header_override", "table_id": "tbl_0001", "header_rows": 2}
  ]
}
```

**응답:** `202 Accepted`
```json
{
  "refinement_set_id": "01926f8b-...",
  "status": "SUBMITTED",
  "message": "정제 작업이 대기열에 등록되었습니다."
}
```

---

## 6. 컬렉션 (`/collections`)

| Method | Path | 권한 | 설명 |
|--------|------|------|------|
| `POST` | `/collections` | admin | 컬렉션 생성 |
| `GET` | `/collections` | viewer | 컬렉션 목록 |
| `GET` | `/collections/{id}` | viewer | 컬렉션 상세 |
| `PATCH` | `/collections/{id}` | admin | 컬렉션 정보 수정 |
| `DELETE` | `/collections/{id}` | admin | 컬렉션 삭제 |
| `POST` | `/collections/{id}/documents` | editor | 문서 추가 (인덱싱) |
| `DELETE` | `/collections/{id}/documents/{doc_id}` | editor | 문서 제거 |
| `GET` | `/collections/{id}/stats` | viewer | 컬렉션 통계 |

### `POST /collections`

**요청:**
```json
{
  "name": "법령 자료 2024",
  "slug": "법령자료-2024",
  "description": "2024년 개정 법령 전체",
  "embedding_provider": "bge_m3",
  "embedding_model": "BAAI/bge-m3",
  "distance_metric": "Cosine",
  "is_public": false
}
```

**응답:**
```json
{
  "id": "01926f8c-...",
  "name": "법령 자료 2024",
  "slug": "법령자료-2024",
  "embedding_provider": "bge_m3",
  "vector_dimension": 1024,
  "qdrant_collection_name": "col_법령자료-2024_bge_m3",
  "document_count": 0,
  "created_at": "2026-06-30T09:00:00Z"
}
```

### `GET /collections/{id}/stats`

**응답:**
```json
{
  "collection_id": "01926f8c-...",
  "document_count": 150,
  "chunk_count": 24500,
  "vector_count": 24500,
  "indexed_vectors_count": 24500,
  "status": "green",
  "last_indexed_at": "2026-06-30T08:00:00Z"
}
```

---

## 7. 검색 (`/search`)

| Method | Path | 권한 | 설명 |
|--------|------|------|------|
| `POST` | `/search` | viewer | 벡터 검색 |
| `GET` | `/search/history` | viewer | 검색 이력 |

### `POST /search`

**요청:**
```json
{
  "collection_id": "01926f8c-...",
  "query": "임차인의 보증금 반환 의무",
  "limit": 10,
  "score_threshold": 0.7,
  "filters": {
    "chunk_types": ["paragraph", "table"],
    "doc_language": "ko",
    "min_quality_score": 0.8,
    "doc_ids": null,
    "page_range": null
  }
}
```

**응답:**
```json
{
  "query": "임차인의 보증금 반환 의무",
  "results": [
    {
      "chunk_id": "01926f8d-...",
      "doc_id": "01926f8a-...",
      "doc_title": "주택임대차보호법",
      "score": 0.924,
      "chunk_type": "paragraph",
      "text": "임대인은 임대차가 종료된 경우에...",
      "section_title": "제3조의2 (보증금의 회수)",
      "section_path": ["제1장", "제3조의2"],
      "page_numbers": [5],
      "block_ids": ["blk_0042", "blk_0043"]
    }
  ],
  "total_found": 10,
  "took_ms": 45
}
```

---

## 8. 내보내기 (`/exports`)

| Method | Path | 권한 | 설명 |
|--------|------|------|------|
| `POST` | `/documents/{id}/exports` | editor | 내보내기 생성 |
| `GET` | `/documents/{id}/exports` | viewer | 내보내기 목록 |
| `GET` | `/exports/{id}/download` | viewer | 파일 다운로드 |

### `POST /documents/{id}/exports`

**요청:**
```json
{ "format": "chunks_jsonl" }
```

지원 형식: `canonical_json`, `review_md`, `chunks_jsonl`, `records_jsonl`, `facts_jsonl`, `diagnostics_json`, `full_bundle`

---

## 9. WebSocket (`/ws`)

| Path | 설명 |
|------|------|
| `/ws/documents/{id}/progress` | 문서 처리 진행률 실시간 구독 |

**메시지 형식:**
```json
{
  "doc_id": "01926f8a-...",
  "stage": "embedding",
  "progress": 0.64,
  "message": "청크 임베딩 중 (41/64)",
  "timestamp": 1751289600.0
}
```

---

## 10. 관리 (`/admin`)

| Method | Path | 권한 | 설명 |
|--------|------|------|------|
| `GET` | `/admin/users` | admin | 사용자 목록 |
| `POST` | `/admin/users` | admin | 사용자 생성 |
| `PATCH` | `/admin/users/{id}` | admin | 사용자 수정 (역할 변경 등) |
| `DELETE` | `/admin/users/{id}` | admin | 사용자 비활성화 |
| `GET` | `/admin/jobs` | admin | 전체 작업 이력 |
| `GET` | `/admin/system/stats` | admin | 시스템 통계 |
| `POST` | `/admin/system/purge-failed` | admin | 실패 작업 정리 |

---

## 11. HTTP 상태 코드 규칙

| 상태 | 사용 상황 |
|------|-----------|
| `200 OK` | 조회, 수정 성공 |
| `201 Created` | 리소스 생성 성공 |
| `202 Accepted` | 비동기 작업 등록 (Celery 큐잉) |
| `204 No Content` | 삭제 성공 |
| `400 Bad Request` | 요청 형식 오류, 유효성 검사 실패 |
| `401 Unauthorized` | 인증 토큰 없음 또는 만료 |
| `403 Forbidden` | 권한 부족 |
| `404 Not Found` | 리소스 없음 |
| `409 Conflict` | 중복 생성 (동일 slug 등) |
| `422 Unprocessable Entity` | Pydantic 유효성 오류 |
| `429 Too Many Requests` | Rate limit 초과 |
| `500 Internal Server Error` | 서버 내부 오류 |
