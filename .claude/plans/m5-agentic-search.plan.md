# Plan: 에이전틱 검색 (심층 검색)

**Source PRD**: `.claude/prds/agentic-rag-governance-v3.prd.md`
**Selected Milestone**: 5. 에이전틱 검색
**Complexity**: Medium

## Summary
여러 문서와 조건이 얽힌 복합 질문을 하위 질문으로 나눠 따로 검색하고, 근거가 약한 하위 질문만 한 번 더 찾은 뒤, 모은 근거로 한 번에 종합해 답한다. 사용자가 켜는 "심층 검색" 모드로만 동작하고, 일반 질문의 속도와 동작은 그대로 둔다. 하위 질문마다 무엇을 찾았는지를 화면과 답변 추적 기록에 남긴다.

## 사용자 결정 (2026-11-11)
- 실행 방식: 사용자가 켜는 심층 검색. 채팅 입력창 스위치와 MCP ask의 `deep` 인자로만 켠다.
- 모델과 단계: 단계 상한을 둔 경량 설계. 하위 질문은 최대 3개, 보강 검색은 하위 질문마다 1회. LLM은 분해와 종합(그리고 기존 근거 검증)에만 쓰고, 근거 충분성은 검색 점수로 판단한다. 로컬 기준 목표는 2분 이내다.
- 지식그래프: 이번 범위에서 뺀다.

## 측정한 출발점
- 로컬 Qwen2.5-3B 답변 한 건 39~78초(재검색 포함 78초), LLM 호출 한 번 20~30초. GPU 12GB 중 11.9GB 사용 중이라 7B를 함께 올릴 수 없다.
- 심층 검색은 의도 분류를 건너뛰고 분해 1회, 종합 1회, 근거 검증 1회를 쓴다. 검증 실패 시 재검색은 하지 않는다(이미 보강 검색을 했다). 예상 60~100초.

## 기본값
1. 하위 질문 최대 3개. 분해 결과를 해석하지 못하거나 하나뿐이면 원 질문 하나로 검색한다(일반 경로와 같은 검색).
2. 하위 질문마다 상위 4개 청크를 검색한다. 결과가 2개 미만이거나 최고 재순위 점수가 0 미만이면, "원 질문 + 하위 질문"으로 8개를 한 번 더 찾는다.
3. 근거는 청크 id로 중복을 없애고 하위 질문 순서대로 모아 최대 10개까지 쓴다. 하위 질문 검색이 모두 비면 원 질문으로 한 번 찾는다.
4. 종합 프롬프트에는 하위 질문 목록과 번호 붙은 발췌문을 넣는다. 인용 번호는 기존과 같이 발췌문 순서다.
5. 모든 검색은 기존 `_retrieve_chunks`(권한 필터와 Postgres 재확인 포함)를 그대로 부른다. 하위 질문 문장도 권한 밖 문서를 끌어오지 못한다.
6. 진행 상황은 Redis `chat_progress:{message_id}`에 단계별로 쓰고, 끝나면 메시지와 답변 추적의 `agent_steps`에 저장한다. 하위 질문, 검색 횟수, 찾은 문서 id와 파일명, 보강 여부, 단계별 소요 시간을 담는다(본문은 넣지 않는다).
7. 답변 캐시 키에 모드를 넣는다.
8. MCP ask에 `deep`(기본 false)을 더하고, 심층 검색의 대기 시간은 `MCP_DEEP_ANSWER_TIMEOUT_SECONDS`(기본 300)로 따로 둔다.
9. 심층 검색은 표 질의와 요약 조회 경로를 쓰지 않는다. 청크 검색만 쓴다.
10. 사용량 로그와 답변 추적은 기존과 같은 방식으로 남긴다.

