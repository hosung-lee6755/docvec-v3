# Plan: 기업 계정(LDAP/AD) 연동과 SMB 파일서버 커넥터

**Source PRD**: `.claude/prds/agentic-rag-governance-v3.prd.md`
**Selected Milestone**: 3. 기업 계정·문서 원천 연동
**Complexity**: Large

## Summary
사용자는 사내 Active Directory 계정으로 로그인하고, AD 그룹이 v3 그룹으로 동기화된다. 관리자가 등록한 SMB 공유 폴더의 파일은 주기적으로 수집되며, 파일의 NTFS 권한(DACL)이 문서 ACL로 옮겨진다. 원천에서 파일이나 권한이 바뀌면 다음 동기화 때 반영된다. 매핑할 수 없는 권한은 넓게 열지 않고 수집을 보류한다(fail-closed).

2026-11-11 사용자 결정: 계정 연동은 LDAP/AD, 첫 커넥터는 사내 파일서버(SMB)다. 두 원천이 같은 AD의 SID를 쓰므로, 파일 권한의 SID를 사용자·그룹에 바로 매핑할 수 있다.

## 확정이 필요한 기본값
마일스톤 2처럼 아래 기본값으로 진행한다. 바꿀 항목이 있으면 착수 전에 알려 주면 된다.

1. **계정 생성**: AD 사용자는 첫 로그인 때 자동으로 만든다. 역할은 viewer, 열람등급은 Internal로 시작한다. 환경변수 `LDAP_ADMIN_GROUP_DN`에 지정한 그룹의 구성원은 admin 역할을 받는다. 관리자가 화면에서 바꾼 열람등급은 다음 로그인에도 유지한다.
2. **로컬 계정 유지**: 기존 아이디/비밀번호 계정은 그대로 둔다. AD가 멈췄을 때 쓸 비상용 관리자 계정이 필요하기 때문이다. AD 사용자는 로컬 비밀번호로 로그인할 수 없다.
3. **퇴사·비활성 반영**: AD에서 비활성화되거나 사라진 사용자는 다음 디렉터리 동기화(기본 15분) 때 비활성화한다. 로그인할 때도 AD에서 다시 확인한다. AD에 연결되지 않으면 AD 사용자의 로그인은 실패한다(캐시된 비밀번호로 통과시키지 않는다).
4. **원천 권한이 기준**: 커넥터로 들어온 문서의 ACL과 AD 그룹의 구성원은 화면에서 고칠 수 없다. 다음 동기화가 덮어쓰기 때문이다. 변경은 원천(AD, 파일서버)에서 한다.
5. **넓은 권한 주체**: `Everyone`, `Authenticated Users`, `Domain Users`에게 읽기 권한이 있는 파일은 ACL 없이 등록한다. 이 경우 컬렉션 권한만 적용된다.
6. **보류 규칙(fail-closed)**: 읽기 거부(Deny) 항목이 있는 파일, 그리고 읽기 권한 주체를 하나도 매핑하지 못한 파일은 등록하지 않고 "보류"로 남긴다. v3의 ACL은 허용 목록만 표현하고, 빈 목록은 "제한 없음"을 뜻하기 때문이다. 보류된 파일은 관리 화면에서 사유와 함께 보인다.
7. **내용이 바뀐 파일**: 기존 문서를 지우고 새 문서로 다시 등록한다. 문서 버전 이력은 마일스톤 7에서 다룬다. 따라서 답변 추적 기록의 옛 문서 id는 "삭제된 문서"로 보인다.
8. **권한만 바뀐 파일**: 재색인 없이 ACL과 Qdrant 권한 사본만 갱신한다.
9. **보안등급**: 커넥터마다 "경로 접두어 → 등급" 규칙을 둘 수 있다. 규칙이 없으면 컬렉션 기본 등급을 따른다.
10. **동기화 주기**: 커넥터별로 정하며 기본값은 30분이다. 관리 화면에서 즉시 실행할 수도 있다.

