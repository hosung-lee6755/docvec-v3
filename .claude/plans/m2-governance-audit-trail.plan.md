# Plan: 거버넌스·감사 증적 (v3 마일스톤 2)

**Source PRD**: `.claude/prds/agentic-rag-governance-v3.prd.md`
**Selected Milestone**: 2. 거버넌스·감사 증적
**Complexity**: Large

## Summary
채팅 답변 하나마다 **답변 추적 기록**을 남긴다. 기록에는 누가 물었는지, 그때 어떤 권한으로 판정했는지, 어떤 청크를 찾아 어떤 문서를 인용했는지, 어떤 모델로 만들었고 근거 검증을 통과했는지가 들어간다. 이 기록은 대화를 지워도 남는다. 관리자는 답변에서 근거 문서로, 거꾸로 문서에서 그 문서를 근거로 쓴 답변으로 추적할 수 있다. 같은 운영 데이터로 AI 기본법 제34조 항목별 근거 문서(docx)를 기간을 정해 내려받는다. 마일스톤 1에서 넘어온 결정 두 가지(등급 하향 권한 범위, 저장된 대화의 인용 재판정)도 여기서 처리한다.

## 코드 조사에서 확인한 사실 (계획의 근거)
1. **답변의 근거가 남지 않는다.** `chat.py`의 `generate_answer`(`app/pipeline/tasks/chat.py:407`)는 `ChatMessage.citations`에 인용 청크만 JSON으로 저장한다. 의도 분류 결과, 검색 후보 전체와 점수, 근거 검증 결과, 재검색 여부, 캐시 적중 여부, 판정에 쓴 권한은 어디에도 기록하지 않는다.
2. **대화를 지우면 답변 기록이 사라진다.** `DELETE /chat/conversations/{id}`(`app/api/v1/endpoints/chat.py:295`)는 메시지를 하드 삭제한다. 감사 증적은 대화와 별도로 보관해야 한다.
3. **모델·토큰 기록은 메시지와 연결되지 않는다.** `LLMUsageLog`(`app/db/models/llm_usage_log.py`)는 conversation_id까지만 있고 메시지 단위 연결이 없다. 캐시 적중 시에는 아무 기록도 남지 않는다.
4. **감사 로그는 상태 변경만 다룬다.** `log_audit`(`app/services/audit.py:10`)은 그룹, ACL, 등급 변경 등에서만 호출된다. 문서 원본 미리보기·다운로드(`documents/metadata.py:212`, `:281`)와 컬렉션 내보내기는 기록하지 않는다.
5. **검색 기록에 결과 문서가 없다.** `SearchHistory`(`app/services/search_service.py:137`)는 질의와 결과 수만 남긴다.
6. **관리자 감사 화면은 있다.** `GET /admin/audit-logs`(`app/api/v1/endpoints/admin.py:17`)와 `AuditLogPage.tsx`(151줄)가 필터·페이지네이션을 제공한다. 새 화면은 이 패턴을 따른다.
7. **docx 생성 라이브러리가 이미 있다.** `python-docx`가 의존성에 들어 있어 새 패키지 없이 근거 문서를 만들 수 있다.

