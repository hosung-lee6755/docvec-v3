# Plan: 문서인식·검색 품질 노출 UI

**Source PRD**: `.claude/prds/agentic-rag-governance-v3.prd.md`
**Selected Milestone**: 6. 문서인식·검색 품질 노출 UI (v2 #2)
**Complexity**: Large

## Summary
백엔드에 이미 있는 검색 점수, 쪽별 OCR 신뢰도, 사전 적용 기록을 사용자가 화면에서 보고, 검색 방식은 컬렉션마다 설정한다. 지금은 채팅 인용에 점수가 없고, 쪽별 신뢰도를 돌려주는 API가 없으며, 사전 적용은 문맥 없이 원문과 치환어만 보인다. 검색 설정은 코드 상수다.

## 사용자 결정 (2026-11-11)
| 질문 | 결정 |
|---|---|
| 검색 설정 범위 | 컬렉션 단위 설정. 컬렉션 소유자가 검색 방식, 결과 수, MMR, 재순위 사용 여부를 정하고 검색과 채팅이 따른다. 검색 화면에서는 질의마다 MMR과 결과 수만 바꿀 수 있다 |
| 인용 점수 노출 | 모든 사용자에게 보여 주되 접어 둔다. 답변 추적에도 같은 값을 남긴다 |
| OCR 신뢰도 | 문서 상세의 쪽별 막대, 문서 목록의 품질 열과 필터, 신뢰도 낮은 쪽에서 나온 검색 결과와 인용의 경고 배지 |
| 사전 적용 결과 | 문맥 속 강조, 사전 항목 이름과 버전, 문서별 항목 끄기, 채팅의 검색어 확장 표시 |

## 조사로 확인한 사실
- 검색 화면(`perform_search`)은 벡터 또는 하이브리드이고 재순위가 없다. 채팅(`_retrieve_chunks`)은 하이브리드 융합 뒤 재순위를 항상 하고, 인용에는 점수 하나만 남긴다.
- 재순위 점수는 `normalize=True`라 0~1이다. 마일스톤 5의 심층 검색은 이를 로짓으로 보고 "0 미만이면 약함"으로 판단해, 점수 기준 보강이 한 번도 발동하지 않는다(버그). 0.5로 고친다.
- `ocr_page_confidence`는 Tesseract로 읽은 쪽만 `{page_number, confidence, word_count}`로 저장하고, 어떤 API도 돌려주지 않는다. 품질 블록 기준값은 0.5다.
- 사전 적용 기록의 `chunk_id`와 `node_id`는 채워지지 않고, 위치 값은 블록 실행 중의 본문 기준이라 청크 본문에 바로 표시할 수 없다.
- 사전 적용 "되돌리기"는 `reverted` 표시만 남기고, 사전 블록이 이를 보지 않아 재처리해도 같은 치환이 다시 일어난다(버그).
- 채팅은 사전의 검색어 확장(SEARCH_EXPAND)을 쓰지 않는다. 검색 화면만 쓴다.

## 기본값 (사용자 결정을 구체화)
1. 컬렉션 검색 설정은 `collections.search_settings`(JSON, null이면 기본값)에 둔다. 항목: `mode`(hybrid, vector), `top_k`(3~10, 채팅 근거 수), `rerank`(bool), `diversify`(bool), `vector_weight`(0.1~0.9, 하이브리드에서 벡터 비중). 기본값은 지금 채팅 동작과 같다: hybrid, 5, 재순위 켬, MMR 끔, 0.6.
2. 설정을 바꿀 수 있는 사람은 컬렉션의 다른 설정을 바꿀 수 있는 사람과 같다(컬렉션 수정 권한).
3. 채팅은 범위가 컬렉션 하나일 때만 그 설정을 따른다. 프로젝트 전체나 범위 없음이면 기본값이다. 심층 검색은 하위 질문마다 정한 개수를 그대로 쓴다.
4. 검색 화면은 컬렉션을 고르면 그 설정이 기본값이 되고, 질의마다 결과 수와 MMR만 바꾼다. (구현 중 변경) 검색 화면은 재순위를 하지 않는다. API 프로세스에 재순위 모델을 올리지 않기 위해서이며, 응답의 `applied.rerank_in_chat`으로 채팅의 재순위 여부만 알린다. 방식을 넘기지 않고 저장된 컬렉션 설정도 없는 검색 API 호출은 예전처럼 의미 검색이다.
5. 인용과 검색 결과에 붙이는 근거: 벡터 점수, 키워드(BM25) 점수, 융합 점수, 재순위 점수, 질문과 겹친 낱말(형태소 기준 최대 10개), 그 쪽의 OCR 신뢰도. 가린 인용에는 넣지 않는다.
6. OCR 신뢰도 기준은 `OCR_LOW_CONFIDENCE`(기본 0.5, 품질 블록 기본값과 같음)다. OCR을 하지 않은 쪽은 판단하지 않는다.
7. 문서 목록 필터는 "OCR 신뢰도 낮은 쪽 있음"과 품질 상태(검토 필요, 실패)다.
8. 사전 적용 기록에 앞뒤 문맥(각 40자)을 새로 저장한다. 이전 기록은 문맥 없이 보인다.
9. 문서별 끄기는 `document_dictionary_exclusions(document_id, entry_id)` 테이블에 두고, 세 사전 블록(불용어, 동의어, 사용자 사전)이 다음 처리부터 그 항목을 건너뛴다. 되돌리기도 같은 문서의 (항목, 원문) 쌍을 건너뛰도록 고친다. 그래서 되돌리기는 그 문서 안의 같은 표현 전체에 적용된다.
10. 채팅도 검색어 확장을 쓰고, 덧붙인 낱말을 메시지(`chat_messages.expanded_terms`)에 남겨 답변 아래에 보여 준다.

## Files to Change
| File | Action | Why |
|---|---|---|
| `backend/alembic/versions/c9f1a3b5d7e9_quality_visibility.py` | CREATE | search_settings, 인용 점수, 사전 문맥, 문서별 제외, expanded_terms |
| `backend/app/services/search_settings.py` | CREATE | 설정 검증, 기본값, 컬렉션별 해석 |
| `backend/app/services/retrieval_evidence.py` | CREATE | 겹친 낱말, OCR 신뢰도 조회와 표시 |
| `backend/app/pipeline/tasks/chat.py` | UPDATE | 컬렉션 설정 적용, 점수 보존, 검색어 확장 |
| `backend/app/services/search_service.py`, `schemas/search.py` | UPDATE | 설정 적용, 재순위, 근거 필드 |
| `backend/app/services/agentic/deep_search.py` | UPDATE | 재순위 점수 기준 0.5 |
| `backend/app/api/v1/endpoints/collections.py` | UPDATE | search_settings 조회와 수정 |
| `backend/app/api/v1/endpoints/chat.py`, `answer_traces.py`, `services/answer_trace.py` | UPDATE | 인용 근거 필드, 가림, 추적 기록 |
| `backend/app/api/v1/endpoints/documents/*` | UPDATE | 쪽별 신뢰도 API, 목록 품질 필터, 사전 적용 문맥과 문서별 제외 |
| `backend/app/pipeline/blocks/normalization_blocks.py` | UPDATE | 문맥 저장, 제외와 되돌리기 반영 |
| `frontend/src/components/collections/SearchSettingsSection.tsx` | CREATE | 컬렉션 검색 설정 |
| `frontend/src/components/chat/CitationEvidence.tsx` | CREATE | 인용 근거 펼침, OCR 경고 |
| `frontend/src/pages/SearchPage.tsx`, `ChatPage.tsx`, `AnswerTracesPage.tsx`, `DocumentsPage.tsx` | UPDATE | 근거, 배지, 필터 |
| `frontend/src/components/document-detail/QualityTab.tsx`, `DictionaryApplicationsTab.tsx` | UPDATE | 쪽별 막대, 문맥 강조, 문서별 끄기 |

## Tasks
1. 마이그레이션과 모델.
2. 검색 설정 서비스와 컬렉션 API.
3. 채팅 검색: 설정 적용, 점수 보존, 겹친 낱말, OCR 표시, 검색어 확장. 심층 검색 기준 수정.
4. 검색 화면 API: 설정 적용, 근거 필드(재순위는 하지 않음).
5. 인용 응답과 가림, 답변 추적 기록과 상세.
6. 쪽별 OCR 신뢰도 API와 문서 목록 품질 필터.
7. 사전 블록: 문맥 저장, 문서별 제외, 되돌리기 반영. 적용 목록 API와 제외 API.
8. 프론트엔드 화면 전부.
9. 리뷰, 문서(아키텍처 §11.9, 유지보수 1.16, 설계서 15.4), 전체 테스트, 커밋.

## Validation
- 백엔드: api 컨테이너 pytest(새 단위 테스트, 채팅, 검색, 누출 매트릭스, 사전 블록), 전체 스위트.
- 프론트: tsc, eslint, vitest.
- 실측: "심층 검색 테스트" 컬렉션으로 설정을 바꿔 검색과 채팅 결과가 따라 바뀌는지 확인한다.

## Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| 인용 근거 필드가 가린 인용으로 새어 나간다 | Medium | 가림 함수가 새 필드도 비우고, 누출 매트릭스와 가림 테스트로 확인한다 |
| 채팅에 검색어 확장을 넣어 답변 품질이 바뀐다 | Low | 확장은 사전의 SEARCH_EXPAND 항목만 쓰고, 덧붙인 낱말을 화면과 기록에 남긴다 |
| 설정으로 재순위를 끄면 채팅 품질이 떨어진다 | Medium | 기본값은 켬이고, 설정 화면에 영향을 적는다 |
| CollectionsPage가 이미 1,200줄을 넘는다 | High | 새 설정은 별도 컴포넌트로 만든다 |

## Acceptance
- [ ] 컬렉션 검색 설정을 바꾸면 그 컬렉션의 검색과 채팅이 따른다
- [ ] 채팅 인용과 검색 결과에서 점수, 겹친 낱말, OCR 경고를 볼 수 있고, 가린 인용에는 나오지 않는다
- [ ] 문서 상세에서 쪽별 OCR 신뢰도를 보고, 문서 목록에서 신뢰도 낮은 문서를 거른다
- [ ] 사전 적용을 문맥과 함께 보고, 문서별로 항목을 끄면 재처리부터 적용되지 않는다. 되돌리기도 실제로 반영된다