## Patterns to Mirror
| Category | Source | Pattern |
|---|---|---|
| 로그인·감사 | `backend/app/api/v1/endpoints/auth.py:89` | IP·계정별 rate limit, 실패도 `auth.login_failed`로 감사, 응답 문구는 일반화 |
| 비밀값 저장 | `backend/app/core/crypto.py:31` | `encrypt_secret`/`decrypt_secret`(Fernet). `ENCRYPTION_KEY`는 바꾸지 않는다 |
| 문서 등록 | `backend/app/api/v1/endpoints/documents/upload.py:211` | 크기·확장자 검사, 파일명 정리, MinIO 업로드 실패 시 고아 원본 정리, `_start_workflow_or_mark_failed` |
| 문서 삭제 | `backend/app/api/v1/endpoints/documents/listing.py:341` | Qdrant·요약 색인·원본까지 정리 |
| 권한 사본 | `backend/app/services/access_payload.py:53` | ACL 변경 후 `sync_document_access_sync`로 Qdrant 페이로드 갱신 |
| 권한 판정 | `backend/app/services/access_policy.py` | 규칙은 이 모듈 한 곳에만 둔다 |
| 주기 작업 | `backend/app/pipeline/celery_app.py:56` | `beat_schedule`에 등록하고 작업 안에서 Redis 락으로 중복 실행을 막는다 |
| 모델 | `backend/app/db/models/user_group.py:12` | UUID PK, `UTCDateTime`, FK `SET NULL` |
| 테스트 | `backend/tests/unit/api_pg_helpers.py` | 실제 Postgres(p3-test-pg) 위에서 엔드포인트 함수를 직접 호출하고 반환값으로 단언 |

## Files to Change
| File | Action | Why |
|---|---|---|
| `backend/app/db/models/user.py` | UPDATE | `auth_source`(local/ldap), `external_id`(objectSid), `external_dn` |
| `backend/app/db/models/user_group.py` | UPDATE | `source`(local/ldap), `external_id`(objectSid), `external_dn` |
| `backend/app/db/models/source_connector.py` | CREATE | `SourceConnector`, `SourceItem`, `ConnectorRun` |
| `backend/alembic/versions/*_directory_and_connectors.py` | CREATE | 위 컬럼과 테이블, 인덱스(external_id unique) |
| `backend/app/core/config.py` | UPDATE | `LDAP_*` 설정. 비밀번호는 환경변수로만 받는다 |
| `backend/app/services/directory/ldap_client.py` | CREATE | ldap3 래퍼(서비스 계정 검색, 사용자 bind, 중첩 그룹 조회, 필터 이스케이프) |
| `backend/app/services/directory/provisioning.py` | CREATE | 사용자 자동 생성·갱신, 그룹·구성원 동기화, 비활성 반영 |
| `backend/app/api/v1/endpoints/auth.py` | UPDATE | 로그인에 LDAP 경로 추가(아이디 또는 이메일) |
| `backend/app/services/connectors/smb_client.py` | CREATE | SMB 목록·다운로드·보안 설명자 조회를 감싼 인터페이스와 구현 |
| `backend/app/services/connectors/acl_mapping.py` | CREATE | DACL을 (ACL 주체 목록 / 제한 없음 / 보류 사유) 중 하나로 바꾸는 순수 함수 |
| `backend/app/services/connectors/sync_engine.py` | CREATE | 신규, 내용 변경, 권한 변경, 삭제 처리 |
| `backend/app/services/document_ingest.py` | CREATE | 업로드 엔드포인트의 등록 로직을 서비스로 분리해 커넥터와 함께 쓴다 |
| `backend/app/pipeline/tasks/directory.py`, `connectors.py` | CREATE | beat 작업(디렉터리 동기화, 커넥터 동기화) |
| `backend/app/api/v1/endpoints/connectors.py` | CREATE | 커넥터 CRUD, 즉시 동기화, 실행 이력, 보류 목록(관리자 전용) |
| `backend/app/api/v1/endpoints/documents/acl.py`, `groups.py` | UPDATE | 원천 동기화 대상의 수동 수정 차단(409) |
| `docker-compose.dev-directory.yml` | CREATE | 개발용 Samba AD DC(LDAP와 SMB), 127.0.0.1 바인딩 |
| `frontend/src/pages/ConnectorsPage.tsx` 외 | CREATE/UPDATE | 연결 관리 화면, 사용자·그룹의 출처 표시, 로그인 입력 문구 |
| `docs/기술문서_시스템_아키텍처.md`, `docs/유지보수_가이드.md` | UPDATE | 구조, 설정 방법, 장애 대응 |