## 이번 마일스톤에서 확정할 결정 (기본값으로 진행, 바꾸려면 말씀해 주세요)
1. **추적 기록은 관리자만 본다.** 다만 관리자도 문서 열람 규칙을 건너뛰지 못하므로, 추적 상세 화면의 **청크 본문은 그 관리자가 지금 볼 수 있는 문서일 때만** 보여 준다. 볼 수 없는 문서는 파일명, 등급, 청크 id만 보인다. 질의와 답변 본문은 감사 목적상 그대로 보여 주고, 추적 기록을 열람한 사실도 감사 로그에 남긴다(`answer_trace.view`).
2. **추적 기록에는 청크 본문을 복사하지 않는다.** 청크 id, 문서 id, 그 시점의 파일명과 유효 등급, 점수, 순위, 본문 해시만 저장한다. 본문 복사본이 권한 밖으로 새는 경로를 만들지 않기 위해서다. 문서가 나중에 바뀌었는지는 해시로 확인한다.
3. **보관 기간은 정하지 않는다(무기한 보관).** AI 기본법의 보관 기간을 원문으로 확인하지 못했으므로 자동 삭제 작업은 만들지 않는다. 법률 검토 뒤 별도로 정한다.
4. **근거 문서는 "운영 데이터 요약 + 담당자 작성란" 형식이다.** 제34조 항목마다 시스템이 채울 수 있는 수치·설정은 자동으로 넣고, 해석이 필요한 부분은 "법률 검토 필요" 표시와 함께 비워 둔다. 법적 적합성을 시스템이 판정하지 않는다.
5. **등급을 낮추거나 ACL 제한을 푸는 일은 문서 업로더와 컬렉션 소유자만 할 수 있다.** 등급을 올리거나 제한을 추가하는 일은 지금처럼 문서 editor도 할 수 있다. 마일스톤 1의 알려진 제약 16번을 이렇게 닫는다.
6. **저장된 대화를 다시 열 때, 지금 볼 수 없는 문서의 인용은 가린다.** 인용 칸에는 "열람 권한이 없는 문서"만 표시하고 본문과 파일명은 내려보내지 않는다. 답변 본문은 이미 그 사용자에게 보여 준 것이므로 그대로 둔다. 마일스톤 1의 알려진 제약 17번을 이렇게 닫는다.
7. **채팅 답변에 "AI가 생성한 답변"을 표시한다**(제31조 대응). 화면과 내보낸 근거 문서 모두에 넣는다.

## Patterns to Mirror
| Category | Source | Pattern |
|---|---|---|
| Naming | `app/services/audit.py:10`, `app/services/access_policy.py` | 서비스 모듈 함수 `log_*`, `build_*`. 감사 액션명은 `<resource>.<verb>` |
| Errors | `app/services/audit.py:25` | 기록 실패가 본 작업(답변 생성)을 막지 않는다. 예외는 로그로만 남긴다 |
| Data access | `chat.py` 워커는 sync 세션과 `db.query`, API는 async 세션과 `select` | 추적 기록 작성은 워커(sync), 조회는 API(async) |
| Models/Migration | `app/db/models/audit_log.py`, `alembic/versions/7a1c2e9d4b6f_*.py` | 사용자 FK는 `ondelete="SET NULL"`로 기록 보존, down_revision은 현재 head `7a1c2e9d4b6f` |
| Admin API | `app/api/v1/endpoints/admin.py:17` | `require_admin`, 필터 쿼리 파라미터, `{total, items}` 응답, limit ≤ 200 |
| Tests | `tests/unit/test_access_leak_matrix.py`, `tests/unit/api_pg_helpers.py` | 실제 Postgres와 SAVEPOINT 롤백, `world` 픽스처, 손으로 쓴 기대값 |
| Frontend | `frontend/src/pages/AuditLogPage.tsx`, `src/hooks/useAudit.ts` | 관리 메뉴 페이지, react-query 훅, KRDS 표·필터 |

