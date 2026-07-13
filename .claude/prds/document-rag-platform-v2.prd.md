# 문서 RAG 플랫폼 고도화 (Project_2 / v2)

## Problem
RAG 구축 담당자와 AI 서비스 개발 담당자는 Project_1(1차 버전)에서 이미 하이브리드 검색(Vector+BM25), OCR, 사전 정규화 등 핵심 기능을 구현했지만, 이를 확인·설정·활용할 수 있는 화면이 부족해 실제로 100% 활용하지 못하고 있다. 반복적인 문서 처리 흐름을 워크플로우로 구성할 방법이 없고, 구축된 RAG 데이터의 상태·버전·품질을 가시화하고 검증할 관리 체계도 미흡하다. 이 상태로는 경쟁이 치열한 문서 RAG 시장에서 영업/수익화가 가능한 완성도의 제품이라 보기 어렵다.

## Evidence
- Assumption — needs validation via 외부 고객/잠재 고객 대상 데모 및 정성 피드백 수집.
- 담당자 본인의 직접 관찰(내부 관찰 기반, 외부 정량 검증 없음): "기능은 있는데 사용자가 확인·설정을 못 함", "사용자가 받는 정보가 너무 한정적", "구축된 RAG 데이터가 가시화되지 않고 활용하기 어려움".

## Users
- **Primary**: RAG 문서 구축 담당자 및 관리자, RAG 문서를 활용한 AI 서비스 개발 담당자
- **Not for**: 정형 센서 데이터 + 진단 ML/DL 기반 설비 상태진단 시나리오 사용자 — 별도 미래 트랙으로 분리 (비전 단계, 현재 고객사/데이터셋 없음)

## Hypothesis
We believe **워크플로우 에디터(신규) + 기 구축 기능 노출 UI(문서인식/검색품질) + 데이터관리·평가 체계 고도화 + UI/UX 전면 개편**을 제공하면 **RAG 구축 담당자와 AI 서비스 개발 담당자가 RAG 데이터를 더 쉽게 구축·검증·관리**할 수 있게 되어, **영업 가능한 완성도의 최종 v1(고도화 버전) 확보**로 이어질 것이다.
We'll know we're right when **데모 시연에서 실제 잠재 고객으로부터 긍정적 반응 또는 구체적인 추가 논의 요청을 얻는다**.

## Success Metrics
| Metric | Target | How measured |
|---|---|---|
| 데모 고객 반응 | 긍정적 반응 / 추가 미팅·제안 요청 발생 | 데모 시연 후 정성 피드백 수집 |
| 4대 영역 완성도 | 4개 마일스톤 전부 완료 | /plan 단계 마일스톤 완료 체크 |
| (정량 지표) | TBD — needs validation | TBD, 초기 데모 이후 정의 |

## Scope

**MVP** — 아래 4대 영역 전체를 포함한 완성 버전. 이미 레드오션인 시장 특성상, 일부만 구현된 부분 MVP는 영업에 불충분하다고 판단하여 4개 영역 전체 완료를 최소 단위로 설정.

1. 워크플로우 에디터 (신규 — 고정 블록 조합형 문서 처리 워크플로우)
2. 문서인식 개선 노출 UI (파싱 + 검색/답변 품질 — 기 구축 백엔드 기능을 사용자가 확인·설정할 수 있는 화면)
3. 데이터관리 고도화 (문서 버전 lifecycle 정식화, 골든쿼리 평가 체계)
4. UI/UX 전면 개편

**Out of scope**
- 정형 데이터 연계(센서/진동신호 등) + 진단 ML/DL 모델 기반 상태진단·알림 서비스 — 아직 비전 단계이며 고객사/데이터셋 없음. 별도 미래 트랙/PRD로 분리하되, 이번 아키텍처 설계 시 확장 포인트만 남겨둔다.
- 멀티테넌시, PPTX/XLSX 지원, 정식 cross-encoder 리랭커 — Project_2 설계 문서엔 포함되어 있으나 이번 라운드 포함 여부는 보류. `/plan` 단계에서 마일스톤별로 확정 필요.

## Delivery Milestones
<!-- Business outcomes, not engineering tasks. /plan turns each into a plan. -->
<!-- Status: pending | in-progress | complete -->

| # | Milestone | Outcome | Status | Plan |
|---|---|---|---|---|
| 1 | 저장소 분기 (Project_1 → Project_2) | Project_1(GitHub `docvec`, main 브랜치)을 git fork하여 Project_2를 독립 저장소로 확보, Project_1은 롤백/비교 기준점으로 보존 | complete | 2026-07-13: `docvec-v2` 저장소로 mirror push 완료, 기존 설계문서/PRD `docs/design/`, `.claude/prds/`로 병합 후 push 완료 |
| 2 | 문서인식 노출 UI | 사용자가 하이브리드 검색 결과 근거, OCR 신뢰도, 사전 적용 결과 등을 화면에서 확인·설정 가능 | pending | — |
| 3 | 데이터관리 고도화 | 문서 버전 lifecycle 정식화 + 골든쿼리 평가/회귀 체계 도입 | pending | — |
| 4 | 워크플로우 에디터 | 사용자가 고정 처리 블록을 조합해 문서 처리 흐름을 구성·실행 가능 | complete | `.claude/plans/workflow-editor.plan.md` — 2026-07-13: 격리된 `docvec-v2` 스택에서 브라우저 골든패스(회원가입→로그인→프로젝트/워크플로우 생성→블록 3개 연결→저장→게시→실행) 검증 완료, 실행 결과 COMPLETED |
| 5 | UI/UX 전면 개편 | 신규 디자인 시스템 기반으로 전체 화면 재설계 | pending | — |

## Open Questions
- [ ] 5개 마일스톤의 실행 순서와 의존관계 — 리스크가 큰 워크플로우 에디터(1건)를 먼저 할지 나중에 할지 (`/plan`에서 결정)
- [ ] 멀티테넌시, PPTX/XLSX, 정식 리랭커 도입 여부 및 포함 시점
- [ ] 골든쿼리 초기 세트 규모 및 작성 주체
- [ ] 데모 대상 잠재 고객사가 구체적으로 존재하는지 (Evidence 보강 필요)
- [ ] 정형데이터+진단ML 미래 트랙을 위해 이번 아키텍처에 남겨둘 확장 포인트의 구체적 형태

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 워크플로우 에디터가 기존 IA/메뉴 구조에 큰 변화를 요구해 일정 지연 | Medium | High | 독립 모듈로 격리 개발, 기존 처리 로직은 블록으로 감싸는 방식 채택 |
| 문서 버전 스키마 변경이 기존 검색/파이프라인과 충돌 | Medium | Medium | strangler-fig 방식 점진적 마이그레이션(기존 `DocumentTextRevision` 유지하며 신규 테이블 추가 후 전환) |
| 4개 영역 전체 완료가 목표라 범위가 커서 "영업 가능 시점"이 지연 | Medium | High | `/plan`에서 마일스톤별 순서·일정 명확화, 병렬 가능한 작업 식별 |
| 외부 고객 검증 없이 방향 확정 | Medium | Medium | 조기에 잠재 고객 대상 데모/피드백 루프 확보 |

---
*Status: DRAFT — requirements only. Implementation planning pending via /plan.*