## Tasks
### Task 0: 개발용 디렉터리 환경과 라이브러리 검증(스파이크)
- **Action**: Samba AD DC 컨테이너를 띄우고 테스트 사용자, 중첩 그룹, 공유 폴더를 만든다. 공유 폴더에는 권한이 서로 다른 파일을 둔다. `ldap3`로 bind와 중첩 그룹 조회(`LDAP_MATCHING_RULE_IN_CHAIN`)를 확인한다. SMB 라이브러리로 파일 목록, 다운로드, DACL(SID와 접근 마스크) 조회를 확인한다. 후보는 `smbprotocol`이고, DACL 조회가 어려우면 `pysmb`의 `getSecurity`를 쓴다.
- **Mirror**: 서비스는 127.0.0.1에만 바인딩하고 compose profile로 분리한다.
- **Validate**: 스파이크 결과(선택한 라이브러리, 확인한 SID 예시)를 이 계획서 하단에 기록한다. 실패하면 Task 4 이후의 방식을 다시 정한다.

### Task 1: 데이터 모델과 마이그레이션
- **Action**: 사용자와 그룹에 출처와 외부 id를 추가하고 커넥터 테이블 3개를 만든다. 커넥터 비밀번호는 암호문 컬럼에만 저장한다.
- **Mirror**: `8b2d4f6a1c3e_answer_traces.py`의 생성, 인덱스, downgrade 구성.
- **Validate**: dev DB에서 upgrade, downgrade, upgrade를 반복한다. 기존 사용자는 `auth_source='local'`이 된다.

### Task 2: LDAP 로그인과 계정 자동 생성 (TDD)
- **Action**: 서비스 계정으로 사용자 DN을 찾고 사용자 자격으로 bind한다. 성공하면 사용자를 만들거나 갱신하고, 소속 그룹(중첩 포함)을 v3 그룹 구성원에 반영한다. 필터 값은 반드시 이스케이프하고, 빈 비밀번호 bind(익명 bind 성공)를 막는다. LDAPS나 StartTLS를 기본으로 요구한다.
- **Mirror**: `auth.py`의 rate limit과 감사(`auth.login`, `auth.login_failed`에 `source: ldap`).
- **Validate**: ldap3 `MOCK_SYNC`로 성공, 비밀번호 오류, 빈 비밀번호, 비활성 계정, AD 연결 불가, 필터 주입 문자열, 로컬 사용자와 이메일 충돌을 테스트한다.

### Task 3: 디렉터리 주기 동기화 (TDD)
- **Action**: beat 작업이 AD 그룹과 구성원을 동기화하고, 비활성화되거나 사라진 사용자를 비활성 처리한다. AD 그룹은 화면에서 이름과 구성원을 고칠 수 없다.
- **Mirror**: `sweep_stuck_workflow_runs` 등록 방식과 Redis 락.
- **Validate**: 구성원 추가와 제거, 그룹 삭제, 사용자 비활성을 테스트한다. AD 연결에 실패하면 아무것도 지우지 않는 것도 확인한다.

### Task 4: DACL 매핑 (TDD, 순수 함수)
- **Action**: 보안 설명자의 ACE를 읽기 권한 기준으로 해석해 세 결과 중 하나를 낸다. 결과는 주체 목록, 제한 없음(넓은 권한 주체), 보류(Deny 존재 또는 매핑 불가)다.
- **Validate**: 사용자 SID, 그룹 SID, Everyone, Authenticated Users, Domain Users, Deny ACE, 쓰기 권한만 있는 ACE, 매핑되지 않은 SID만 있는 경우, 일부만 매핑되는 경우를 표로 테스트한다. 일부만 매핑되면 매핑된 주체만 허용한다. 결과는 원천보다 좁아질 수는 있어도 넓어지지는 않는다.

### Task 5: 커넥터 동기화 엔진 (TDD)
- **Action**: 업로드 엔드포인트의 등록 로직을 `document_ingest`로 옮긴다. 엔진은 원천 목록과 `SourceItem`을 비교해 신규, 내용 변경, 권한만 변경, 원천 삭제를 처리한다. 변경 여부는 크기, 수정 시각, 보안 설명자 해시로 판단하고 내용 해시로 다시 확인한다. 실행마다 `ConnectorRun`에 건수와 오류를 남긴다.
- **Mirror**: 업로드의 크기·확장자 검사와 고아 원본 정리, 삭제 엔드포인트의 정리 순서.
- **Validate**: 가짜 SMB 클라이언트로 네 경우와 보류를 테스트한다. 한 파일의 오류가 전체 실행을 멈추지 않는지, 경로를 조작한 파일명과 크기 초과 파일을 막는지도 확인한다. 기존 업로드 테스트가 모두 통과해야 한다.