## Files to Change
| File | Action | Why |
|---|---|---|
| `backend/app/db/models/answer_trace.py` | CREATE | `AnswerTrace`(답변 1건), `AnswerTraceSource`(검색 후보·인용 청크, document_id 인덱스) |
| `backend/alembic/versions/<new>_answer_traces.py` | CREATE | 두 테이블, `search_history.result_document_ids` 컬럼 |
| `backend/app/services/answer_trace.py` | CREATE | 추적 기록 생성(sync), 권한 스냅샷, 본문 해시 계산 |
| `backend/app/pipeline/tasks/chat.py` | UPDATE | 정상·캐시 적중·재검색·실패 경로마다 추적 기록 작성, 소요 시간과 토큰 기록 |
| `backend/app/api/v1/endpoints/answer_traces.py` | CREATE | 관리자용 목록·상세(청크 본문은 열람 규칙 적용), 문서별 역추적 |
| `backend/app/services/governance_report.py` | CREATE | 기간별 운영 데이터 집계와 제34조 항목별 docx 생성 |
| `backend/app/api/v1/endpoints/governance.py` | CREATE | 근거 문서 내려받기(관리자), 내려받은 사실 감사 |
| `backend/app/api/v1/endpoints/chat.py` | UPDATE | 대화 조회 시 지금 볼 수 없는 문서의 인용을 가림 |
| `backend/app/api/v1/endpoints/documents/metadata.py` | UPDATE | 미리보기·다운로드 감사(`document.preview`, `document.download`), 등급 하향 권한 제한 |
| `backend/app/api/v1/endpoints/documents/acl.py` | UPDATE | 제한 해제·항목 제거 시 업로더·컬렉션 소유자만 허용 |
| `backend/app/api/v1/endpoints/collections.py` | UPDATE | 내보내기 감사(`collection.export`), 기본 등급 하향은 컬렉션 소유자만 |
| `backend/app/services/search_service.py` | UPDATE | 검색 기록에 결과 문서 id 저장 |
| `backend/app/api/v1/router.py` | UPDATE | 새 라우터 등록 |
| `frontend/src/pages/AnswerTracesPage.tsx` | CREATE | 답변 추적 목록(사용자·기간·문서 필터)과 상세 패널 |
| `frontend/src/pages/GovernanceReportPage.tsx` | CREATE | 기간 선택과 근거 문서 내려받기 |
| `frontend/src/hooks/useAnswerTraces.ts` | CREATE | react-query 훅 |
| `frontend/src/components/chat/*` | UPDATE | "AI가 생성한 답변" 표시, 가려진 인용 표시 |
| `frontend/src/components/document-detail/AccessPanel.tsx` | UPDATE | 하향·해제 권한이 없으면 해당 동작 비활성화와 안내 |
| `frontend/src/App.tsx`, `components/Layout.tsx` | UPDATE | 관리 메뉴에 "답변 추적", "AI 기본법 근거 문서" |
| `docs/기술문서_시스템_아키텍처.md`, `docs/유지보수_가이드.md` | UPDATE | 추적 구조, 근거 문서 생성 절차, 알려진 제약 16·17 갱신 |

## 추적 기록에 담는 것
- **누가, 언제**: 사용자 id, 사용자명 스냅샷, 시스템 역할, 대화·메시지 id(대화가 지워지면 NULL), 생성 시각, 소요 시간
- **권한 맥락**: 열람등급, 소속 그룹 id 목록, 접근 가능 컬렉션 수, 권한 지문(`AccessContext.fingerprint()`), 질의 범위(컬렉션·프로젝트)
- **검색**: 의도 분류 결과, 검색 경로(일반·표·요약), 재검색 여부, 후보 청크 목록(청크 id, 문서 id, 파일명·유효 등급 스냅샷, 점수, 순위, 인용 여부, 본문 해시)
- **생성**: 모델 키, 백엔드, 검증 모델, 근거 검증 결과(통과·실패·미실행), 시스템 프롬프트 출처(프로젝트·사용자·기본)와 해시, 입출력 토큰, 캐시 적중 여부
- **결과**: 질의 원문, 답변 원문, 상태(DONE·FAILED), 오류 메시지

## Tasks
### Task 1: 추적 기록 모델과 마이그레이션
- **Action**: `AnswerTrace`, `AnswerTraceSource` 모델과 마이그레이션을 만들고, `search_history.result_document_ids`(JSON, nullable)를 추가한다. 사용자·메시지 FK는 `SET NULL`로 둬서 사용자나 대화를 지워도 기록이 남게 한다.
- **Mirror**: `audit_log.py`의 FK 정책, `7a1c2e9d4b6f` 마이그레이션 형식
- **Validate**: `alembic upgrade head` → `downgrade -1` → `upgrade head`가 테스트 DB에서 성공