## Files to Change
| File | Action | Why |
|---|---|---|
| `backend/alembic/versions/b8e4f6a0c3d5_agentic_search.py` | CREATE | chat_messages, answer_traces에 mode, agent_steps |
| `backend/app/db/models/chat_message.py`, `answer_trace.py` | UPDATE | 컬럼 |
| `backend/app/services/agentic/planner.py` | CREATE | 분해 프롬프트와 견고한 해석 |
| `backend/app/services/agentic/deep_search.py` | CREATE | 하위 질문 검색, 보강, 근거 병합, 종합 메시지 |
| `backend/app/pipeline/tasks/chat.py` | UPDATE | 모드 분기, 진행 기록, 캐시 키 |
| `backend/app/services/answer_trace.py`, `endpoints/answer_traces.py` | UPDATE | mode, agent_steps 기록과 노출 |
| `backend/app/api/v1/endpoints/chat.py` | UPDATE | 요청 mode, 응답 mode·agent_steps·progress |
| `backend/app/mcp/tools.py`, `core/config.py`, `docker-compose.yml` | UPDATE | ask의 deep 인자와 대기 시간 |
| `frontend/src/hooks/useChat.ts`, `pages/ChatPage.tsx`(와 하위 컴포넌트) | UPDATE | 심층 검색 스위치, 진행 단계, 검색 과정 펼침 |
| `frontend/src/pages/AnswerTracesPage.tsx`, `hooks/useAnswerTraces.ts` | UPDATE | 모드 배지와 검색 과정 |
| 테스트 | CREATE/UPDATE | planner 해석, deep_search 흐름, 누출 매트릭스 심층 경로, API, MCP, 프론트 |

## Tasks
1. 마이그레이션과 모델.
2. planner: JSON 배열, 번호 목록, 줄바꿈 목록을 모두 해석하고 중복과 빈 줄을 버린다. 3개를 넘으면 자른다.
3. deep_search: 위 기본값 2~4, 6. 검색 함수와 진행 콜백을 주입받아 테스트한다.
4. chat 작업 분기와 추적 기록.
5. API와 MCP.
6. 프론트엔드.
7. 누출 매트릭스에 심층 경로를 더한다(하위 질문 검색이 사용자별 기대 문서만 돌려주는지).
8. 실제 워커로 복합 질문을 돌려 지연과 결과를 측정한다.
9. 리뷰, 문서(아키텍처 §11.8, 유지보수 1.15, 설계서 15.4), 전체 테스트, 커밋.

## Validation
- 백엔드: api 컨테이너에서 pytest(누출 매트릭스, 채팅, MCP, 새 단위 테스트), ruff.
- 프론트: tsc, eslint, vitest.
- 실측: 로컬 3B로 복합 질문 1건 이상, 지연과 하위 질문 기록 확인.

## Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| 3B 모델이 분해를 엉뚱하게 한다 | High | 해석 실패나 1개면 원 질문 검색으로 되돌아가고, 하위 질문 검색이 모두 비면 원 질문으로 한 번 찾는다 |
| 지연이 2분을 넘는다 | Medium | LLM 호출 3회로 묶고, 실측 결과를 문서에 남긴다 |
| 하위 질문 문장이 권한 밖 문서를 찾는다 | Low | 모든 검색이 `_retrieve_chunks`를 지나고 누출 매트릭스로 확인한다 |

## Acceptance
- [x] 심층 검색을 켠 복합 질문이 하위 질문별 근거를 모아 인용 붙은 답을 낸다
- [x] 진행 단계와 검색 과정이 채팅 화면과 답변 추적에 보인다
- [x] 일반 질문의 동작과 캐시는 바뀌지 않는다
- [x] 누출 매트릭스 심층 경로 0건

## 구현 결과 (2026-11-11)
- 위 Tasks 1~9를 모두 마쳤다. 구조와 기록 형식은 아키텍처 문서 §11.8, 운영은 유지보수 가이드 1.15절에 있다.
- 실측(RTX 3080 Ti, Qwen2.5-3B, 개발용 문서 3건, MCP로 같은 비교 질문): 심층 검색 48.3초(나누기 3.9초, 검색 9.5초, 답변 9.6초, 근거 확인 6.4초), 일반 모드 37.3초. 두 모드 모두 맞는 답을 냈고 근거 확인을 통과했다. 목표인 2분 안에 들어왔다.
- 문서가 세 건뿐이라 심층 검색의 품질 이득은 보이지 못했다. 심층 답 중간에 틀린 문장이 한 번 섞였다가 바로잡혔다(아키텍처 문서 §14 제약 44). 문서가 많은 컬렉션에서 다시 재야 한다.
- 리뷰 반영: 캐시 적중 시 검색 과정 문서 재판정, MCP 결과의 검색 과정 가림, 대화 시작의 호출 제한과 심층 검색 분당 5건 제한, 검색 하나의 실패 허용과 전부 실패 시 작업 실패, 실패해도 추적에 검색 과정 보존, 실패 시 진행 키 정리, 청크 중복 키를 sha256으로.
- 남긴 것: 심층 검색의 의도 분류, 이어 묻기 문맥, LLM 기반 충분성 판단(아키텍처 문서 §14 제약 40~42).
