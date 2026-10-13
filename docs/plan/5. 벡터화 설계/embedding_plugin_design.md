# 임베딩 플러그인 설계

## 1. 설계 목표

- 임베딩 모델(OpenAI, BGE-m3, E5 등)을 **코드 변경 없이 교체** 가능
- 컬렉션마다 서로 다른 모델 사용 가능
- 배치 처리 및 비동기 호출 통일된 인터페이스로 제공
- 새 모델 추가 시 어댑터 클래스 하나만 작성

---

## 2. 핵심 인터페이스

### 2-1. `EmbeddingProvider` (추상 기반 클래스)

```python
from abc import ABC, abstractmethod

class EmbeddingProvider(ABC):
    """모든 임베딩 어댑터가 구현해야 하는 인터페이스."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """생성되는 벡터의 차원. 컬렉션의 벡터 차원과 일치해야 함."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """텍스트 리스트를 임베딩. 
        - 단일 쿼리: embed([query]) 반환 [vector]
        - 배치 청크: embed([chunk1, chunk2, ...]) 반환 [vector1, vector2, ...]
        """
```

### 2-2. 구현체 예시

```python
class OpenAIEmbeddingProvider(EmbeddingProvider):
    _MODEL = "text-embedding-3-small"
    _DIM = 1536
    
    @property
    def dimension(self) -> int:
        return self._DIM
    
    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(input=texts, model=self._MODEL)
        return [item.embedding for item in response.data]


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    """로컬 모델 (BGE-M3, E5 등)"""
    
    def __init__(self, repo_id: str, dimension: int):
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(repo_id)
        self._dimension = dimension
    
    @property
    def dimension(self) -> int:
        return self._dimension
    
    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return vectors.tolist()
```

### 2-3. 런타임 조회

```python
# services/embedding.py
_EMBEDDING_MODEL_REGISTRY = {
    "bge-m3": BgeM3EmbeddingProvider(...),
    "openai-text-embedding-3-small": OpenAIEmbeddingProvider(),
    # ...
}

def get_embedding_provider() -> EmbeddingProvider:
    """현재 설정의 기본 임베딩 모델 프로바이더 반환."""
    model_id = settings.default_embedding_model  # e.g., "bge-m3"
    return _EMBEDDING_MODEL_REGISTRY[model_id]
```

---

## 3. 컬렉션별 차원 제약과 모델 선택

모든 컬렉션은 **단 하나의 물리적 Qdrant 컬렉션** (`settings.qdrant_collection_name="documents"`)을 공유하며, 고정된 벡터 차원(`settings.default_embedding_dimension=1024`)을 사용한다.

따라서 컬렉션의 임베딩 모델을 변경할 때는 **같은 차원의 모델만 선택 가능**하다:

```python
# collections.py의 _SELECTABLE_MODELS 필터 로직
_SELECTABLE_MODELS = [
    model for model in EMBEDDING_MODEL_REGISTRY
    if EMBEDDING_MODEL_REGISTRY[model].dimension == settings.default_embedding_dimension
]
```

---

## 4. 임베딩 모델 변경 워크플로우

컬렉션의 `embedding_model`을 변경하면 **백그라운드 재임베딩 작업**이 자동으로 시작된다:

### 4.1 API 호출 흐름

```
PUT /collections/{collection_id}
  {"embedding_model": "new-model"}
    ↓
(api/v1/endpoints/collections.py)
  if new_model != current_model:
    collection.reembed_status = "PENDING"
    collection.reembed_progress = "0/{doc_count}"
    db.commit()
    
    reembed_collection.delay(collection_id, new_model)  # Celery task
```

### 4.2 Celery 워커: `tasks/reembed.py`

```python
@celery_app.task(name="tasks.reembed_collection", queue="low")
def reembed_collection(collection_id: str, embedding_model: str) -> dict:
    """
    컬렉션의 모든 INDEXED 문서를 새 모델로 재임베딩.
    - Qdrant 포인트 ID는 유지 (같은 ID, 새 벡터)
    - 페이로드는 변경 없음
    """
    collection.reembed_status = "RUNNING"
    
    for doc in accessible_docs:
        start_job(REEMBED, doc_id)
        chunks = scroll_by_document(doc_id)
        vectors = embed_texts(chunks, embedding_model)  # 새 모델로 임베딩
        upsert_points(collection, vectors)  # 같은 ID, 새 벡터로 업데이트
        complete_job(...)
    
    collection.reembed_status = "COMPLETED"
```