### Task 2: 채팅 워커에서 추적 기록 작성 (TDD)
- **Action**: `services/answer_trace.py`에 `record_answer_trace(db, ...)`를 만들고, `generate_answer`의 네 경로(정상, 캐시 적중, 재검색 후 재생성, 실패)에서 호출한다. 기록 실패는 답변 생성을 막지 않는다. 검색 함수가 점수와 청크 id를 돌려주는지 확인하고, 빠져 있으면 반환값에 더한다.
- **Mirror**: `log_audit`의 실패 격리, `chat.py`의 sync 세션 사용
- **Validate**: 새 테스트 `test_answer_trace_recording.py` — 경로별로 기록이 1건 생기는지, 권한 스냅샷과 인용 여부가 맞는지, 대화를 지워도 기록이 남는지, 기록 저장이 실패해도 답변 상태가 DONE인지

### Task 3: 관리자용 추적 조회 API (TDD)
- **Action**: `GET /admin/answer-traces`(사용자·기간·문서·컬렉션·근거 검증 실패 필터), `GET /admin/answer-traces/{id}`(상세), 문서 기준 역추적은 목록의 `document_id` 필터로 처리한다. 상세의 청크 본문은 `check_document_access`로 관리자 본인의 열람 가능 여부를 판정해 볼 수 있을 때만 현재 본문을 붙이고, 해시가 다르면 "기록 이후 문서가 바뀜"으로 표시한다. 상세 조회는 `answer_trace.view`로 감사한다.
- **Mirror**: `admin.py:17` 목록 API
- **Validate**: 새 테스트 `test_api_answer_traces.py` — 관리자 외 403, 필터 결과, 열람등급이 낮은 관리자에게 대외비 청크 본문이 나가지 않는지

### Task 4: 조회 감사 확대 (TDD)
- **Action**: 문서 미리보기, 다운로드 URL 발급, 컬렉션 내보내기에 감사 행을 남긴다. 검색 기록에 결과 문서 id를 저장한다. 목록·상세 같은 일반 조회는 양이 많아 감사 대상에서 뺀다.
- **Mirror**: `documents/acl.py`의 `log_audit` 호출 위치(커밋과 같은 트랜잭션)
- **Validate**: 각 엔드포인트 호출 뒤 감사 행이 1건 생기는지 확인하는 테스트

### Task 5: 마일스톤 1에서 넘어온 권한 정리 (TDD)
- **Action**: 결정 5(등급 하향·제한 해제는 업로더와 컬렉션 소유자만), 결정 6(저장된 대화의 인용 가림)을 구현한다. 판정은 `access_policy.py`에 함수로 추가해 규칙을 한 곳에 둔다.
- **Mirror**: `access_policy.can_view`, `documents/acl.py`의 403 처리
- **Validate**: editor가 하향하면 403, 업로더는 성공. 권한을 회수한 뒤 대화를 다시 열면 인용이 가려지는지. 기존 누출 매트릭스 전부 통과

### Task 6: AI 기본법 근거 문서 생성 (TDD)
- **Action**: `governance_report.py`가 기간을 받아 운영 데이터를 집계하고 docx를 만든다. 항목은 제34조에 맞춰 위험관리(권한 모델 설정, 등급별 문서 수, 권한 변경 이력 수), 설명(답변 생성 방식, 근거 검증 통과율, 재검색 비율), 이용자 보호(PII 처리 설정과 탐지 건수), 사람의 감독(관리자 조치 이력, 검증 실패 답변 목록), 기록 보관(추적 기록 건수와 기간)으로 나눈다. 해석이 필요한 칸은 "법률 검토 필요"로 표시한다. `GET /admin/governance/report?from=&to=`로 내려받고, 내려받은 사실을 감사한다.
- **Mirror**: `collections.py`의 내보내기 응답 방식
- **Validate**: 고정 데이터로 만든 보고서에서 항목 제목과 수치가 기대값과 같은지 python-docx로 읽어 확인