### Task 6: 커넥터 API와 수동 수정 차단
- **Action**: 관리자 전용 커넥터 CRUD, 연결 테스트, 즉시 동기화, 실행 이력, 보류 목록 API를 만든다. 비밀번호는 응답에 절대 넣지 않는다. 커넥터 문서의 ACL 수정과 AD 그룹 수정은 409로 막는다. 생성, 수정, 삭제, 동기화는 감사 로그에 남긴다.
- **Validate**: 비관리자 403, 비밀번호 비노출, 409 차단, 감사 행을 테스트한다.

### Task 7: 프런트엔드
- **Action**: 관리 메뉴에 "문서 원천 연결" 화면을 추가한다. 이 화면에서 커넥터를 등록하고 즉시 동기화하며, 최근 실행 결과와 보류된 파일의 사유를 본다. 사용자·그룹 화면에는 출처(AD, 로컬)를 표시하고 AD 출처 항목은 편집할 수 없게 한다. 로그인 입력 문구는 "아이디 또는 이메일"로 바꾼다. 문서 상세의 접근 허용 패널에는 "원천에서 관리됨" 안내를 넣는다.
- **Validate**: tsc, eslint, vitest. 화면별 테스트를 추가한다.

### Task 8: 누출 회귀, 문서, 리뷰, 커밋
- **Action**: 마일스톤 1의 누출 매트릭스에 커넥터 출처 문서를 넣는다(그룹 권한 파일, 개인 권한 파일, 보류 파일, 권한 회수 후 동기화). Samba 컨테이너로 로그인부터 수집과 검색까지 한 번 끝까지 확인한다. 아키텍처 문서와 유지보수 가이드에 설정 방법과 장애 대응(AD 장애, 보류 처리)을 쓴다. code-reviewer와 security-reviewer 검토를 반영한 뒤 커밋한다.
- **Validate**: 백엔드 전체 테스트, 프런트엔드 검사, 누출 0건.

## Validation
```bash
# 백엔드
MSYS_NO_PATHCONV=1 docker compose exec -T api sh -c "cd /app && /app/.venv/bin/pytest -q -p no:cacheprovider --no-cov tests"
# 프런트엔드
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)/frontend:/app" -v p3_fe_node_modules:/app/node_modules -w /app node:22-alpine sh -c "npx tsc --noEmit -p . && npx eslint src && npx vitest run"
# 개발용 디렉터리(통합 확인)
docker compose -f docker-compose.yml -f docker-compose.dev-directory.yml --profile dev-directory up -d
```

## Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| SMB 라이브러리로 DACL을 읽기 어렵다 | Medium | Task 0에서 먼저 확인하고, 두 라이브러리 중 되는 쪽을 쓴다 |
| 매핑 실수로 원천보다 넓게 열린다 | Medium | 매핑은 순수 함수 하나에 두고, 넓어지는 경우가 없음을 표 테스트로 고정한다. 애매하면 보류한다 |
| 아직 동기화되지 않은 그룹 SID 때문에 파일이 계속 보류된다 | Medium | 커넥터 동기화 전에 디렉터리 동기화를 먼저 돌리고, 보류 사유에 SID를 보여 준다 |
| 대량 공유 폴더의 첫 수집이 GPU 처리 대기열을 막는다 | Medium | 실행당 신규 등록 건수에 상한을 두고 나머지는 다음 실행으로 넘긴다 |
| 내용 변경 시 삭제 후 재등록이라 추적 기록의 문서 연결이 끊긴다 | High | 제약으로 문서화하고 마일스톤 7(버전 수명주기)에서 해결한다 |
| LDAP 주입, 익명 bind, 평문 LDAP | Low | 이스케이프, 빈 비밀번호 거부, TLS 기본 강제를 테스트로 고정한다 |
| Samba AD DC 컨테이너가 무겁거나 기동이 불안정하다 | Medium | 개발 전용 profile로 분리하고, 단위 테스트는 MOCK_SYNC와 가짜 SMB로 돌린다 |

