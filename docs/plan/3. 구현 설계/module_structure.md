# module_structure.md

> **기록 문서 안내(2026-11-17).** 이 문서는 최초 설계 시점의 기획 기록이며, 현재 구현에 맞춰 고치지 않는다. 현재 구현은 `docs/design/`의 현행 설계서와 `docs/기술문서_시스템_아키텍처.md`, `docs/유지보수_가이드.md`를 기준으로 본다. 문서 사이의 우선순위는 `docs/README.md`에 적혀 있다.

## 1. 백엔드 모듈 설계 (FastAPI + Celery + Services)

### api/v1/endpoints/
- 각 도메인별 REST 엔드포인트
- auth, documents, collections, projects, search, chat, golden_queries, users, stats

### pipeline/adapters/
- 문서 포맷별 파서 (PDF, DOCX, HWP, HWPX)
- base_adapter.py: 공통 인터페이스

### pipeline/tasks/
- Celery 비동기 작업: ingest, process, chunks, summary, chat, reembed, pipeline
- 백그라운드 작업 (문서 처리, 임베딩, 재임베딩)

### db/models/
- ORM 모델: User, Document, Collection, ChatMessage, GoldenQuery, GoldenEvalRun, etc.

### services/
- 비즈니스 로직 계층
- embedding, qdrant_service, bm25_service, reranker, llm, search_service, document_service, preview_service, chunk_stats, storage

### schemas/
- Pydantic 요청/응답 모델 (DTOs)

### core/
- config, security, logging, crypto

## 2. 프론트엔드 모듈 설계 (React + TypeScript)

### pages/
- 라우트별 페이지 컴포넌트

### components/
- 재사용 가능한 UI 컴포넌트 (GoldenEvalModal, etc.)

### hooks/
- 커스텀 React 훅 (useDocuments, useCollections, useChat, useGoldenQueries, etc.)

### lib/
- API 클라이언트, 유틸리티 함수
