# Plan: 외부 에이전트 연동(MCP)

**Source PRD**: `.claude/prds/agentic-rag-governance-v3.prd.md`
**Selected Milestone**: 4 — 외부 에이전트 연동(MCP)
**Complexity**: Medium

## Summary
승인된 외부 에이전트(Claude Code·Claude Desktop 등)가 직원 본인의 권한 범위 안에서 v3의 검색, 원문 조회, 답변 도구를 쓰게 한다.
직원은 화면에서 개인 접근 토큰을 발급해 에이전트에 넣고, 에이전트는 그 직원이 볼 수 있는 문서만 본다. 모든 도구 호출은 감사 기록에 남고, 답변 도구는 답변 추적 기록에 "MCP 경로"로 남는다.

## 사용자 결정 (2026-11-11)
- 권한 모델: **사용자 위임 토큰**. 서비스 계정 권한과 OAuth 2.1은 이번 범위가 아니다.
- 도구 범위: **검색 + 원문 조회 + 답변**.

## 기본값 (질문 없이 정한 것, 바꾸려면 말해 달라)
1. MCP는 `MCP_ENABLED`(기본 false)로 켠다. 꺼져 있으면 토큰 발급과 MCP 호출이 모두 막힌다.
2. 토큰은 `dvp_` + 무작위 43자, 발급할 때 한 번만 보여 주고 SHA-256만 저장한다. 만료일은 필수(기본 90일, 최대 365일), 사람당 활성 토큰 10개까지.
3. 토큰은 본인과 관리자가 회수한다. 계정이 비활성화되면(AD 사용 중지 포함) 그 사람의 토큰도 바로 쓸 수 없다. 커넥터용 시스템 계정은 발급할 수 없다.
4. MCP 엔드포인트는 `POST /api/v1/mcp` 한 곳, Streamable HTTP의 무상태·JSON 응답 방식만 지원한다(SSE 스트림 없음). 웹 로그인 JWT는 받지 않고 개인 접근 토큰만 받는다.
5. 도구 5개: `list_collections`, `search_documents`, `read_chunk`, `read_document`, `ask`. 판정은 웹과 같은 `access_policy`를 쓴다. 볼 수 없는 문서와 없는 문서는 같은 메시지로 답해 존재를 드러내지 않는다.
6. 문서 본문은 신뢰하지 않는 데이터로 표시한다(결과에 `untrusted_content` 표시와 도구 설명의 안내). 문서 속 지시문을 따르지 말라는 뜻이다.
7. 감사: 도구 호출마다 `mcp.tool_call`(도구, 토큰 id, 범위, 결과 문서 id, 건수). 토큰 발급·회수는 `access_token.create`, `access_token.revoke`. 검색은 웹과 같이 검색 기록에 남는다.
8. `ask`는 웹 채팅과 같은 경로(대화·메시지 생성 → 채팅 워커)로 답하고, 최대 120초 기다린다. 모델은 `MCP_ANSWER_MODEL`(기본 로컬 qwen2.5-3b). 대화에 `channel=mcp`를 붙여 웹 채팅 목록에는 나오지 않게 하고, 답변 추적 기록에 `channel`과 토큰 id를 남긴다.
9. 호출 제한은 사용자당 분당 60회(답변 도구는 10회).
10. 공식 Python MCP SDK(2.3.0)는 쓰지 않는다. 새 주 버전이라 검증되지 않았고 httpx2·pyjwt 등 의존성이 크게 늘어난다. 무상태 JSON 방식은 JSON-RPC 몇 개면 되므로 직접 구현하고, 공식 SDK 클라이언트로 실제 연결해 맞는지 확인한다.

## Patterns to Mirror
| Category | Source | Pattern |
|---|---|---|
| 권한 판정 | `backend/app/services/access_policy.py`, `api/v1/permissions.py::check_document_access` | 모든 문서 접근은 한 곳의 규칙으로 |
| 검색 | `services/search_service.py::perform_search` | 웹 검색과 같은 함수, 같은 이중 확인 |
| 답변 | `api/v1/endpoints/chat.py::create_conversation`, `pipeline/tasks/chat.py::generate_answer` | 대화·메시지 생성 후 워커 |
| 감사 | `services/audit.py::log_audit` | action 문자열, detail JSON |
| 비밀값 | `services/source_locks.py`, `core/crypto.py` | 비밀값은 응답·로그에 넣지 않음 |
| 테스트 | `tests/unit/test_access_leak_matrix.py` | 손으로 쓴 기대값, 실제 Postgres + 메모리 Qdrant |

