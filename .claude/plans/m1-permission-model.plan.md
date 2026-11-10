# Plan: 권한 모델 확장 (v3 마일스톤 1)

**Source PRD**: `.claude/prds/agentic-rag-governance-v3.prd.md`
**Selected Milestone**: 1. 권한 모델 확장
**Complexity**: Large

## Summary
지금은 "컬렉션 접근 가능 여부" 하나로 모든 검색·답변·열람을 판정한다. 여기에 **사용자 그룹**, **문서 보안등급 대 사용자 열람등급(clearance)**, **문서별 허용 목록(ACL)** 을 더하고, 판정 로직을 한 곳(접근 정책 모듈)으로 모아 검색·채팅·요약검색·목록·원문 열람·골든쿼리·답변 캐시가 모두 같은 기준을 쓰게 한다. Qdrant 페이로드에 권한 필드를 넣어 **검색 단계에서 거르고**, 리랭킹·LLM 투입 전에 Postgres 기준으로 한 번 더 확인하는 이중 구조로 만든다. 모든 응답 경로를 덮는 누출 회귀 테스트의 "누출 0건"을 완료 조건으로 삼는다.

## 코드 조사에서 확인한 사실 (계획의 근거)
1. **권한 판정이 두 벌로 중복**되어 있다. API는 `app/api/v1/permissions.py:103` `accessible_collection_ids`(async), 채팅 워커는 `app/pipeline/tasks/chat.py:158` `_accessible_collection_ids`(sync)로 같은 규칙을 따로 구현했다. 확장하면 반드시 어긋난다 → 정책을 한 곳으로 모은다.
2. **답변 캐시 키에 사용자 권한이 없다.** `chat.py:17` `_answer_cache_key`는 (질의, 컬렉션, 프로젝트, 모델)만 쓴다. 권한이 문서 단위로 갈라지면 높은 등급 사용자의 답변이 낮은 등급 사용자에게 캐시로 나갈 수 있다 → 이번 확장으로 새로 생길 누출 경로, 반드시 수정.
3. **요약 인덱스는 권한 필드가 없어 후처리로 거른다** (`app/api/v1/endpoints/documents/listing.py:129`, `app/services/summary_index.py:39`). top-k를 자른 뒤 거르므로 결과가 줄고, 새 규칙이 빠지기 쉽다.
4. **페이로드만 바꾸면 재임베딩이 필요 없다.** `qdrant_service.set_payload_by_document`(`app/services/qdrant_service.py:109`)로 태그를 동기화하는 선례(`documents/metadata.py:33` `_sync_tags_to_index`)가 있다. → PRD 리스크 "전체 재색인 반복"은 **페이로드 백필 1회**로 줄어든다(벡터 재계산 없음).
5. `Document.security_level`은 이미 있고 값은 `Public | Internal | Confidential` 고정(`app/schemas/document.py:286`)이지만 **검색·열람 어디에도 쓰이지 않는다**.
6. 그룹 개념은 코드에 없다. 사용자 역할(`viewer/editor/admin`)은 시스템 권한이고 데이터 접근 권한이 아니다(현재 admin도 남의 비공개 컬렉션을 못 본다).
7. 문서 단위 열람(상세·청크·원문·다운로드 등 약 50곳)은 모두 `check_document_access`(`permissions.py:89`)를 거친다 → 이 함수 하나를 확장하면 일괄 적용된다. 반면 **목록·통계·태그 집계**(`listing.py:66,116,147`, `stats.py:61`)는 컬렉션 ID로 SQL을 직접 거르므로 따로 고쳐야 한다.

## 권한 규칙 (이번 마일스톤에서 확정할 의미론)
문서 D를 사용자 U가 볼 수 있으려면 **세 조건을 모두** 만족해야 한다(교집합).
1. **컬렉션 접근**: 기존 규칙 그대로(소유자, 프로젝트 상속, 컬렉션 멤버). 업로더 본인(`created_by`) 예외도 유지.
2. **보안등급**: `rank(D의 유효 등급) <= rank(U의 열람등급)`. 순위 Public=0 < Internal=1 < Confidential=2.
   - D의 유효 등급 = `D.security_level` → 없으면 `Collection.default_security_level` → 없으면 **Public**(기존 문서 동작 보존).
   - U의 열람등급 기본값 = **Internal**, 관리자만 변경 가능.
