# folder_structure.md

> **기록 문서 안내(2026-11-17).** 이 문서는 최초 설계 시점의 기획 기록이며, 현재 구현에 맞춰 고치지 않는다. 현재 구현은 `docs/design/`의 현행 설계서와 `docs/기술문서_시스템_아키텍처.md`, `docs/유지보수_가이드.md`를 기준으로 본다. 문서 사이의 우선순위는 `docs/README.md`에 적혀 있다.

## 1. 목표

본 문서는 Document Structuring Solution의 최종 폴더 구조를 정의한다.

## 2. 실제 폴더 구조 (DocVec 플랫폼)

```
project_root/
├─ backend/
│  ├─ app/
│  │  ├─ api/v1/
│  │  │  ├─ endpoints/        # API routes (auth, documents, collections, chat, search, golden_queries, etc.)
│  │  │  ├─ deps.py           # Dependencies (DB session, current user, etc.)
│  │  │  ├─ permissions.py    # Access control
│  │  │  └─ router.py         # Router registration
│  │  ├─ pipeline/
│  │  │  ├─ adapters/         # Format adapters (pdf, docx, hwp, hwpx)
│  │  │  ├─ tasks/            # Celery tasks (ingest, process, chunks, summary, chat, reembed)
│  │  │  └─ celery_app.py     # Celery configuration
│  │  ├─ db/
│  │  │  ├─ models/           # ORM models (User, Document, Collection, ChatMessage, GoldenQuery, etc.)
│  │  │  ├─ session.py        # Database session management
│  │  │  └─ base.py           # Base model
│  │  ├─ services/            # Business logic (embedding, qdrant, bm25, llm, search, document, preview, chunk_stats, storage)
│  │  ├─ schemas/             # Pydantic models (DTOs)
│  │  ├─ core/                # Config, security, logging, crypto
│  │  └─ main.py              # FastAPI app
│  ├─ alembic/                # Database migrations
│  └─ pyproject.toml
├─ frontend/
│  ├─ src/
│  │  ├─ pages/               # Route pages (DashboardPage, DocumentsPage, CollectionsPage, ChatPage, SearchPage, etc.)
│  │  ├─ components/          # React components (GoldenEvalModal, Layout, etc.)
│  │  ├─ hooks/               # Custom React hooks (useDocuments, useCollections, useChat, useGoldenQueries, etc.)
│  │  ├─ lib/                 # Utilities (apiClient, documentStatus, etc.)
│  │  ├─ store/               # State management (authStore)
│  │  ├─ types/               # TypeScript types
│  │  └─ App.tsx
│  └─ package.json
├─ docker-compose.yml
└─ README.md
```

## 3. 설계 원칙

- FastAPI API 계층 (endpoints) 분리
- Celery 비동기 작업 (pipeline/tasks) 분리
- 데이터베이스 모델 (db/models) 분리
- 비즈니스 로직 (services) 별도 계층
- API 스키마 (schemas) 명시적 정의
- 프론트엔드는 React 페이지/훅/컴포넌트 구조
