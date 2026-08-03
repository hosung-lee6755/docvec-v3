# GraphRAG 통합 설계서

> 2026-07-29 작성. Docling VLM 통합 조사(같은 날짜) 완료 후 순서대로 착수 — 사용자 지시.
> 이 문서는 **설계만** 다룬다. 구현은 별도 착수 승인 후 진행한다.

## 0. 결정 사항 (2026-07-29)

- GraphRAG는 기존 청크 기반 hybrid search(vector + BM25 + Contextual Retrieval, task #140)를
  **대체하지 않고 보강**한다 — 엔티티/관계 그래프는 별도 검색 단계로 추가되고, 실패해도
  기존 검색 경로는 그대로 동작해야 한다(그레이스풀 폴백 원칙, 이 프로젝트 전반의 기존 관례).
- 그래프 구축은 **컬렉션 단위**로 스코프한다 — `search_service.py`/`chat.py`가 이미
  `collection_id`/`accessible_collection_ids`로 검색을 스코프하는 것과 동일한 경계.
  전역 그래프(모든 컬렉션 통합)는 이번 설계에서 다루지 않는다(권한 경계가 깨짐).
- 엔티티/관계 추출은 **로컬 LLM(Qwen2.5-3B) 우선, 실패 시 등록된 BYOK 클라우드 키로 폴백**
  구조를 취한다 — 아래 §2.2의 실증된 이유 때문에 로컬 모델 단독으로는 신뢰도가 떨어질 수 있다.
- Microsoft GraphRAG 원안의 **커뮤니티 탐지 + 계층적 요약(Leiden clustering 등)은 이번
  설계 범위에서 제외**한다 — 계산 비용과 구현 복잡도 대비 이 프로젝트 문서 규모(개별 문서
  단위 업로드, 컬렉션당 수십~수백 건)에서 이득이 크지 않다. LightRAG류의 경량 엔티티-관계
  그래프 + 그래프 확장 검색만 채택한다(§2.3).

## 1. 현황 진단

### 1.1 이미 존재하는 자산 (재사용 대상)

GraphRAG를 "0에서부터" 만들 필요가 없다 — 이미 그래프의 재료가 되는 조각들이 있다.

| 자산 | 위치 | 재사용 방식 |
|---|---|---|
| 문서 레벨 키워드 | `content_blocks.py::ExtractKeywordsBlock` | 엔티티 후보의 1차 소스 — 이미 로컬 LLM 1회 호출로 문서당 키워드 목록을 뽑고 있음 |
| 청크-키워드 매칭 | `document_chunk.py::keywords` (JSON) | 문서 키워드와 청크 텍스트의 substring 매칭 결과 — 추가 LLM 호출 없이 이미 "이 청크가 어떤 키워드를 언급하는가"가 있음 |
| 구조 계층 | `structure_analyze` 블록의 `DocumentNode` 트리, `section_path`/`heading_path` | 엔티티가 "어느 섹션에서 나왔는지" 근거(provenance)로 그대로 재사용 가능 |
| Parent/Child 청크 | `document_chunk.py::parent_chunk_id`/`chunk_tier` (Phase 9) | 그래프 확장 검색 결과를 parent 청크로 승격하는 기존 패턴과 합류 가능 |
| Contextual Retrieval | `storage_blocks.py::context_header` (task #140) | 엔티티 추출 프롬프트에 문서 제목/section_path를 앵커로 주는 로직을 그대로 재사용 |
| BYOK 클라우드 키 | `process.py::_resolve_vision_credentials`(비전 전용이지만 동일 패턴), `ProjectApiKey`/`UserApiKey` | 그래프 추출도 동일한 project→user 우선순위로 키를 조회하는 헬퍼를 하나 더 만들면 됨(비전이 아닌 텍스트 생성 키라 함수는 별도 필요, 조회 로직은 동일) |

### 1.2 존재하지 않는 것 (신규 구축 대상)

- 엔티티(개체) 자체를 1급 데이터로 저장하는 테이블이 없다 — `keywords`는 문자열 배열일 뿐,
  "이 엔티티가 문서 A의 청크 3과 문서 B의 청크 7에 동시에 등장한다" 같은 **문서 간 연결**을
  표현할 방법이 없다.
- 엔티티 간 관계(예: "A 기관이 B 사업을 주관한다")를 저장/조회하는 구조가 없다.
- 검색 시점에 그래프를 순회(예: "이 엔티티와 연결된 다른 엔티티들의 청크까지 확장 조회")하는
  로직이 없다 — 현재 검색은 순수 벡터/BM25 유사도 기반이라 "직접 언급되지 않았지만 관계로
  연결된" 정보는 못 찾는다. 이게 GraphRAG가 채우려는 정확한 공백이다.

## 2. GraphRAG 개념 정리 및 이 프로젝트 적용 시 핵심 리스크

### 2.1 일반적인 GraphRAG 접근 (2024~2026 흐름)

- **Microsoft GraphRAG(2024)**: 청크마다 LLM으로 엔티티+관계를 추출 → 전체 그래프에 커뮤니티
  탐지(Leiden) 적용 → 각 커뮤니티를 계층적으로 요약 → 질의 시 관련 커뮤니티 요약을 활용.
  정확도는 높지만 사전 인덱싱 비용(LLM 호출 횟수)이 매우 크다.
- **LightRAG(2024~2025)**: 커뮤니티 탐지 없이 엔티티-관계 그래프만 구축하고, 질의 시
  "저수준(구체 엔티티)"과 "고수준(주제/관계)" 두 단계로 그래프를 확장 조회. 인덱싱 비용이
  Microsoft GraphRAG보다 훨씬 낮다.
- **HippoRAG류(연상 기억 방식)**: 엔티티 그래프에 Personalized PageRank를 적용해 질의와
  관련된 엔티티를 그래프 확산으로 찾음 — 다단계 추론(multi-hop) 질의에 강점.
- 2026년 현재도 공통점은 동일: **(1) 청크별 엔티티/관계 추출(LLM) → (2) 그래프 저장 →
  (3) 질의 시 그래프 확장 → (4) 확장된 컨텍스트를 LLM에 제공**. 차이는 (1)의 추출 정교함과
  (3)의 확장 알고리즘 복잡도.

### 2.2 이 프로젝트에서 반드시 고려해야 할 리스크 — 이번 세션에 실증된 로컬 모델 한계

**Contextual Retrieval 구현(task #140) 중 직접 확인한 사실**: 로컬 LLM(Qwen2.5-3B-Instruct)에게
"청크 여러 개를 한 번에 나열해서 설명해 달라"는 배치 프롬프트를 주면, 배치 크기(15개, 6개
모두 시도)와 무관하게 **첫 항목만 길게 답하고 나머지는 무시**하는 패턴이 재현됐다. 이는
토큰 예산이나 프롬프트 표현 문제가 아니라 이 모델 크기(3B)의 구조화된 다중 항목 출력 능력
자체의 한계로 판단했고, 해결책은 "한 번에 하나씩만 요청"하는 단일 항목 패턴으로 전환하는
것이었다(`storage_blocks.py::_llm_chunk_contexts` 참고).

**Microsoft GraphRAG의 표준 엔티티 추출 프롬프트는 정확히 이 실패 패턴을 유발하는 형태다**
— "이 텍스트에서 엔티티 N개와 관계 M개를 모두 나열하라"는 한 번의 호출로 구조화된 다중
항목(엔티티 리스트 + 관계 리스트)을 요구한다. granite-docling-258M 테스트(같은 날, Docling
VLM 조사)에서도 반복 루프/환각 실패가 재현된 바 있어, 이 프로젝트의 로컬 모델 전반이
"한 번에 여러 개를 구조화해서 뽑아내라"는 요청에 취약하다는 패턴이 이제 세 번째로
확인된 셈이다.

**→ 설계 반영**: 엔티티/관계 추출은 청크당 "엔티티 목록 1콜 + 관계 목록 1콜"처럼 **여러
콜로 쪼개더라도 각 콜은 반드시 단일 유형·단일 항목 지향 프롬프트**로 짠다(§5.2). 로컬 모델의
신뢰도가 그래프 품질에 직결되므로, 등록된 BYOK 클라우드 키(GPT-4o-mini/Claude 등, 이미
`pdf_adapter.py`의 비전 폴백과 같은 자격 증명 체계)가 있으면 **그래프 추출은 클라우드 우선**으로
두는 편이 낫다 — 그래프 데이터는 한 번 잘못 추출되면 문서 간 연결 오류로 확산되어 청크
단위 실패보다 여파가 크다.

### 2.3 채택 접근

LightRAG 스타일의 경량 엔티티-관계 그래프. 커뮤니티 탐지/계층 요약은 제외(§0). 그래프
확장은 1-hop(직접 연결된 엔티티까지만)으로 제한 — multi-hop 확산(HippoRAG의 PageRank류)은
Phase 2 이후 실사용 데이터로 필요성이 확인되면 추가.

## 3. 목표 아키텍처

### 3.1 전체 흐름

```
rag_store 완료(청크+임베딩 확정) 후
  → graph_extract 블록(신규): 청크별 엔티티/관계 추출 → document_entities/entity_relations 저장
  → 검색 시점(search_service.py / chat.py::_retrieve_chunks):
      1) 기존 hybrid search로 top-K 청크 확보 (변경 없음)
      2) 확보된 청크에 연결된 엔티티 조회 → 그 엔티티와 연결된 다른 엔티티의 청크를 1-hop 확장
      3) 확장된 청크를 기존 결과에 병합(중복 제거) — 최종 컨텍스트로 LLM에 전달
```

- `graph_extract`는 `rag_store` **이후**에 실행한다 — 임베딩 대상인 child 청크(§1.1의
  `chunk_tier`)가 이미 확정된 시점에 붙어야, 엔티티-청크 연결이 최종 청크 ID를 정확히 참조한다.
- 그래프 확장은 검색 파이프라인의 **추가 단계**이지 대체가 아니다 — 그래프 조회가 비거나
  실패해도(엔티티 미추출, DB 오류 등) 기존 hybrid 결과만으로 그대로 응답한다.

### 3.2 그래프 저장소 선택

**PostgreSQL 인접 테이블(신규 2~3개 테이블) 채택** — Neo4j 등 전용 그래프 DB는 도입하지 않는다.

이유:
- 이 프로젝트 규모(컬렉션당 문서 수십~수백 건)에서 전용 그래프 DB의 순회 성능 이점이
  크지 않고, 1-hop 확장은 평범한 SQL JOIN으로 충분히 빠르다.
- 운영 중인 스택(Postgres/Redis/Qdrant/MinIO)에 새 인프라 컴포넌트를 추가하면 배포/백업/
  장애 대응 지점이 늘어난다 — `docker-compose.yml`에 서비스 하나 더 얹는 비용 대비 이득이
  낮다고 판단.
- 컬렉션 삭제 시 `ON DELETE CASCADE`로 그래프 데이터도 함께 정리되는 이점(기존 FK 패턴과 동일).

## 4. 데이터 모델 설계 (제안 — 실제 마이그레이션 아님)

### 4.1 `document_entities` (신규)

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | UUID PK | |
| `collection_id` | UUID FK → collections | 그래프 스코프(§0) |
| `canonical_name` | Text | 정규화된 엔티티 이름(동일 엔티티 중복 방지용 — 최소 공백 정리/대소문자만, 임베딩 기반 별칭 통합은 Phase 2) |
| `entity_type` | String(30) | 예: 기관/인물/사업/장소/제도 — 문서군에 맞는 고정 카테고리 목록(자유 태깅 아님, 로컬 모델이 자유 텍스트 타입을 안정적으로 못 뽑을 가능성 고려) |
| `description` | Text, nullable | 최초 추출 시 근거 문장 1개(전체 요약 아님 — 커뮤니티 요약 없음, §0) |
| `created_at` | DateTime | |

### 4.2 `entity_chunk_links` (신규 — N:M)

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | UUID PK | |
| `entity_id` | UUID FK → document_entities | |
| `chunk_id` | UUID FK → document_chunks (ON DELETE CASCADE) | 청크 삭제/재처리 시 자동 정리 |
| `document_id` | UUID FK → documents | 조인 없이 바로 필터링하기 위한 비정규화 컬럼(기존 `document_chunk.document_id` 패턴과 동일한 이유) |

### 4.3 `entity_relations` (신규)

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | UUID PK | |
| `collection_id` | UUID FK → collections | |
| `source_entity_id` | UUID FK → document_entities | |
| `target_entity_id` | UUID FK → document_entities | |
| `relation_type` | String(50) | 고정 목록이 아닌 짧은 서술(예: "주관한다", "소속이다") — 관계는 종류가 훨씬 다양해 엔티티 타입처럼 고정 카테고리로 강제하면 정보 손실이 큼 |
| `chunk_id` | UUID FK → document_chunks | 이 관계가 어느 청크에서 추출됐는지(근거) |
| `created_at` | DateTime | |

이 세 테이블만으로 LightRAG의 최소 요구(엔티티, 엔티티-청크 연결, 엔티티-엔티티 관계)를
충족한다. 커뮤니티/요약 테이블은 §0에 따라 만들지 않는다.

## 5. 워크플로우 통합

### 5.1 신규 블록: `graph_extract`

- 카테고리: "분석" (`extract_keywords`/`summarize`와 동일 그룹)
- 위치: `rag_store` 이후 실행되는 별도 스텝 — 기존 `step_queue_for_block`(workflow.py)에서
  `rag_store`/임베딩용 `chunk_split`만 `"embed"` 큐로 분리하는 것과 같은 이유로, `graph_extract`는
  LLM 텍스트 생성만 하고 GPU 임베딩을 쓰지 않으므로 `"normal"` 큐로 충분(로컬 모델이면
  `worker`가 이미 로컬 LLM을 처리 중인 케이스와 동일한 방식).
- Config(제안): `enable_graph_extract: bool = False`(옵트인, Contextual Retrieval의
  `enable_llm_context`와 동일한 게이팅 원칙), `entity_types: list[str]`(문서군별 커스터마이즈),
  `prefer_cloud: bool = True`(§2.2의 클라우드 우선 권장을 명시적 스위치로).
- 캐시: 기존 `BlockExecutionCache` 패턴 그대로 재사용 — `block_version` bump 규칙도 동일하게
  적용(그래프 추출 로직 변경 시 재실행 강제).

### 5.2 추출 프롬프트 설계 원칙 (§2.2 반영)

- 청크 1개당: "엔티티 목록만 나열"(1콜) → "방금 나열한 엔티티들 사이의 관계만 나열"(1콜,
  이전 콜의 엔티티 목록을 컨텍스트로 제공) — 두 콜 모두 **한 번에 한 종류만** 요청하고,
  `content_blocks.py::_generate`/`_han_ratio` 가드를 그대로 재사용한다.
- 절대 하지 않을 것: "엔티티와 관계를 한 번에 JSON으로 뽑아라" 같은 복합 구조화 출력 요청 —
  이번 세션에 실증된 실패 패턴(§2.2)과 정확히 같은 모양이라 재현될 가능성이 높다.

### 5.3 검색 통합

- `search_service.py::perform_search`, `chat.py::_retrieve_chunks` 양쪽에 그래프 확장
  단계를 추가 — 위치는 hybrid rerank(BM25) **이후, MMR 다양성 선택 이전**이 자연스럽다
  (확장된 청크도 다양성 선택 대상에 포함되어야 중복 엔티티 청크로 결과가 쏠리지 않음).
- 그래프 확장이 꺼져 있거나(컬렉션에 `graph_extract` 미실행) 매칭되는 엔티티가 없으면
  기존 경로와 100% 동일 — Contextual Retrieval의 "키 없으면 폴백" 원칙과 동일한 안전장치.

## 6. 리스크 및 트레이드오프

| 리스크 | 완화 방안 |
|---|---|
| 로컬 LLM 추출 신뢰도(§2.2) | 클라우드 우선 옵션 제공, 단일 항목 프롬프트 원칙 강제 |
| 엔티티 중복(동일 개체가 다른 표기로 여러 행 생성) | Phase 1은 문자열 정규화만, 임베딩 기반 별칭 통합은 Phase 2 |
| 인덱싱 비용 증가(청크당 최소 2회 LLM 호출 추가) | 옵트인 config, Contextual Retrieval의 `_CONTEXT_LLM_MAX_CHUNKS` 같은 문서당 상한 적용 예정 |
| 그래프 확장이 검색 지연시간 증가 | 1-hop 제한 + `_HYBRID_CANDIDATE_MULTIPLIER`류의 확장 개수 상한 적용 |
| 잘못된 관계 추출이 답변 오염 | 관계마다 `chunk_id`(근거) 저장 필수 — UI에서 "이 관계의 근거 청크" 추적 가능하게(Phase 2 이상) |

## 7. 단계별 로드맵

- **Phase 1 (제안)**: §4 테이블 마이그레이션, `graph_extract` 블록(옵트인, 클라우드 키
  있을 때만 기본 활성), 단위 테스트. 검색 통합 없이 그래프 데이터만 우선 쌓는다.
- **Phase 2**: `search_service.py`/`chat.py`에 1-hop 그래프 확장 검색 통합, 실제 문서로
  A/B 비교(그래프 확장 켰을 때/껐을 때 답변 품질) 검증.
- **Phase 3 (필요성 확인 후)**: 엔티티 별칭 통합(임베딩 유사도 클러스터링), multi-hop 확장,
  UI에 관계 그래프 시각화 탭 추가.

이번 설계서는 Phase 1 착수 여부부터 사용자 승인을 받고 진행한다.