3. **문서 ACL**: D에 ACL 항목이 **없으면 제한 없음**. 있으면 U 본인 또는 U가 속한 그룹이 목록에 있어야 한다. 업로더 본인은 항상 포함.

관리자 역할은 데이터 접근을 우회하지 않는다(기존 원칙 유지). 판정은 Postgres가 정본, Qdrant 페이로드는 검색 단계 필터용 사본이다.

> **확인 필요(가정으로 진행)**: ① 등급 미지정 문서 = Public, ② 사용자 기본 열람등급 = Internal, ③ 관리자 우회 없음, ④ ACL은 컬렉션 권한과 교집합.

## Patterns to Mirror
| Category | Source | Pattern |
|---|---|---|
| Naming | `app/api/v1/permissions.py:48` | `check_*_access`는 실패 시 `HTTPException(403/404)`, `accessible_*_ids`는 ID 목록 반환 |
| Errors | `app/api/v1/endpoints/documents/metadata.py:33` | Postgres 저장이 정본, 인덱스 동기화 실패는 로그+조건부 502, 멱등 재시도 |
| Logging/Audit | `app/services/audit.py:10` `log_audit` | 상태 변경과 같은 커밋에 감사 행 추가, 실패해도 본 작업을 막지 않음. 액션명 `<resource>.<verb>` |
| Data access | `app/api/v1/permissions.py`, `chat.py:158` | API는 async 세션 + `select`, 워커는 sync 세션 + `db.query` |
| Models/Migration | `app/db/models/collection_member.py`, `alembic/versions/4d6f8a0c2e4b_*.py` | 복합 PK 멤버십 테이블, `UTCDateTime`, down_revision 체인(현재 head `4d6f8a0c2e4b`) |
| Tests | `tests/unit/test_api_permissions_pg.py`, `tests/unit/api_pg_helpers.py` | 실제 Postgres + SAVEPOINT 롤백, `world` 픽스처로 사용자 조합 구성, `_status_of`로 403/404 검증 |
| Frontend | `frontend/src/pages/UsersPage.tsx`, `components/document-detail/DocumentSidebar.tsx` | 페이지·탭 컴포넌트, react-query 훅, KRDS 컴포넌트 |