### Task 7: 프런트엔드
- **Action**: 관리 메뉴에 "답변 추적"과 "AI 기본법 근거 문서" 페이지를 추가한다. 채팅 답변에 "AI가 생성한 답변" 표시를 넣고, 가려진 인용은 "열람 권한이 없는 문서"로 보여 준다. AccessPanel은 하향·해제 권한이 없을 때 해당 동작을 막고 이유를 보여 준다.
- **Mirror**: `AuditLogPage.tsx`, `GroupsPage.tsx`, `useAudit.ts`
- **Validate**: vitest(새 페이지 렌더링, 가려진 인용 표시, AccessPanel 비활성화), tsc, eslint

### Task 8: 문서, 리뷰, 커밋
- **Action**: 아키텍처 문서에 추적 구조 절을 추가하고 알려진 제약 16·17을 갱신한다. 유지보수 가이드에 근거 문서 생성 절차와 FAQ를 넣는다. code-reviewer와 security-reviewer로 검토하고 지적을 반영한 뒤 커밋한다.
- **Validate**: 아래 Validation 전체 통과

## Validation
```bash
# 백엔드 (api 컨테이너)
docker compose exec -T api sh -c "cd /app && /app/.venv/bin/pytest -q -p no:cacheprovider --no-cov tests/unit/test_answer_trace_recording.py tests/unit/test_api_answer_traces.py tests/unit/test_governance_report.py tests/unit/test_access_leak_matrix.py tests/unit/test_access_review_regressions.py"
docker compose exec -T api sh -c "cd /app && /app/.venv/bin/pytest -q -p no:cacheprovider --no-cov"
# 프런트엔드 (node 컨테이너)
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)/frontend:/app" -v p3_fe_node_modules:/app/node_modules -w /app node:22-alpine sh -c "npx tsc --noEmit -p . && npx eslint src && npx vitest run"
```

## Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| 추적 상세 화면이 권한 밖의 문서 본문을 관리자에게 보여 주는 새 누출 경로가 된다 | Medium | 청크 본문을 저장하지 않고, 보여 줄 때마다 열람 규칙으로 판정한다. 누출 매트릭스에 추적 상세 경로를 추가한다 |
| 추적 기록 작성이 답변 생성을 느리게 하거나 실패시킨다 | Low | 한 트랜잭션에서 묶어 쓰고, 실패해도 답변은 DONE으로 끝낸다. 실패는 로그로 남긴다 |
| 추적 기록이 빠르게 쌓여 DB가 커진다 | Medium | 답변 1건당 후보 청크 수십 행 수준이다. document_id와 created_at에 인덱스를 두고, 보관 기간은 법률 검토 뒤 정한다 |
| 근거 문서를 법적 적합성 증명으로 오해한다 | Medium | 문서 첫 장과 해석 칸에 "운영 데이터 요약이며 법률 검토가 필요함"을 명시한다 |
| 등급 하향 권한을 좁혀 기존 editor 작업 흐름이 막힌다 | Low | 화면에서 이유를 보여 주고, 업로더나 컬렉션 소유자에게 요청하도록 안내한다 |
| PRD가 법률 검토를 착수 조건으로 뒀는데 아직 검토가 없다 | High | 법적 해석이 들어가는 부분은 담당자 작성란으로 남기고, 시스템은 운영 데이터만 채운다. 검토 결과가 나오면 항목 구성만 바꾸면 되도록 항목 정의를 한 곳에 모은다 |

## Acceptance
- [ ] 모든 채팅 답변(캐시 적중, 실패 포함)에 추적 기록이 남고, 대화를 지워도 남는다
- [ ] 관리자가 답변에서 근거 문서로, 문서에서 그 문서를 쓴 답변으로 추적할 수 있다
- [ ] 추적 상세가 관리자의 열람 권한 밖 본문을 보여 주지 않는다(누출 테스트 통과)
- [ ] 기간을 정해 제34조 항목별 근거 문서(docx)를 내려받을 수 있다
- [ ] 미리보기·다운로드·내보내기·추적 열람·근거 문서 내려받기가 감사 로그에 남는다
- [ ] 마일스톤 1의 알려진 제약 16·17이 결정대로 해소된다
- [ ] 백엔드 전체 테스트와 프런트 검사 통과, 기존 누출 매트릭스 유지
