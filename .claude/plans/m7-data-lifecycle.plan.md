# Plan: 데이터관리 고도화 (문서 버전 수명주기, 골든쿼리 회귀)

**Source PRD**: `.claude/prds/agentic-rag-governance-v3.prd.md`
**Selected Milestone**: 7. 데이터관리 고도화 (v2 #3)
**Complexity**: Large

## Summary
같은 문서의 새 내용이 들어오면 새 버전으로 묶고, 검색과 답변에는 현재 버전만 쓴다. 문서는 현재, 이전, 보관 상태를 거치고 만료일이 지나면 자동으로 보관된다. 골든쿼리 평가는 채팅과 같은 검색 경로로 워커에서 돌리고, 기준 실행과 비교해 품질이 떨어지면 회귀로 표시한다. 검색 설정, 사전, 문서 버전이 바뀌면 평가가 자동으로 다시 돈다.

## 사용자 결정 (2026-11-12)
| 질문 | 결정 |
|---|---|
| 버전 관리 | 최신만 검색하고 이전 버전은 이력으로 남긴다. 열람, 비교, 되돌리기가 된다 |
| 수명주기 | 현재, 이전, 보관 세 상태와 만료일. 만료일이 지나면 자동 보관, 보관 문서는 다시 꺼낼 수 있다 |
| 평가 경로 | 채팅과 같은 경로(컬렉션 검색 설정, 재순위, 사전 확장, 권한 필터)로 워커에서 비동기 실행. 적중률(hit@k)과 MRR을 더한다 |
| 회귀 판정 | 기준 실행 대비. 검색 설정, 사전, 문서 버전이 바뀌면 골든쿼리가 있는 컬렉션만 자동 재평가 |

## 조사로 확인한 사실
- 버전 개념이 없다. 업로드는 같은 사용자, 같은 컬렉션, 같은 해시만 중복(409)으로 막는다. 내용이 다른 같은 이름의 파일은 별개 문서가 되어 옛 내용도 검색된다. 해시 검사 코드는 단건과 zip 업로드에 복사돼 있다.
- 커넥터는 내용이 바뀌면 문서를 지우고 새로 만든다(`sync_engine._sync_file`). 이력이 없다.
- 검색 경로는 두 겹으로 거른다. Qdrant 권한 페이로드 필터(`qdrant_access_filter`, `qdrant_visibility_filter`)와 Postgres 재확인(`load_document_facts` → `visible_document_ids`)이다. 표와 요약 조회(`_accessible_documents`)는 SQL만 쓴다. MCP `read_chunk`와 `read_document`는 id로 바로 읽는다.
- `can_view`와 `document_visibility_clause`는 목록, 집계, 감사 화면도 쓴다. 여기에 수명주기를 넣으면 감사 화면에서 이전 버전이 사라진다.
- 골든쿼리 평가는 API 프로세스에서 의미 검색만으로 동기 실행하고 정밀도와 재현율만 계산한다. 기대 문서는 문서 id로 저장돼 있어 새 버전이 생기면 재현율이 0이 된다.
- 문서가 INDEXED가 되는 곳은 rag_store 블록(`storage_blocks.py` 두 곳), 워크플로 완료(`workflow.py`), 레거시 처리(`process.py` 두 곳)다.
- 재순위 모델은 `worker` 컨테이너(high 큐)에서 돈다. `generate_answer`도 high 큐다. GPU 임베딩 워커는 embed 큐다.

## 기본값 (사용자 결정을 구체화)
1. **문서 열 추가**: `lineage_id`(같은 문서의 모든 버전이 공유, 기존 문서는 자기 id), `version_number`(1부터), `lifecycle_state`(pending, current, superseded, archived), `expires_at`, `archived_at`. pending은 처리 중인 새 버전을 뜻하는 내부 상태다.
2. **새 버전 판정**: 같은 컬렉션에 같은 원본 파일명으로 내용(해시)이 다른 파일을 올리면 그 파일명의 최신 버전에 이어 붙인다. 업로드 때 `new_document=true`를 주면 별개 문서로 올린다. 해시가 같으면 지금처럼 중복(409)이다. 커넥터의 내용 변경도 새 버전이 된다.
3. **승격 시점**: 새 버전은 pending으로 시작하고, INDEXED가 되는 순간 current가 되면서 같은 계보의 current를 superseded로 바꾼다. 처리에 실패하면 이전 버전이 계속 현재 버전이다. 첫 버전은 지금처럼 바로 current다.
4. **이전 버전의 벡터는 남긴다**. 검색에서만 빠지고, 되돌리기는 재처리 없이 상태만 바꾼다.
5. **검색 조건**: "검색 가능"은 열람 가능하면서 current이고 만료일이 지나지 않은 문서다. `can_view`는 그대로 두고 `can_retrieve`, `retrievable_document_ids`, `document_retrievable_clause`를 새로 둔다. Qdrant 페이로드에 `lifecycle`(active, inactive)을 넣고 필터는 `must_not lifecycle=inactive`로 건다. 필드가 없는 기존 포인트도 걸러지지 않고 Postgres 재확인이 막는다.
6. **적용 경로**: 검색 API, 채팅(일반, 심층, 표, 요약), 요약 검색, 골든 평가, MCP 검색과 id 읽기, 답변 캐시 재확인. 채팅 기록의 인용 가림과 감사 화면은 열람 기준을 그대로 쓴다. 옛 답의 인용은 계속 보인다.
7. **목록**: 문서 목록은 기본으로 이전 버전(superseded)을 숨기고 `lifecycle` 필터(current, archived, superseded, all)를 둔다. 컬렉션 문서 수도 이전 버전을 빼고 센다.
8. **수명주기 조작**: 보관, 되돌리기(이전 버전이나 보관 문서를 현재 버전으로), 만료일 지정은 문서를 편집할 수 있는 사람(업로더, 컬렉션 편집자)이 한다. 감사 로그를 남긴다. 현재 버전을 지우면 남은 이전 버전 가운데 가장 최근의 INDEXED 버전이 현재 버전이 된다.
9. **버전 API**: 버전 목록(볼 수 있는 버전만), 두 버전 본문 비교(줄 단위 diff, 상한 있음).
10. **만료**: beat가 10분마다 만료된 current 문서를 archived로 바꾸고 Qdrant 페이로드를 맞춘다. 그 사이에도 Postgres 재확인이 만료일을 직접 보므로 만료 문서는 답에 쓰이지 않는다.
11. **커넥터**: 내용 변경은 새 버전이다. 원천에서 사라짐, 보류, 크기 초과는 지금처럼 문서를 지우되 같은 계보의 모든 버전을 지운다(fail-closed). 권한 변경도 모든 버전에 적용한다.
12. **골든 평가**: 실행은 `tasks.run_golden_eval`(high 큐, 재순위 모델이 있는 워커)로 비동기다. 평가 실행자의 권한으로 `_retrieve_chunks`를 그대로 쓴다. 자동 실행은 컬렉션 소유자의 권한으로 돈다. 일치 판정은 계보(lineage) 단위다. 질의별 정밀도, 재현율, 적중 여부, 역순위를 내고 평균을 낸다.
13. **기준과 회귀**: 컬렉션의 첫 성공 실행이 자동으로 기준이 되고, 편집자가 다른 실행을 기준으로 바꿀 수 있다. 적중률, 평균 재현율, MRR 중 하나라도 기준보다 `GOLDEN_REGRESSION_TOLERANCE`(기본 0.05) 넘게 떨어지면 회귀다. 기준에서 맞혔는데 이번에 놓친 질의도 함께 기록한다.
14. **자동 재평가**: 컬렉션 검색 설정 변경, 사전 변경(골든쿼리가 있는 모든 컬렉션), 새 버전 승격, 보관, 되돌리기, 만료, 문서 삭제 때 예약한다. 60초 뒤에 돌고, 이미 대기 중인 자동 실행이 있으면 새로 만들지 않는다.
15. **골든쿼리 수정**: 질의와 기대 문서를 고치는 PATCH를 더한다.

## Files to Change
| File | Action | Why |
|---|---|---|
| `backend/alembic/versions/d1a3c5e7f9b2_document_lifecycle.py` | CREATE | 문서 수명주기 열, 골든 실행 상태·지표·기준·회귀 열 |
| `backend/app/db/models/document.py` | UPDATE | lineage_id, version_number, lifecycle_state, expires_at, archived_at |
| `backend/app/db/models/golden_eval_run.py` | UPDATE | status, trigger, 지표, 기준, 회귀, 설정 사본, 오류 |
| `backend/app/services/access_policy.py` | UPDATE | facts에 수명주기, can_retrieve, retrievable_document_ids, 검색용 SQL 조건, Qdrant 필터 |
| `backend/app/services/access_payload.py` | UPDATE | lifecycle 페이로드 |
| `backend/app/services/document_lifecycle.py` | CREATE | 버전 판정, 승격, 보관, 되돌리기, 삭제 뒤 승격, 만료 |
| `backend/app/services/golden_eval.py` | CREATE | 지표 계산, 회귀 판정, 자동 재평가 예약 |
| `backend/app/pipeline/tasks/golden_eval.py` | CREATE | 평가 태스크, 만료 태스크 |
| `backend/app/pipeline/celery_app.py` | UPDATE | include, beat 일정 |
| `backend/app/pipeline/tasks/chat.py`, `services/search_service.py`, `api/v1/endpoints/documents/listing.py`, `mcp/tools.py` | UPDATE | 검색 가능 조건 |
| `backend/app/pipeline/blocks/storage_blocks.py`, `pipeline/tasks/workflow.py`, `pipeline/tasks/process.py` | UPDATE | INDEXED 시 승격 |
| `backend/app/api/v1/endpoints/documents/upload.py`, `models.py` | UPDATE | 새 버전 판정, 응답 |
| `backend/app/api/v1/endpoints/documents/lifecycle.py` | CREATE | 버전 목록, 비교, 보관, 되돌리기, 만료일 |
| `backend/app/api/v1/endpoints/golden_queries.py`, `schemas/golden_query.py` | UPDATE | 비동기 실행, 기준 지정, 수정 |
| `backend/app/api/v1/endpoints/collections.py`, `dictionary.py` | UPDATE | 자동 재평가 예약, 문서 수 |
| `backend/app/services/connectors/sync_engine.py` | UPDATE | 내용 변경을 새 버전으로, 삭제는 계보 전체 |
| `frontend/src/...` | UPDATE | 문서 목록 필터와 배지, 버전 이력 패널, 골든 평가 화면 |

## Tasks
1. 마이그레이션과 모델. 기존 문서는 lineage_id=id, version_number=1, current로 채운다.
2. 권한 정책에 검색 가능 조건을 넣고 모든 검색 경로에 적용한다. 감사와 기록 가림은 그대로 둔다.
3. 수명주기 서비스와 API, 업로드와 커넥터의 새 버전 처리, INDEXED 승격, 만료 태스크.
4. 골든 평가 비동기화, 계보 일치, 지표, 기준과 회귀, 자동 재평가, 골든쿼리 수정.
5. 프런트엔드: 목록 필터·배지, 버전 이력 패널, 골든 평가 화면 갱신.
6. 문서, 리뷰, 전체 테스트, 실제 서비스 점검(API 수준).

## Validation
```bash
MSYS_NO_PATHCONV=1 docker compose exec -T api sh -c "cd /app && /app/.venv/bin/pytest -q -p no:cacheprovider --no-cov -W ignore tests"
# 프런트엔드: node:22-alpine에서 tsc, eslint, vitest
```

## Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| 검색 경로 하나를 빠뜨려 이전 버전이 답에 섞임 | 중 | Postgres 재확인 함수를 하나로 모으고 경로별 회귀 테스트 |
| 파일명이 같은 다른 문서가 새 버전으로 묶임 | 중 | `new_document` 옵션, 업로드 응답에 몇 번째 버전인지 표시, 되돌리기 가능 |
| 자동 재평가가 워커를 오래 잡음 | 낮음 | 골든쿼리가 있는 컬렉션만, 60초 디바운스, 대기 중이면 생략 |
| 기존 포인트에 lifecycle 필드가 없음 | 확실 | must_not 조건이라 걸러지지 않음, Postgres 재확인이 정본 |

## Acceptance
- [x] 같은 파일명 새 내용 업로드 → v2가 INDEXED 되면 v1은 검색에서 빠지고 이력에 남는다
- [x] 되돌리기, 보관, 만료가 검색 결과에 바로 반영된다
- [x] 골든 평가가 채팅과 같은 경로로 돌고 회귀를 표시한다
- [x] 백엔드·프런트엔드 테스트 통과

## 구현 노트 (2026-11-12 완료)
- 코드 리뷰와 보안 리뷰 지적을 반영했다. 승격은 계보 잠금과 번호 순서를 따르고, DB에 계보별 현재 버전 하나와 버전 번호 유일성을 걸었다. 새 버전은 이전 버전의 등급과 ACL을 물려받고, 권한 변경은 계보 전체에 걸린다.
- 골든 평가 실행은 편집자 전용이 되었고, 결과는 조회하는 사람의 권한으로 가린다. 회귀는 두 실행에 모두 있는 질의만 비교한다. 30분 넘게 멈춘 실행은 만료 점검이 실패로 정리한다.
- 커넥터 문서는 사람이 수명주기를 바꿀 수 없고, 사람이 올린 문서는 커넥터 계보에 이어지지 않는다.
- 검증: 백엔드 1995 통과(알려진 실패 3건은 CORS 2건, presigned URL 1건), 프런트엔드 160 통과, 실제 서비스 점검 20/20.
- 남은 제약은 아키텍처 문서 §14 제약 56~64에 적었다. 화면 점검은 전체 마일스톤이 끝난 뒤 한 번에 한다.