## Files to Change
| File | Action | Why |
|---|---|---|
| `backend/app/db/models/user_group.py` | CREATE | `UserGroup`, `UserGroupMember` |
| `backend/app/db/models/document_acl.py` | CREATE | `DocumentAclEntry`(document_id, principal_type user/group, principal_id) |
| `backend/app/db/models/user.py` | UPDATE | `clearance_level` (기본 Internal) |
| `backend/app/db/models/collection.py` | UPDATE | `default_security_level` (nullable) |
| `backend/alembic/versions/<new>_access_model.py` | CREATE | 위 테이블·컬럼 + 인덱스 |
| `backend/app/services/access_policy.py` | CREATE | 정책 단일 모듈: `AccessContext`(frozen), async/sync 빌더, 문서 판정, Qdrant·SQL 필터 생성, 캐시 지문 |
| `backend/app/api/v1/permissions.py` | UPDATE | `check_document_access`가 등급·ACL까지 판정, `accessible_collection_ids`는 정책 모듈 위임 |
| `backend/app/services/qdrant_service.py` | UPDATE | `search`가 정책 필터를 받음, 권한 필드 payload 인덱스 생성 |
| `backend/app/services/access_payload.py` | CREATE | 문서 권한 페이로드 계산·동기화(본문·요약 인덱스), 백필 함수 |
| `backend/app/pipeline/blocks/storage_blocks.py` | UPDATE | 색인 시 권한 페이로드 포함(`:492`), `block_version` 올림 |
| `backend/app/services/summary_index.py` | UPDATE | 요약 포인트에 collection_id·권한 페이로드, 검색 시 필터 |
| `backend/app/services/search_service.py` | UPDATE | 정책 컨텍스트로 검색 + Postgres 재확인 |
| `backend/app/pipeline/tasks/chat.py` | UPDATE | 중복 `_accessible_collection_ids` 제거, `_accessible_documents` 필터, **캐시 키에 권한 지문** |
| `backend/app/api/v1/endpoints/documents/listing.py` | UPDATE | 목록·태그·요약검색에 등급·ACL |
| `backend/app/api/v1/endpoints/stats.py` | UPDATE | 집계 범위에 동일 규칙 |
| `backend/app/api/v1/endpoints/golden_queries.py` | UPDATE | 평가 검색을 요청자 컨텍스트로 수행 |
| `backend/app/api/v1/endpoints/groups.py` | CREATE | 그룹 CRUD + 멤버 추가·제거(관리자) |
| `backend/app/api/v1/endpoints/documents/acl.py` | CREATE | 문서 ACL 조회·교체(editor), 변경 시 페이로드 동기화 |
| `backend/app/api/v1/endpoints/users.py` | UPDATE | 관리자의 사용자 열람등급 변경 |
| `backend/app/api/v1/endpoints/documents/metadata.py` | UPDATE | `security_level` 변경 시 페이로드 동기화 |
| `backend/app/api/v1/endpoints/collections.py` | UPDATE | `default_security_level` 설정·변경 시 소속 문서 페이로드 동기화 |
| `backend/app/api/v1/router.py` | UPDATE | 신규 라우터 등록 |
| `backend/app/schemas/access.py` | CREATE | 그룹·ACL·열람등급 요청/응답 스키마 |
| `backend/scripts/backfill_access_payload.py` | CREATE | 기존 포인트 권한 페이로드 백필(멱등, 재임베딩 없음) |
| `backend/tests/unit/test_access_policy.py` | CREATE | 정책 순수 로직 |
| `backend/tests/unit/test_access_policy_pg.py` | CREATE | 실제 Postgres로 컨텍스트 빌더·SQL 필터 |
| `backend/tests/unit/test_access_leak_matrix.py` | CREATE | **누출 회귀 매트릭스**(Task 9) |
| `backend/tests/unit/test_api_groups.py`, `test_api_document_acl.py` | CREATE | 신규 API |
| `frontend/src/pages/GroupsPage.tsx` (+ 라우트·메뉴) | CREATE | 그룹 관리 화면 |
| `frontend/src/components/document-detail/AccessPanel.tsx` | CREATE | 문서 보안등급·ACL 편집 |
| `frontend/src/pages/UsersPage.tsx` | UPDATE | 사용자 열람등급·소속 그룹 |
| `frontend/src/pages/CollectionsPage.tsx` | UPDATE | 컬렉션 기본 보안등급 |
| `docs/기술문서_시스템_아키텍처.md`, `docs/유지보수_가이드.md`, `docs/design/문서_데이터_RAG_플랫폼_고도화_설계서.md` §15 | UPDATE | 권한 모델 as-built, 백필 절차, 설계서 차이 콜아웃 |

## Tasks
### Task 1: 데이터 모델과 마이그레이션
- **Action**: 그룹·그룹멤버·문서 ACL 테이블, `users.clearance_level`(기본 Internal, 기존 행도 Internal), `collections.default_security_level`(nullable). 등급 값은 기존 `Public/Internal/Confidential`과 동일 집합. 개발 스택 Postgres에 테스트 전용 `docvec_test` DB 생성 절차 포함.
- **Mirror**: `collection_member.py` 복합 PK, 마이그레이션 체인.
- **Validate**: `alembic upgrade head` → `downgrade -1` → `upgrade head` 왕복 성공.

### Task 2: 접근 정책 모듈 (TDD, 순수 로직 먼저)
- **Action**: `AccessContext`(user_id, 접근 가능 collection_ids, clearance_rank, principals = `{"u:<id>"} ∪ {"g:<gid>"}`) 불변 데이터. 순수 함수 `can_view(ctx, doc_facts)`, `qdrant_filter(ctx, scope)`, `cache_fingerprint(ctx)`. DB 빌더는 async(API)·sync(워커) 두 개지만 규칙 계산은 공유 순수 함수 하나만 쓴다.
- **Mirror**: `permissions.py` 네이밍, 불변 데이터 원칙.
- **Validate**: `test_access_policy.py`, `test_access_policy_pg.py` 통과 + 기존 `test_api_permissions_pg.py` 전부 그대로 통과.

