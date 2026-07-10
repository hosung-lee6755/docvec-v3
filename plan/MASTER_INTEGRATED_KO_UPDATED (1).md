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
| 운영 | 감사 로그 (로그인/문서삭제/권한변경/API키 등록삭제 등 계측, 관리자 전용 조회 화면) | database_schema.md, api_design.md |
| 운영 | BYOK 사용량/비용 대시보드 (모델별·사용자별 토큰/추정비용 집계, 로컬 모델 비용 제외) | database_schema.md, api_design.md |

### 8.2 보류/미착수

| 항목 | 상태 | 비고 |
|---|---|---|
| Agentic OCR 실험 기능 | 미착수 | 별도 확인 후 착수 예정 |
| 경량 로컬 VLM 기반 OCR | 명시적 보류 | 기존 임베딩/리랭커와 GPU 메모리 경합 위험으로 사용자 확인 대기 중 |

### 8.3 알려진 한계 (기술명세서/영업 자료 작성 시 반드시 반영)

- ~~버전 관리 없음~~ → **해결**: git 저장소 초기화 완료, GitHub 원격(`origin/main`)에 푸시됨.
- ~~보안 감사 미실시~~ → **해결**: 자체 보안 리뷰 수행, CRITICAL 5건/HIGH 3건/MEDIUM 2건 전부 수정 완료 (SECRET_KEY 검증, PBKDF2 키 유도, Redis 레이트리밋, 비활성 계정 차단, 이메일 열거 방지, 쿠키 하드닝, CORS 화이트리스트). CSRF는 Bearer 토큰 기반 인증 구조상 쿠키 전용 `/auth/refresh` 엔드포인트로 영향 범위가 제한된다고 판단, 전체 CSRF 토큰 미들웨어 대신 쿠키 하드닝만 적용 — 정식 외부 침투테스트는 아직 수행되지 않음.
- **자동화 테스트 여전히 얇음** (개선됨, 완전하지는 않음): 인증/권한(IDOR)/골든쿼리/ZIP업로드 핵심 경로에 신규 유닛테스트 추가로 커버리지 12.29% → 26.75%로 상승. `--cov-fail-under=80` 기준에는 크게 미달 — 프론트엔드 컴포넌트 테스트는 여전히 0개.
- **베스트에포트 기능**: HWP/HWPX 페이지 매칭은 실측 86~93% 수준(100% 아님, engine_design.md 참조).
- **골든 쿼리 평가**: 실제 6개 문서 기반 24개 질의로 top_k=1/2/5 실측 완료 (2026-07-10) — 단위/수치 특정 질의에서 검색 정밀도가 낮아지는 약점을 확인함 (수치는 별도 보고, 영업 자료에는 "정밀도 X%, 특정 질의 유형은 개선 여지 있음" 형태로 정직하게 반영 권장).
- **성능 벤치마크**: 단일 노드 로컬 개발 환경(RTX 3080Ti, 12.9GB VRAM) 기준 실측 완료 (2026-07-10). `/search`(벡터 모드, top_k=5, 동시 10건): 평균 3.4초, P95 3.7초. `/chat`(로컬 Qwen2.5-3B, 동시성 없이 순차 측정 — GPU 메모리 경합 방지 목적): 첫 요청(모델 콜드 로드) 120초 초과, 이후 웜 상태에서 38~66초/건. **이 수치는 프로덕션 SLA가 아니며, 단일 로컬 GPU/순차 처리 기준이다.** 실제 동시 사용자 다중 채팅 부하, 클라우드 LLM(OpenAI/Anthropic BYOK) 사용 시나리오, 또는 vLLM 등 최적화된 서빙 스택 도입 전 수치이므로 영업 자료에 그대로 사용 금지 — "로컬 모델 기준 참고 수치"로만 인용할 것. 로컬 LLM 채팅 응답시간(38~66초, 콜드스타트 120초+)은 사용자 체감상 매우 느린 수준이며, 실서비스에는 클라우드 LLM(BYOK) 사용 또는 서빙 스택 최적화가 필수로 보인다.