### 4.3 상태 추적

- `reembed_status`: `PENDING` → `RUNNING` → `COMPLETED` or `FAILED`
- `reembed_progress`: `"3/10"` 형태로 진행상황 표시
- UI는 재임베딩 중 embedding_model `<select>` 비활성화

---

## 3. 어댑터 구현체

### 3-1. `OpenAIEmbeddingProvider`

```python
class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    OpenAI Embeddings API 어댑터.
    지원 모델: text-embedding-3-small (1536d), text-embedding-3-large (3072d)
    """
    
    def __init__(self, config: OpenAIEmbeddingConfig):
        self._client = openai.OpenAI(api_key=config.api_key)
        self._model = config.model  # 'text-embedding-3-small'
        self._dimension = config.dimension  # 1536

    @property
    def provider_id(self) -> str:
        return 'openai'

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def vector_dimension(self) -> int:
        return self._dimension

    def embed_single(self, text: str) -> EmbeddingResult:
        text = self.validate_text(text)
        response = self._client.embeddings.create(
            input=text,
            model=self._model
        )
        return EmbeddingResult(
            text=text,
            vector=response.data[0].embedding,
            model=self._model,
            token_count=response.usage.total_tokens
        )

    def embed_batch(self, texts: list[str], batch_size: int = 64) -> list[EmbeddingResult]:
        results = []
        for i in range(0, len(texts), batch_size):
            batch = [self.validate_text(t) for t in texts[i:i + batch_size]]
            response = self._client.embeddings.create(
                input=batch,
                model=self._model
            )
            for j, item in enumerate(response.data):
                results.append(EmbeddingResult(
                    text=batch[j],
                    vector=item.embedding,
                    model=self._model
                ))
        return results
```

---

### 3-2. `BgeM3EmbeddingProvider`

```python
class BgeM3EmbeddingProvider(EmbeddingProvider):
    """
    BAAI/bge-m3 로컬 모델 어댑터.
    다국어 지원, 1024차원, 한국어 품질 우수.
    FlagEmbedding 라이브러리 사용.
    """
    
    def __init__(self, config: BgeM3Config):
        from FlagEmbedding import BGEM3FlagModel
        self._model = BGEM3FlagModel(
            config.model_path,
            use_fp16=config.use_fp16,
            device=config.device  # 'cuda' or 'cpu'
        )
        self._dimension = 1024

    @property
    def provider_id(self) -> str:
        return 'bge_m3'

    @property
    def model_id(self) -> str:
        return 'BAAI/bge-m3'

    @property
    def vector_dimension(self) -> int:
        return self._dimension

    def embed_single(self, text: str) -> EmbeddingResult:
        text = self.validate_text(text)
        output = self._model.encode(
            [text],
            batch_size=1,
            return_dense=True
        )
        return EmbeddingResult(
            text=text,
            vector=output['dense_vecs'][0].tolist(),
            model='bge-m3'
        )

    def embed_batch(self, texts: list[str], batch_size: int = 64) -> list[EmbeddingResult]:
        validated = [self.validate_text(t) for t in texts]
        results = []
        for i in range(0, len(validated), batch_size):
            batch = validated[i:i + batch_size]
            output = self._model.encode(
                batch,
                batch_size=batch_size,
                return_dense=True
            )
            for j, vec in enumerate(output['dense_vecs']):
                results.append(EmbeddingResult(
                    text=batch[j],
                    vector=vec.tolist(),
                    model='bge-m3'
                ))
        return results
```

---

### 3-3. `E5LargeEmbeddingProvider`