### Task 3: 권한 페이로드와 Qdrant 필터
- **Action**: 각 청크 포인트에 `sec_rank`(int), `acl`(제한 없음이면 `["*"]`, 있으면 `u:<id>`/`g:<id>` + 업로더) 추가. 검색 필터 = `collection_id ∈ ctx` AND `sec_rank <= ctx.rank` AND `acl ∈ ({"*"} ∪ ctx.principals)` AND NOT `disabled`. `sec_rank`·`acl`·`collection_id`·`document_id` payload 인덱스 생성. 색인 블록과 요약 인덱스가 같은 페이로드를 쓴다(요약에 collection_id 추가).
- **Mirror**: `_sync_tags_to_index`, `storage_blocks.py:492`. 블록 로직 변경이므로 `block_version` 올림.
- **Validate**: `QdrantClient(":memory:")` 로컬 모드로 등급·ACL·그룹 조합별 반환 포인트 검증.

### Task 4: 응답 경로 전부를 정책에 연결
- **Action**:
  - `check_document_access`에 등급·ACL 판정 추가(상세·청크·원문·다운로드·구조 등 일괄 적용).
  - 검색, 채팅 청크·표·요약 경로, 요약 검색(후처리 대신 Qdrant 필터), 목록·태그·통계 SQL, 골든쿼리 평가를 컨텍스트 기반으로 교체.
  - **이중 확인**: Qdrant 결과를 리랭킹·LLM에 넣기 전에 해당 문서들을 Postgres 기준으로 재확인(fail-closed).
  - **답변 캐시 키에 `cache_fingerprint` 포함**.
  - 워커의 중복 `_accessible_collection_ids` 삭제.
- **Validate**: 기존 전체 테스트 통과 + Task 9 매트릭스.

### Task 5: 권한 변경 시 동기화
- **Action**: 문서 등급 변경, ACL 교체, 컬렉션 기본 등급 변경 시 본문·요약 포인트 페이로드 갱신. 그룹 멤버십 변경은 페이로드에 그룹 ID만 있으므로 동기화 불필요(컨텍스트 쪽에서 반영). 동기화 실패 시 Postgres는 저장되고 Task 4 이중 확인이 누출을 막으며, 사용자에게는 재시도 가능한 오류를 준다.
- **Mirror**: `_sync_tags_to_index`.
- **Validate**: 동기화 실패를 모킹해도 매트릭스 누출 0건.

### Task 6: 관리 API (CRUD 일괄)
- **Action**: 그룹 목록·생성·조회·수정·삭제, 멤버 목록·추가·제거(관리자). 문서 ACL 조회·교체(문서 editor). 사용자 열람등급 변경(관리자). 컬렉션 기본 등급(컬렉션 editor). 모든 변경에 감사 로그(`group.create`, `group.member_add`, `document.acl_update`, `document.security_level_update`, `user.clearance_update` 등). 그룹 삭제 시 ACL 항목 정리.
- **Mirror**: `projects.py` 멤버 초대·제거, `log_audit`.
- **Validate**: `test_api_groups.py`, `test_api_document_acl.py` — 권한 없는 호출 403, 감사 행 생성.

### Task 7: 기존 데이터 백필
- **Action**: 모든 포인트(본문·요약)에 권한 페이로드를 계산해 넣는 멱등 스크립트. 재임베딩 없음. 진행률·실패 문서 목록 출력, `--dry-run` 지원.
- **Validate**: 개발 스택에 샘플 문서 색인 → 백필 → 페이로드 확인, 두 번 실행해도 결과 동일.