## Acceptance
- [ ] AD 계정으로 로그인하면 사용자와 그룹이 생기고, 그룹 권한으로 문서가 걸러진다
- [ ] AD에서 비활성화한 사용자는 다음 동기화 뒤 로그인과 API 사용이 막힌다
- [ ] SMB 공유의 파일이 권한과 함께 등록되고, 권한 변경과 삭제가 다음 동기화에 반영된다
- [ ] 매핑할 수 없는 권한은 보류되며, 원천보다 넓게 열린 문서는 0건이다
- [ ] 누출 회귀 테스트 0건, 백엔드·프런트엔드 검사 통과
- [ ] 문서와 리뷰 반영 후 커밋

## Task 0 스파이크 결과 (2026-11-11)
개발용 AD DC는 Debian 공식 `samba` 패키지로 직접 만든 이미지(`dev/directory/`)로 띄웠다. 커뮤니티 이미지는 쓰지 않았다.

- **LDAP(ldap3 2.9.1)**: LDAPS(636)로 서비스 계정 bind, 사용자 bind 모두 된다. 중첩 그룹은 `member:1.2.840.113556.1.4.1941:=<DN>` 필터로 한 번에 나온다(alice → sales-east, sales). 비활성 계정(dave, `userAccountControl=514`)과 틀린 비밀번호는 `invalidCredentials`로 거부된다. 빈 비밀번호는 ldap3가 클라이언트에서 막지만, 우리 코드에서도 따로 막는다. 평문 389 포트의 simple bind는 서버가 `strongerAuthRequired`로 거부한다. `objectSid`는 바이너리로 오므로 문자열 SID로 바꿔 저장한다.
- **SMB(smbprotocol 1.17.0)**: `smbclient.walk`, `open_file`, `stat`으로 목록, 다운로드, 크기·수정 시각을 얻는다. 보안 설명자는 `SMB2QueryInfoRequest`(info_type 3, OWNER|GROUP|DACL)로 받는다.
- **DACL 해석**: smbprotocol의 ACL 파서는 ACL revision 3(`ACL_REVISION_DS`)을 거부한다. 그래서 MS-DTYP 자기 상대 형식을 읽는 작은 파서를 직접 둔다(`acl_mapping.py`). 실제 응답에서 Deny ACE가 맨 앞에 오고, 읽기 권한 마스크는 `0x1200a9`, 관리자는 `0x1f01ff`였다. `Domain Users`는 도메인 SID에 RID 513이 붙은 형태다.
- **설계 반영**: 수집용 서비스 계정의 SID는 모든 파일에 읽기 권한으로 들어 있으므로 매핑에서 제외한다. `Domain Users`(RID 513), `Everyone`(S-1-1-0), `Authenticated Users`(S-1-5-11)는 넓은 권한 주체로 본다.

## 구현 결과와 계획에서 바뀐 점 (2026-11-11)

- 업로드·삭제 로직을 서비스로 떼어 내지 않았다. 기존 테스트가 엔드포인트 모듈 내부를 patch하고 있어서, 동기화 엔진이 엔드포인트 함수를 지연 import로 그대로 쓴다.
- 커넥터를 지워도 커넥터용 시스템 계정은 지우지 않고 비활성으로 남긴다. 다른 행이 FK로 참조할 수 있기 때문이다.
- 기본값 4(원천이 기준)를 AD 계정의 사용 여부와 관리자 지정에도 적용했다. 화면에서 바꾸면 다음 동기화가 되돌리므로 409로 막는다. 편집자 역할과 열람등급은 v3에서 바꿀 수 있다.
- LDAP를 켜면 자가 회원가입을 막는다(보안 리뷰: 직원 이메일 선점 방지). 운영에서는 LDAP 인증서 검증을 끌 수 없다.
- 실제 Samba AD로 끝에서 끝까지 확인하다 Builtin 그룹 SID가 깨진 문자열로 들어오는 버그를 찾아 고쳤다(objectSid를 raw_attributes에서 읽음).
- 코드·보안 리뷰 반영: LDAP 페이지 검색과 대량 비활성화 거절, StartTLS 실패 확인, 문서와 원천 항목 연결을 한 커밋으로, 권한을 다시 읽지 못한 기존 문서는 내림, 하위 폴더 오류를 삼키지 않고 빈 목록이면 삭제 중단, Qdrant 갱신 실패는 파일 단위 오류, 락 하트비트와 끊긴 실행 정리, 동기화 중 커넥터 삭제 409.
- 남은 제약은 아키텍처 문서 §14의 24~34번에 정리했다.
