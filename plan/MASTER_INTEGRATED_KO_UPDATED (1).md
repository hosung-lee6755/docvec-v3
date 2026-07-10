# MASTER_INTEGRATED_KO.md
# Document Structuring Solution (DocVec) - 통합 설계 안내 문서

## 1. 문서 목적

본 문서는 DocVec(Document Structuring Solution)의 설계 문서를 한 번에 탐색할 수 있도록 정리한 통합 안내 문서다.
각 세부 설계 문서를 링크로 연결하고, 문서 간 관계와 참조 순서를 설명한다.

> **2026-07-10 최신화**: 하위 설계 문서 24개 전부를 실제 구현(FastAPI + Celery + React/TS + Postgres + Qdrant + Redis + MinIO, docker compose) 기준으로 대조·갱신했다. 각 문서는 이제 원래의 개념 설계뿐 아니라 "현재 실제로 동작하는 방식"과 "설계와 다르게 구현된 지점"을 명시적으로 구분해 기록한다. 최신화 이전 버전 대비 달라진 핵심 사실은 8절을 참조.

---

## 2. 설계 문서 세트

### 2.1 구조 복원 엔진 설계
- engine_design.md

### 2.2 Canonical Schema 설계 : 표준 데이터 모델 설계
- canonical_schema.md

### 2.3 Refinement 설계 : 데이터 정제 설계
- refinement.md

### 2.4 Review Bundle 설계 : 파싱/구조화 결과 설계
- review_spec.md

### 2.5 Execution Architecture 설계 : 실행 아키텍처 설계
- execution_architecture.md

---

## 3. 문서 간 관계

Execution Architecture
  ├─ Engine Design
  ├─ Canonical Schema
  ├─ Refinement
  └─ Review

---

## 4. 설계 읽기 순서

1. execution_architecture.md
2. engine_design.md
3. canonical_schema.md
4. review_spec.md
5. refinement.md


---

## 5. 구현 설계 (폴더 / 모듈 / 클래스)

본 섹션은 기존 개념 설계를 실제 코드 구조로 연결하는 계층이다.

### 5.1 폴더/파일 구조
- [folder_structure.md]
- [file_structure_design.md]

설명:
- src 기준 기능 단위 디렉토리 분리
- ingest → parser → structurer → refinement → normalization → export 흐름 유지
- models / utils는 공통 계층

---

### 5.2 모듈 구조
- [module_structure.md]
- [module_interface_spec.md]

설명:
- 각 디렉토리는 단일 책임
- parser / structurer / refinement / recompute 완전 분리
- canonical 이전/이후 계층 분리 유지

---

### 5.3 클래스 설계
- [class_design.md]
- [class_design_detailed.md]

설명:
- 상태 객체(Input, Raw, Structured, Refined, Canonical) 명확히 분리
- 처리 엔진(Parser, Structurer, RefinementEngine 등) 단일 책임 유지
- 함수형이 아닌 상태 전이 기반 설계

---

## 6. 전체 설계 연결 구조

```text
[Folder Structure]
        ↓
[Module Structure]
        ↓
[Class Design]
        ↓
[Execution Architecture]
        ↓
[Engine / Schema / Refinement / Review]
```

---

## 7. 최종 설계 요약

이 설계는 3단계로 완성된다.

1. 구조 설계
   - engine_design
   - canonical_schema
   - refinement
   - review_spec

2. 실행 설계
   - execution_architecture

3. 구현 설계
   - folder_structure
   - file_structure_design
   - module_structure
   - module_interface_spec
   - class_design
   - class_design_detailed

이 3단계가 결합되어야 실제 코드 구현이 가능하다.

---

## 8. 구현 현황 요약 (2026-07-10 기준)

### 8.1 구현 완료

| 영역 | 기능 | 관련 문서 |
|---|---|---|
| 파싱/구조화 | HWP/HWPX 실제 페이지 단위 인용 (LibreOffice Preview PDF 텍스트 매칭, `pageBreak` 속성은 사용 불가로 판명) | engine_design.md, review_spec.md |
| 파싱/구조화 | 비파괴적 원문 수정/리비전 스냅샷 (`DocumentTextRevision`) | refinement.md |
| RAG 검색 | 청크 조회수(hit-count) 통계 | database_schema.md, class_design.md |
| RAG 검색 | 채팅 의도 분류 라우팅 (문서검색/표질의/요약조회) | module_interface_spec.md.md |
| RAG 검색 | Self-Reflection 답변 검증의 클라우드 모델(BYOK) 위임 | api_design.md |
| RAG 검색 | 골든 쿼리 세트 기반 정밀도/재현율 평가 | database_schema.md, api_design.md, frontend_design.md |
| 운영 | ZIP 대량 업로드 (zip-bomb/경로순회 방어 포함) | api_design.md, performance_spec.md |
| 운영 | 임베딩 모델 변경 시 백그라운드 재임베딩 워크플로우 | embedding_plugin_design.md, task_queue_design.md |

### 8.2 보류/미착수

| 항목 | 상태 | 비고 |
|---|---|---|
| Agentic OCR 실험 기능 | 미착수 | 별도 확인 후 착수 예정 |
| 경량 로컬 VLM 기반 OCR | 명시적 보류 | 기존 임베딩/리랭커와 GPU 메모리 경합 위험으로 사용자 확인 대기 중 |

### 8.3 알려진 한계 (기술명세서/영업 자료 작성 시 반드시 반영)

- **버전 관리 없음**: 저장소가 git으로 관리되지 않음 — 변경 이력·롤백·리뷰 흔적이 없다.
- **자동화 테스트 빈약**: 백엔드 유닛 테스트 6개 파일(보안/설정/BM25/검색 위주), 프론트엔드는 스토어 테스트 1개뿐. 추정 커버리지 20% 미만 (test_strategy.md 2절 참조).
- **베스트에포트 기능**: HWP/HWPX 페이지 매칭은 실측 86~93% 수준(100% 아님, engine_design.md 참조). 골든 쿼리 평가는 소규모 스모크테스트만 수행, 대표성 있는 정밀도/재현율 수치는 아직 없음.
- **보안 감사 미실시**: 프로젝트/컬렉션 공유, BYOK API 키 저장 등 민감 기능에 대한 정식 보안 리뷰가 수행된 적 없음.
- **성능 벤치마크 없음**: 동시 사용자·P95 레이턴시 등 고객향 SLA 수치가 아직 측정되지 않음 (performance_spec.md는 내부 튜닝 상수만 문서화).