```python
class E5LargeEmbeddingProvider(EmbeddingProvider):
    """
    intfloat/multilingual-e5-large 어댑터.
    1024차원, 검색 쿼리에 'query: ' 접두사 필요.
    transformers + sentence-transformers 사용.
    """

    def __init__(self, config: E5Config):
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(
            config.model_path,
            device=config.device
        )
        self._dimension = 1024

    @property
    def provider_id(self) -> str:
        return 'e5_large'

    @property
    def model_id(self) -> str:
        return 'intfloat/multilingual-e5-large'

    @property
    def vector_dimension(self) -> int:
        return self._dimension

    def embed_single(self, text: str, is_query: bool = False) -> EmbeddingResult:
        text = self.validate_text(text)
        # E5는 query/passage 구분 필요
        prefixed = f"query: {text}" if is_query else f"passage: {text}"
        vec = self._model.encode([prefixed])[0]
        return EmbeddingResult(
            text=text,
            vector=vec.tolist(),
            model='multilingual-e5-large'
        )

    def embed_batch(self, texts: list[str], batch_size: int = 64) -> list[EmbeddingResult]:
        validated = [self.validate_text(t) for t in texts]
        prefixed = [f"passage: {t}" for t in validated]
        results = []
        for i in range(0, len(prefixed), batch_size):
            batch = prefixed[i:i + batch_size]
            vecs = self._model.encode(batch, batch_size=batch_size)
            for j, vec in enumerate(vecs):
                results.append(EmbeddingResult(
                    text=validated[i + j],
                    vector=vec.tolist(),
                    model='multilingual-e5-large'
                ))
        return results
```

---

## 4. 플러그인 등록 흐름

```
앱 시작
  └─ register_default_providers(config)
       ├─ OpenAIEmbeddingProvider 등록 (provider_id='openai')
       ├─ BgeM3EmbeddingProvider 등록 (provider_id='bge_m3')
       └─ E5LargeEmbeddingProvider 등록 (provider_id='e5_large')

Celery embed_task 실행
  ├─ Collection 조회 → embedding_provider='bge_m3'
  ├─ EmbeddingPluginRegistry.get('bge_m3') → BgeM3EmbeddingProvider
  └─ provider.embed_batch(chunk_texts, batch_size=64)

검색 시 (FastAPI)
  ├─ Collection 조회 → embedding_provider='openai'
  ├─ EmbeddingPluginRegistry.get('openai') → OpenAIEmbeddingProvider
  └─ provider.embed_single(query_text)
```

---

## 5. 에러 처리

| 오류 | 원인 | 처리 |
|------|------|------|
| `EmbeddingAPIError` | OpenAI API 오류 (Rate Limit, 5xx) | 지수 백오프 재시도 (3회) |
| `EmbeddingModelError` | 로컬 모델 로드 실패 | 즉시 FAILED, 에러 코드 `ERR_MODEL_LOAD` |
| `EmbeddingInputError` | 빈 텍스트, 토큰 초과 | 청크 건너뜀 + 경고 기록 |
| `KeyError` | 미등록 provider_id | 즉시 FAILED, 에러 코드 `ERR_PROVIDER_NOT_FOUND` |

---

## 6. 모델별 사양 비교

| 모델 | provider_id | 차원 | 언어 | 호스팅 | 장점 |
|------|------------|------|------|--------|------|
| text-embedding-3-small | `openai` | 1536 | 다국어 | 외부 API | 설정 불필요, 고품질 |
| BAAI/bge-m3 | `bge_m3` | 1024 | 다국어 | 로컬/GPU | 한국어 최적화, API 비용 없음 |
| multilingual-e5-large | `e5_large` | 1024 | 다국어 | 로컬/GPU | 다국어 균형 품질 |

**기본값:** `bge_m3` (한국어 문서 처리 최적화)

---

## 7. 새 모델 추가 방법

```python
# 1. EmbeddingProvider를 상속하는 클래스 작성
class MyCustomProvider(EmbeddingProvider):
    @property
    def provider_id(self) -> str: return 'my_custom'
    @property
    def model_id(self) -> str: return 'my-model-v1'
    @property
    def vector_dimension(self) -> int: return 768
    def embed_single(self, text: str) -> EmbeddingResult: ...
    def embed_batch(self, texts: list[str], batch_size: int = 64) -> list[EmbeddingResult]: ...

# 2. 앱 시작 시 등록
EmbeddingPluginRegistry.register(MyCustomProvider(config))

# 3. 컬렉션 생성 시 provider_id='my_custom' 지정
# → 파이프라인 코드 변경 없이 사용 가능
```

**파이프라인 코드(embed_task 등)는 변경 불필요.**