### Task 8: 화면 (최소 범위 — 전면 개편은 마일스톤 8)
- **Action**: 그룹 관리 페이지, 사용자 화면에 열람등급·소속 그룹, 문서 상세 사이드바에 보안등급·허용 목록 편집, 컬렉션 설정에 기본 보안등급.
- **Mirror**: `UsersPage.tsx`, `DocumentSidebar.tsx`, react-query 훅.
- **Validate**: `npx vitest run`, `npx tsc --noEmit`, `npx eslint src`, 개발 스택에서 등급이 다른 두 계정 시나리오를 브라우저로 확인.

### Task 9: 누출 회귀 매트릭스 (완료 조건)
- **Action**: 사용자 5종(Public·Internal·Confidential 열람자, 그룹 A 소속, 무소속) × 문서 6종(등급 3종, ACL 사용자 지정, ACL 그룹 지정, 컬렉션 기본 등급 상속). 각 사용자에 대해 **모든 응답 경로**에서 볼 수 없는 문서 ID가 한 번도 나오지 않는지 검증: 검색, 채팅 근거·인용(청크/표/요약), 요약 검색, 목록·태그·통계, 상세·청크·원문·다운로드, 골든쿼리 평가, **같은 질의의 답변 캐시 재사용**. Qdrant 로컬 메모리 모드 + 실제 Postgres.
- **Mirror**: `test_api_permissions_pg.py`의 `world` 픽스처.
- **Validate**: `pytest tests/unit/test_access_leak_matrix.py` 0 failed.

### Task 10: 문서 갱신과 리뷰
- **Action**: 기술문서·유지보수 가이드(백필·장애 대응)·설계서 §15 갱신. 코드 리뷰·보안 리뷰 에이전트로 점검 후 CRITICAL/HIGH 수정.
- **Validate**: 리뷰 CRITICAL/HIGH 0건.

## Validation
```bash
# 개발 스택(project_3), 테스트 전용 DB docvec_test 준비 후
docker compose exec -T api sh -c "cd /app && /app/.venv/bin/alembic upgrade head"
docker compose exec -T api sh -c "cd /app && /app/.venv/bin/pytest"
docker compose exec -T api sh -c "cd /app && /app/.venv/bin/pytest --cov=app --cov-report=term-missing"
docker compose exec -T api sh -c "cd /app && /app/.venv/bin/pytest tests/unit/test_access_leak_matrix.py -v"
docker compose exec -T api sh -c "cd /app && /app/.venv/bin/python -m scripts.backfill_access_payload --dry-run"
cd frontend && npx vitest run && npx tsc --noEmit && npx eslint src
```
기준선: 기존 1471 passed / 커버리지 98% 이상 유지.

## Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| 응답 경로 하나를 빠뜨려 누출 | Medium | 정책 단일 모듈 + 매트릭스가 경로 전체를 강제, 새 경로는 매트릭스 추가가 머지 조건 |
| 페이로드 동기화 지연·실패로 Qdrant가 낡은 권한을 가짐 | Medium | Postgres 재확인(fail-closed), 멱등 백필 |
| principals 목록이 커져 필터 성능 저하 | Low | payload 인덱스, 그룹 단위 부여 권장, 개발 스택에서 측정 |
| 기존 문서가 갑자기 안 보이는 회귀 | Medium | 미지정 등급=Public, 기본 열람등급=Internal, 기존 권한 테스트 전부 통과 |
| 캐시 지문 추가로 답변 캐시 적중률 하락 | Medium | 같은 권한 조합끼리는 공유, 사용량 화면에서 관찰 |
| 채팅 워커(sync)와 API(async) 판정 차이 | Medium | 규칙은 순수 함수 하나, 두 빌더 결과 비교 테스트 |
| 개발 스택에 테스트 DB 없음 | High | Task 1에 `docvec_test` 생성 절차 포함(운영 DB와 분리) |

## Acceptance
- [ ] Task 1–10 완료
- [ ] 누출 회귀 매트릭스 0 failed (PRD 지표 "권한 누출 0건")
- [ ] 기존 테스트 전부 통과, 커버리지 98% 이상
- [ ] 백필 스크립트 멱등, 재임베딩 없음
- [ ] 정책 모듈 외 새 판정 로직 없음
- [ ] 문서 3종 갱신
