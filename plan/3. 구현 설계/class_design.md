# class_design.md

## 1. ORM 모델 (데이터 계층)

### User
- id, email, password_hash, system_prompt, api_keys

### Document
- id, filename, original_filename, collection_id, status, minio_key, parsed_structure, page_count, tables, summary, pages, etc.

### Collection
- id, name, description, embedding_model, reembed_status, reembed_progress, chunk_strategy

### ChatConversation & ChatMessage
- 사용자 채팅 이력 저장

### GoldenQuery & GoldenEvalRun (신규)
- 평가 쿼리 및 평가 결과 저장

### Project & ProjectMember
- 프로젝트 및 멤버 관리

---

## 2. 서비스 클래스 (비즈니스 로직)

### EmbeddingProvider
- embed(texts) -> list[list[float]]
- 지원: OpenAI, Anthropic, Ollama, HuggingFace

### QdrantService
- search(collection, vector, limit) -> hits
- upsert_points(collection, points)
- delete_points(collection, point_ids)

### BM25Service
- rank(documents, query) -> ranked_documents

### RerankerService
- rerank(query, documents, top_k) -> ranked

### LLMProvider
- generate(prompt, system_prompt, model) -> response

### SearchService
- perform_search(query, collection_id, limit) -> results

### GoldenQueryEvaluation (신규)
- evaluate(golden_queries, collection_id, top_k) -> precision/recall metrics

---

## 3. API 엔드포인트 클래스

### DocumentRouter
- POST /documents/upload-zip
- GET /documents
- GET /documents/{id}
- DELETE /documents/{id}

### CollectionsRouter
- POST /collections/{id}/golden-queries
- GET /collections/{id}/golden-queries
- POST /collections/{id}/golden-eval-runs
- GET /collections/{id}/golden-eval-runs

### ChatRouter
- POST /chat/{conversation_id}/message (의도 분류 및 의도별 검색 라우팅)

### ReembedTask (신규 Celery)
- reembed_collection(collection_id, embedding_model)

---

## 4. 설계 원칙

- 데이터 객체(ORM 모델) 와 비즈니스 로직(서비스) 분리
- 각 클래스는 단일 책임
- 의존성은 주입 패턴 사용
