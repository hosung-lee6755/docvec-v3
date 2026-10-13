# Qdrant 연동 설계

## 1. 개요

Qdrant는 벡터 검색과 페이로드 필터링을 동시에 지원하는 벡터 DB다.  
이 문서는 컬렉션 스키마, 포인트 페이로드 구조, 필터링 전략, 인덱싱 설계를 정의한다.

---

## 2. 컬렉션 아키텍처: 단일 물리적 컬렉션

### 2-1 핵심 설계

**모든 어플리케이션 "컬렉션"은 단 하나의 물리적 Qdrant 컬렉션을 공유한다.**

- 물리적 Qdrant 컬렉션: `settings.qdrant_collection_name="documents"` (고정)
- 고정 벡터 차원: `settings.default_embedding_dimension=1024`
- 파티션: `collection_id` 페이로드 필드로 논리적 분리
- 미사용: `Collection.qdrant_collection_name` DB 컬럼은 레거시 필드 (실제 라우팅에 사용되지 않음)

### 2-2 컬렉션 초기화

```python
# qdrant_service.py
def init_collection(self, name: str, dimension: int) -> None:
    """
    Qdrant 컬렉션 초기화. 
    - name: "documents" (항상 동일)
    - dimension: 1024 (고정)
    """
    existing = {c.name for c in self._client.get_collections().collections}
    if name not in existing:
        self._client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(
                size=dimension,
                distance=Distance.COSINE
            )
        )
```

### 2-3 인덱스 설정 (검색 성능)

```python
# 자주 필터링되는 필드에 인덱스 생성
indexed_fields = [
    'collection_id',    # 논리적 컬렉션 구분 (필수)
    'document_id',      # 문서 조회
    'disabled',         # 검색 제외된 청크 필터링
    'chunk_type',       # 블록 타입 필터
]
```

### 2-2. 검색 필터링

```python
# qdrant_service.py search()
def search(
    self,
    collection: str,          # "documents" (고정)
    vector: list[float],
    limit: int = 10,
    collection_id: str | None = None,    # 논리적 컬렉션 ID
    collection_ids: list[str] | None = None,  # 여러 컬렉션 조회
) -> list[dict]:
    """
    단일 또는 여러 컬렉션에서 벡터 검색.
    
    필터:
    - must: collection_id(s) — 접근 가능한 컬렉션만
    - must_not: disabled=True — 제외된 청크 필터링
    """
    must_conditions = []
    if collection_id:
        must_conditions.append(
            FieldCondition(key="collection_id", match=MatchValue(value=collection_id))
        )
    elif collection_ids:
        must_conditions.append(
            FieldCondition(key="collection_id", match=MatchAny(any=collection_ids))
        )
    
    query_filter = Filter(
        must=must_conditions or None,
        must_not=[FieldCondition(key="disabled", match=MatchValue(value=True))]
    )
    # ... Qdrant 검색 실행
```

---

## 3. 포인트 페이로드 구조

각 포인트는 Qdrant에 저장되는 최소 단위. 청크 1개 = Qdrant 포인트 1개.

```python
from qdrant_client.models import PointStruct

def build_point(chunk: EmbeddedChunk, doc: Document, collection: Collection) -> PointStruct:
    return PointStruct(
        id=str(chunk.chunk_id),   # UUID → 문자열 (Qdrant UUID 형식 지원)
        vector=chunk.vector,
        payload={
            # --- 식별자 ---
            'doc_id': str(doc.id),
            'collection_id': str(collection.id),
            'chunk_id': str(chunk.chunk_id),
            'chunk_index': chunk.chunk_index,

            # --- 청크 내용 ---
            'text': chunk.text,                  # 전체 청크 텍스트
            'chunk_type': chunk.chunk_type,      # 'section'|'paragraph'|'table'|...
            'token_count': chunk.token_count,

            # --- 원본 위치 (provenance) ---
            'section_id': chunk.section_id,
            'section_title': chunk.section_title,
            'section_path': chunk.section_path,  # ['1장', '1.2절', '표 목록']
            'block_ids': chunk.block_ids,         # ["blk_0042", "blk_0043"]
            'page_numbers': chunk.page_numbers,   # [5, 6]
            'table_id': chunk.table_id,           # 청크 타입이 table일 때

            # --- 문서 메타데이터 ---
            'doc_title': doc.doc_title,
            'doc_language': doc.doc_language,
            'doc_format': doc.file_format,        # 'PDF'|'HWP'|'HWPX'|'DOCX'
            'quality_score': float(doc.quality_score or 0.0),
            'uploaded_at': doc.created_at.isoformat(),

            # --- 임베딩 메타 ---
            'embedding_model': chunk.embedding_model,
            'embedding_provider': collection.embedding_provider,
        }
    )
```

**페이로드 필드 타입 요약:**

| 필드 | 타입 | Qdrant 인덱스 | 용도 |
|------|------|--------------|------|
| `doc_id` | keyword | O | 특정 문서 청크 조회 |
| `collection_id` | keyword | O | 컬렉션 내 검색 |
| `chunk_type` | keyword | O | 청크 유형 필터 |
| `page_numbers` | integer[] | O | 페이지 범위 필터 |
| `quality_score` | float | O | 품질 점수 필터 |
| `doc_language` | keyword | O | 언어별 필터 |
| `text` | text | X | 결과 반환용 (검색 대상 아님) |
| `section_title` | text | X | 결과 표시용 |
| `block_ids` | keyword[] | X | 원본 추적용 |