## Files to Change
| File | Action | Why |
|---|---|---|
| `backend/app/db/models/access_token.py` | CREATE | 개인 접근 토큰 |
| `backend/alembic/versions/*_mcp_access_tokens.py` | CREATE | 토큰 테이블, 대화·답변 추적의 channel·토큰 id |
| `backend/app/services/access_tokens.py` | CREATE | 발급, 해시, 검증 |
| `backend/app/api/v1/endpoints/access_tokens.py` | CREATE | 내 토큰, 관리자 토큰 목록·회수 |
| `backend/app/mcp/` | CREATE | JSON-RPC 처리와 도구 |
| `backend/app/api/v1/endpoints/chat.py`, `pipeline/tasks/chat.py`, `services/answer_trace.py` | UPDATE | channel 기록, 웹 목록에서 MCP 대화 제외 |
| `backend/app/core/config.py`, `docker-compose.yml` | UPDATE | MCP 설정 |
| 프런트 설정 화면, 관리자 토큰 화면, 감사·답변 추적 라벨 | UPDATE/CREATE | 토큰 발급·회수 화면 |
| 테스트, 문서 | CREATE/UPDATE | 누출 매트릭스에 MCP 경로 추가, 아키텍처 §11.7, 유지보수 1.14 |

## Tasks
1. 모델·마이그레이션·토큰 서비스.
2. 토큰 API(내 토큰 발급·목록·회수, 관리자 목록·회수)와 감사.
3. MCP JSON-RPC 처리(initialize, ping, tools/list, tools/call, 알림), 토큰 인증, 오류 형식.
4. 도구 5개와 감사, 답변 도구의 channel 기록.
5. 누출 매트릭스에 MCP 도구 경로 추가.
6. 프런트: 내 토큰 발급(한 번만 표시, 연결 예시), 관리자 토큰 목록·회수, 라벨.
7. 실제 MCP 클라이언트(공식 SDK, 임시 venv)로 연결해 끝에서 끝까지 확인.
8. 리뷰(코드·보안), 전체 테스트, 문서, 커밋.

## Validation
```bash
docker compose exec -T api sh -c "cd /app && /app/.venv/bin/pytest -q --no-cov tests"
docker run --rm ... node:22-alpine sh -c "npx tsc --noEmit -p . && npx eslint src && npx vitest run"
```

## Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| 직접 구현한 프로토콜이 클라이언트와 맞지 않는다 | Medium | 공식 SDK 클라이언트로 실제 연결해 확인한다 |
| 토큰 유출 | Medium | 만료 필수, 해시 저장, 회수, 계정 비활성화와 연동, 호출 감사 |
| 문서 속 프롬프트 인젝션 | Medium | 본문을 신뢰하지 않는 데이터로 표시, 쓰기 도구 없음 |
| 답변 도구가 GPU를 오래 잡는다 | Medium | 사용자당 분당 10회 제한, 120초 시간 제한 |

## Acceptance
- [ ] 다른 권한의 두 직원 토큰으로 같은 질의를 하면 각자 볼 수 있는 문서만 나온다(누출 매트릭스).
- [ ] 회수·만료·비활성 계정 토큰은 401.
- [ ] 모든 도구 호출이 감사 기록에, 답변은 답변 추적 기록에 MCP 경로로 남는다.
- [ ] 공식 MCP 클라이언트로 연결해 도구 목록과 호출이 동작한다.

## 구현 결과 (2026-11-11)

- 계획한 작업 1~8을 모두 마쳤다. 구조는 `docs/기술문서_시스템_아키텍처.md` §11.7에, 운영 절차는 `docs/유지보수_가이드.md` 1.14절에 정리했다.
- 공식 MCP Python SDK 2.3.0 클라이언트로 개발용 AD 사용자 두 명의 토큰을 써서 initialize, tools/list, 검색, 읽기, ask를 끝에서 끝까지 확인했다. 그룹 문서는 그룹 구성원만 찾고 읽었고, 다른 사용자가 같은 문서를 열면 거절됐다.
- 계획과 달라진 점: ask 대기 시간 기본값을 120초에서 180초로 늘렸다. 실제 워커에서 답변 하나가 143초 걸린 경우가 있었다. 사용자당 동시 대기 ask를 2건으로 제한했다. ask는 `readOnlyHint=false`로 알린다.
- 리뷰 반영: 대기 중 DB 연결 반납, 큐 실패 처리, 워커 오류 문구 숨김, JSON-RPC 형식 검사, 본문 크기 선검사, 거절과 제한과 취소 호출 감사, 인증 실패 IP 제한.
- 반영하지 않은 항목과 이유는 아키텍처 문서 §14의 35~39에 적었다(시간 초과 뒤에도 도는 답변 작업, 회수 뒤 진행 중인 ask, read_chunk 실행 범위, Redis 장애 시 호출 제한, 메타데이터 필드별 감싸기).