---

## 4. 업로드 전략

### 4-1. 배치 업로드

```python
def upload_chunks(
    client: QdrantClient,
    collection_name: str,
    points: list[PointStruct],
    batch_size: int = 100
) -> int:
    """
    청크 포인트를 배치로 업로드.
    반환: 업로드된 포인트 수
    """
    uploaded = 0
    for i in range(0, len(points), batch_size):
        batch = points[i:i + batch_size]
        client.upsert(
            collection_name=collection_name,
            points=batch,
            wait=True   # 응답 전에 인덱스 반영 보장
        )
        uploaded += len(batch)
    return uploaded
```

### 4-2. 멱등성 (Upsert)

`client.upsert()`를 사용하므로 동일 `point.id`로 재업로드 시 덮어씌움.  
문서 재처리(재인덱싱) 시 동일 chunk_id가 유지되므로 안전.

---

## 5. 검색 전략

### 5-1. 기본 벡터 검색

```python
def search(
    client: QdrantClient,
    collection_name: str,
    query_vector: list[float],
    limit: int = 10,
    score_threshold: float = 0.7
) -> list[ScoredPoint]:
    return client.search(
        collection_name=collection_name,
        query_vector=query_vector,
        limit=limit,
        score_threshold=score_threshold
    )
```

### 5-2. 페이로드 필터 조합 검색

```python
from qdrant_client.models import Filter, FieldCondition, MatchValue, Range

def search_with_filters(
    client: QdrantClient,
    collection_name: str,
    query_vector: list[float],
    doc_ids: list[str] | None = None,
    chunk_types: list[str] | None = None,
    language: str | None = None,
    min_quality: float | None = None,
    page_range: tuple[int, int] | None = None,
    limit: int = 10
) -> list[ScoredPoint]:
    """
    다양한 조건을 AND로 조합한 필터 검색.
    모든 파라미터는 선택적(None이면 해당 조건 생략).
    """
    conditions = []

    if doc_ids:
        conditions.append(FieldCondition(
            key='doc_id',
            match=MatchValue(value=doc_ids) if len(doc_ids) == 1
                  else MatchAny(any=doc_ids)
        ))
    
    if chunk_types:
        conditions.append(FieldCondition(
            key='chunk_type',
            match=MatchAny(any=chunk_types)
        ))
    
    if language:
        conditions.append(FieldCondition(
            key='doc_language',
            match=MatchValue(value=language)
        ))
    
    if min_quality is not None:
        conditions.append(FieldCondition(
            key='quality_score',
            range=Range(gte=min_quality)
        ))
    
    if page_range:
        start, end = page_range
        conditions.append(FieldCondition(
            key='page_numbers',
            range=Range(gte=start, lte=end)
        ))
    
    query_filter = Filter(must=conditions) if conditions else None
    
    return client.search(
        collection_name=collection_name,
        query_vector=query_vector,
        query_filter=query_filter,
        limit=limit,
        score_threshold=0.6,
        with_payload=True
    )
```

---

## 6. 컬렉션 관리 작업

### 6-1. 문서 삭제 (컬렉션에서 제거)

```python
from qdrant_client.models import FilterSelector

def remove_document_from_collection(
    client: QdrantClient,
    collection_name: str,
    doc_id: str
) -> None:
    """특정 문서의 모든 청크를 컬렉션에서 삭제."""
    client.delete(
        collection_name=collection_name,
        points_selector=FilterSelector(
            filter=Filter(
                must=[FieldCondition(
                    key='doc_id',
                    match=MatchValue(value=doc_id)
                )]
            )
        )
    )
```

### 6-2. 컬렉션 통계 조회

```python
def get_collection_stats(
    client: QdrantClient,
    collection_name: str
) -> dict:
    info = client.get_collection(collection_name)
    return {
        'vector_count': info.vectors_count,
        'indexed_vectors_count': info.indexed_vectors_count,
        'points_count': info.points_count,
        'status': info.status,
        'config': {
            'size': info.config.params.vectors.size,
            'distance': info.config.params.vectors.distance
        }
    }
```

### 6-3. 컬렉션 삭제

```python
def delete_collection(client: QdrantClient, collection_name: str) -> None:
    """주의: 복구 불가. API에서 is_public=False 확인 후 호출."""
    client.delete_collection(collection_name)
```

---

## 7. 컬렉션 명명 규칙

```
형식: col_{slug}_{provider_id}
예시:
  col_법령자료_bge_m3
  col_내부문서_openai
  col_research_e5_large

규칙:
- 소문자 + 언더스코어 + 하이픈
- 최대 200자
- collections.qdrant_collection_name 컬럼에 저장
```

---

## 8. 성능 설계 기준

| 항목 | 목표 | 설정 |
|------|------|------|
| 검색 레이턴시 (p99) | < 200ms | HNSW m=16, ef=100 |
| 업로드 처리량 | 100 points/batch | `upsert(wait=True)` |
| 컬렉션당 최대 벡터 | 10M | 단일 노드 기준 |
| 필터 결합 검색 | < 500ms | 페이로드 인덱스 등록 |

---

## 9. 연관 문서

| 문서 | 관계 |
|------|------|
| `embedding_plugin_design.md` | 벡터 생성 인터페이스 |
| `database_schema.md` | `collections`, `chunks_meta` 테이블 |
| `task_queue_design.md` | `qdrant_upload_task` 구현 |
| `api_design.md` | `/api/v1/search`, `/api/v1/collections` 엔드포인트 |
