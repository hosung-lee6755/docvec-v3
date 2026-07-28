# 문서 데이터 RAG 구축 절차

**최종 갱신**: 2026-07-28 — 아래 내용은 실제 구현 완료 상태를 반영함

## 0. 개요

문서 데이터 RAG는 단순히 문서를 벡터DB에 넣는 작업이 아니다.  
정확한 구축 절차는 다음과 같다.

```text
문서 수집
→ 문서 파싱/OCR
→ 정제/구조화
→ 청킹
→ 메타데이터 부여
→ 임베딩
→ 벡터DB/검색 인덱스 저장
→ 검색 Retriever 구성
→ Reranking
→ LLM 답변 생성
→ 출처/근거 표시
→ 평가/운영
```

문서 RAG의 핵심은 다음 5가지다.

1. 문서의 원본 구조를 최대한 보존한다.
2. 검색 가능한 chunk를 적절하게 만든다.
3. 문서 권한, 버전, 출처 정보를 메타데이터로 관리한다.
4. Vector Search만 쓰지 말고 Keyword/BM25 검색을 함께 쓴다.
5. 골든 쿼리로 검색 품질과 답변 품질을 지속 평가한다.

---

## 1. 문서 수집

먼저 어떤 문서를 RAG 대상으로 삼을지 정의한다.

| 항목 | 예시 | 실제 구현 |
|---|---|---|
| 문서 형식 | PDF, DOCX, HWPX, TXT, Markdown, 이미지 | **PDF, DOCX, HWP, HWPX만 구현됨** |
| 문서 유형 | 계약서, 회의록, 보고서, 매뉴얼, 정책문서, 신청서 등 | 지원 |
| 문서 출처 | 업로드, Google Drive, Notion, 사내 DB, S3 | 파일 업로드만 구현 |
| 갱신 주기 | 1회성, 매일, 문서 변경 시 | 1회성, 재처리 지원 |
| 권한 | 사용자별, 조직별, 프로젝트별 접근 제어 | Tenant/Organization/Project/Collection 단위 RBAC |

> **⚠ 실제 구현과 차이**: 설계는 PPTX, XLSX, 이미지, 외부 커넥터를 포함했으나, 실제로는 파일 업로드 (`POST /v1/documents`) API를 통해 **PDF/DOCX/HWP/HWPX만** 지원됨 (`backend/app/api/v1/endpoints/documents.py:_SUPPORTED_UPLOAD_SUFFIXES`).

이 단계에서 중요한 것은 파일만 저장하는 것이 아니라, 문서의 출처, 소유자, 버전, 권한, 업로드 시점을 함께 저장하는 것이다.

### 예시 메타데이터

```json
{
  "document_id": "doc_001",
  "filename": "contract_2026.pdf",
  "source": "user_upload",
  "owner_id": "user_123",
  "project_id": "project_a",
  "version": 1,
  "created_at": "2026-07-10T10:00:00+09:00"
}
```

---

## 2. 문서 파싱/OCR

문서 RAG에서 가장 중요한 단계 중 하나다.  
단순히 PDF를 텍스트로 긁으면 표, 제목, 페이지 번호, 각주, 헤더/푸터, 이미지 캡션이 깨질 수 있다.

권장 순서는 다음과 같다.

```text
1. Native parser 먼저 시도
2. 텍스트 레이어가 없거나 깨진 경우 OCR (Docling + EasyOCR)
3. 표/이미지는 Layout Analysis로 탐지
4. page, bbox, block_type, reading_order 정보를 보존
```

| 문서 상태 | 처리 방식 | 실제 구현 |
|---|---|---|
| 디지털 PDF | PDF text layer 추출 | Native PDF adapter (`pdf_adapter.py`) |
| 스캔 PDF | OCR | Docling adapter (`docling_adapter.py`) — EasyOCR(한국어) + Reading Order 복원 |
| 표 중심 문서 | table parser + OCR fallback | Docling table detection 내장 |
| 이미지 포함 문서 | OCR/VLM 보조 | Docling으로 처리 |
| HWPX/DOCX | 구조 기반 parser 우선 | `hwp_adapter.py`(HWP/HWPX), `docx_adapter.py`(DOCX) |
| 깨진 문서 | OCR + 품질 검수 후보 | 품질 점검 후 REVIEW_REQUIRED 상태로 전환 |

> **⚠ 실제 구현**: Docling PDF 어댑터(`backend/app/pipeline/adapters/docling_adapter.py`)가 도입되어 PDF에서 OCR, table 인식, reading order 복원을 수행. TextExtractBlock에서 config engine=="docling"일 때만 선택적으로 사용되고, 기본은 Native PDF adapter. 다른 포맷(HWPX/DOCX)은 기존 어댑터 유지.

이 단계의 산출물은 단순 text가 아니라 구조화된 block이어야 한다.

### 구조화 예시

```json
{
  "page": 3,
  "blocks": [
    {
      "block_id": "b_001",
      "type": "heading",
      "text": "제5조 대금 지급",
      "bbox": [120, 80, 460, 120]
    },
    {
      "block_id": "b_002",
      "type": "paragraph",
      "text": "계약금액은 금 일천이백만원으로 한다.",
      "bbox": [120, 140, 800, 190]
    }
  ]
}
```

---

## 3. 정제와 구조화

파싱/OCR 결과를 그대로 넣으면 검색 품질이 떨어진다.  
따라서 RAG용 문서 텍스트를 정리해야 한다.

| 작업 | 설명 |
|---|---|
| 불필요 텍스트 제거 | 반복 헤더, 푸터, 페이지 번호 제거 |
| 문단 복원 | 줄바꿈으로 깨진 문장 합치기 |
| 표 정리 | Markdown table 또는 JSON table로 변환 |
| 제목 계층 복원 | h1, h2, h3 구조 부여 |
| OCR 오류 보정 | 자주 깨지는 문자/숫자 보정 |
| 중복 제거 | 같은 문서/같은 페이지 반복 제거 |
| 단위 정규화 | 날짜, 금액, 사업자번호 등 정규화 |

### 나쁜 청크 예시

```text
계약금액은 금 일천이백만원으로 한다. 제6조 계약해지 갑은...
```

### 좋은 청크 예시

```text
문서: 용역계약서
섹션: 제5조 대금 지급
페이지: 3

계약금액은 금 일천이백만원으로 한다.
지급기한은 2026년 7월 31일까지로 한다.
```

---

## 4. 청킹 전략 설계

청킹은 문서를 검색 가능한 작은 단위로 나누는 작업이다.  
문서 RAG 품질은 청킹에서 크게 갈린다.

| 방식 | 설명 | 적합한 경우 |
|---|---|---|
| 고정 길이 청킹 | 500~1,000 tokens 단위로 자름 | 단순 텍스트 |
| Overlap 청킹 | 앞뒤 일부 문맥을 겹침 | 문맥 단절 방지 |
| 섹션 기반 청킹 | 제목/조항/챕터 기준 | 계약서, 매뉴얼, 정책문서 |
| 페이지 기반 청킹 | 페이지 단위 유지 | PDF 출처 표시 중요 |
| 표 단위 청킹 | 표 하나를 atomic unit으로 유지 | 보고서, 견적서, 세금계산서 |
| 계층형 청킹 | 문서 → 섹션 → 문단 → 표 | 복잡한 문서 |

### 권장 기본값

```text
일반 문서: 500~800 tokens
기술/정책 문서: 섹션 기준 + 800~1,200 tokens
계약서: 조항 단위
표 문서: 표 단위 보존
Overlap: 10~20%
```

문서 구조가 중요한 계약서, 정책문서, 기술문서는 고정 길이 청킹보다 섹션/조항 기반 청킹이 적합하다.

---

## 5. 메타데이터 설계

RAG에서 메타데이터는 필수다.  
검색 품질, 권한 필터링, 출처 표시, 재색인, 버전 관리에 모두 필요하다.

### 최소 메타데이터 예시

```json
{
  "chunk_id": "chunk_001",
  "document_id": "doc_001",
  "document_title": "용역계약서",
  "document_type": "contract",
  "page_start": 3,
  "page_end": 3,
  "section_title": "제5조 대금 지급",
  "chunk_type": "paragraph",
  "source": "native_parser",
  "bbox": [120, 140, 800, 240],
  "created_at": "2026-07-10T10:00:00+09:00",
  "document_version": 1,
  "access_scope": ["project_a", "legal_team"]
}
```

### 주요 필터

| 필터 | 용도 |
|---|---|
| `document_type` | 계약서만 검색 |
| `project_id` | 프로젝트별 검색 |
| `owner_id` | 사용자별 권한 |
| `page` | 출처 표시 |
| `section_title` | 문맥 강화 |
| `created_at` | 최신 문서 우선 |
| `version` | 문서 버전 관리 |
| `chunk_type` | 표/본문/제목 구분 |

---

## 6. 임베딩 생성

각 chunk를 embedding model로 벡터화한다.

| 모델 유형 | 예시 |
|---|---|
| 다국어 임베딩 | BGE-M3, multilingual-e5, Jina Embeddings |
| 한국어 특화/강한 모델 | 허깅페이스 검토 필요 |
| 상용 API | OpenAI embeddings 등 |
| 로컬 배포 | BGE, e5, Jina 계열 등 |

중요한 것은 모델 이름보다 평가셋이다.  
한국어 문서 RAG라면 반드시 골든 쿼리로 비교해야 한다.

### 비교 기준

```text
Recall@k
MRR
nDCG
정답 chunk 포함률
한국어 질의 대응
긴 문서 대응
비용
속도
로컬 배포 가능 여부
라이선스
```

---

## 7. 인덱싱: Vector + Keyword + Metadata

문서 RAG는 벡터 검색만으로 부족한 경우가 많다.  
계약번호, 사업자번호, 조항 번호, 날짜, 금액처럼 정확히 매칭해야 하는 값은 Keyword/BM25 검색이 강하다.

### 권장 구조

```text
Vector Index: 의미 검색
Keyword Index: 정확 키워드 검색
Metadata Filter: 권한/문서유형/날짜 필터
Reranker: 최종 후보 재정렬
```

### 실무 검색 흐름

```text
사용자 질문
→ 권한 필터
→ metadata filter
→ vector search top 30
→ keyword search top 30
→ merge
→ rerank top 5~10
→ LLM answer
```

---

## 8. Retriever 구성

Retriever는 사용자 질문을 받아 관련 chunk를 가져오는 역할이다.

| 방식 | 설명 |
|---|---|
| Dense retriever | embedding 기반 의미 검색 |
| Sparse retriever | BM25/키워드 기반 검색 |
| Hybrid retriever | dense + sparse 결합 |
| Metadata-filtered retriever | 권한/문서유형/날짜 필터 |
| Multi-query retriever | 질문을 여러 검색 질의로 확장 |
| Parent-child retriever | 작은 chunk로 검색 후 큰 문맥 반환 |
| Self-query retriever | 질문에서 필터 조건 자동 추출 |

### 예시

사용자 질문:

```text
2024년에 체결된 계약서 중 지급기한이 30일 이내인 계약을 찾아줘
```

Retriever가 내부적으로 구성해야 하는 검색 요청:

```json
{
  "semantic_query": "지급기한 30일 이내 계약",
  "metadata_filter": {
    "document_type": "contract",
    "contract_year": 2024
  }
}
```

---

## 9. Reranking

초기 검색 결과 top 30~100개를 가져온 뒤, reranker가 질문과 가장 관련 있는 chunk를 다시 정렬한다.

### 권장 흐름

```text
Vector/BM25 검색 top 50
→ 중복 제거
→ Cross-encoder reranker
→ top 5~10 선택
→ LLM context로 전달
```

Reranker는 비용과 latency가 추가되지만, 문서 RAG에서는 품질 개선 효과가 큰 편이다.

---

## 10. 답변 생성

LLM에 검색된 context를 넣고 답변을 생성한다.

프롬프트에는 최소한 아래 규칙이 있어야 한다.

```text
- 제공된 문서 근거만 사용한다.
- 근거가 없으면 모른다고 답한다.
- 답변에는 출처 문서명, 페이지, 섹션을 포함한다.
- 숫자/날짜/계약 조건은 원문 기준으로 답한다.
- 여러 문서가 충돌하면 충돌 사실을 명시한다.
```

### 예시 출력

```json
{
  "answer": "계약금액은 12,000,000원입니다.",
  "citations": [
    {
      "document_id": "doc_001",
      "document_title": "용역계약서",
      "page": 3,
      "section": "제5조 대금 지급",
      "text": "계약금액은 금 일천이백만원으로 한다."
    }
  ],
  "confidence": "high"
}
```

---

## 11. 출처 표시와 검증

문서 RAG에서는 답변보다 근거 표시가 더 중요하다.

| 항목 | 설명 |
|---|---|
| 문서명 | 어떤 문서에서 왔는지 |
| 페이지 | PDF 기준 페이지 |
| 섹션 | 조항/제목 |
| 원문 snippet | 답변 근거 |
| bbox | 가능하면 문서 뷰어에서 하이라이트 |
| parser source | native/OCR/LLM/human |
| 문서 버전 | 어느 버전 기준인지 |

OCR 문서라면 원문 텍스트만 보여주지 말고, 가능하면 문서 이미지 위 bbox highlight까지 연결하는 것이 좋다.

---

## 12. 골든 쿼리 평가

구축 후에는 골든 쿼리로 평가한다. 실제 구현은 `backend/app/db/models/golden_query.py` 모델 기반.

### 골든 쿼리 예시

```json
{
  "id": "GQ-001",
  "query": "이 계약서의 계약금액은 얼마야?",
  "expected_document_id": "doc_001",
  "expected_page": 3,
  "expected_section": "제5조 대금 지급",
  "answerable": true,
  "evaluation_type": "exact_match"
}
```

> **⚠ 실제 구현과 차이**: expected_answer는 선택 사항. 대신 expected_document_id와 answerable 필드로 "이 질문에 대해 어느 문서에 답이 있는가" 여부를 추적. GoldenEvalRun 모델로 평가 실행을 기록하며, 자동 메트릭 계산은 부분 구현.

### 평가 지표

| 지표 | 설명 |
|---|---|
| Recall@k | 정답 chunk가 top-k 안에 있는지 |
| MRR | 정답 chunk가 얼마나 상위에 있는지 |
| Faithfulness | 답변이 검색 근거에 충실한지 |
| Answer Correctness | 최종 답이 맞는지 |
| Citation Accuracy | 인용 출처가 맞는지 |
| Refusal Accuracy | 근거 없을 때 모른다고 하는지 |
| Latency | 응답 시간 |
| Cost/query | 질의당 비용 |

RAG 평가는 한 번만 하는 것이 아니라, 청킹 방식, 임베딩 모델, reranker, 프롬프트, LLM을 바꿀 때마다 회귀 테스트해야 한다.

---

## 13. 운영 파이프라인

문서가 수정되거나 삭제될 수 있으므로 운영 절차가 필요하다.

### 문서 업로드 시

```text
문서 업로드
→ parsing job 생성
→ chunk 생성
→ embedding job 생성
→ index upsert
→ 검색 가능 상태 변경
```

### 문서 변경 시

```text
기존 document_version 비활성화
→ 새 version 생성
→ 새 chunk/embedding 생성
→ index 교체
→ 기존 대화/답변은 과거 version 기준으로 보존
```

### 문서 삭제 시

```text
soft delete
→ 검색 대상 제외
→ audit log 보존
→ 필요 시 embedding 삭제
```

---

## 14. 추천 시스템 구성

Agentic OCR/문서 플랫폼 기준으로는 다음 구성이 적합하다.

```text
[Upload/API]
    ↓
[Document Store: S3/MinIO]
    ↓
[Parser/OCR Worker]
    ↓
[Structured Document DB: PostgreSQL]
    ↓
[Chunking Worker]
    ↓
[Embedding Worker]
    ↓
[Vector DB + BM25 Index]
    ↓
[Retriever]
    ↓
[Reranker]
    ↓
[LLM Answer Generator]
    ↓
[Citation + Review UI]
```

### 저장소 구성

| 저장소 | 역할 |
|---|---|
| Object Storage | 원본 문서, 페이지 이미지, artifact |
| PostgreSQL | 문서 메타데이터, chunk, 권한, 버전, 실행 이력 |
| Vector DB | embedding 검색 |
| Search Engine | BM25/keyword 검색 |
| Redis/Queue | parsing/embedding 비동기 작업 |
| Observability | latency, cost, 실패율, 검색 품질 |

---

## 15. MVP 구축 순서

처음부터 완성형으로 가지 말고 아래 순서로 구축하는 것이 안전하다.

### 1단계: 단순 RAG

```text
PDF 업로드
→ 텍스트 추출
→ chunk
→ embedding
→ vector search
→ LLM 답변
→ 출처 표시
```

목표: 문서 기반 질의응답이 동작한다.

### 2단계: 문서 구조 보존

```text
page, section, heading, table metadata 추가
→ citation 정확도 개선
→ 표 문서 처리
```

목표: 답변 근거를 페이지/섹션 단위로 정확히 보여준다.

### 3단계: Hybrid Search

```text
vector + BM25 + metadata filter
→ 계약번호/날짜/금액/조항 검색 개선
```

목표: 정확 키워드와 의미 검색을 모두 잡는다.

### 4단계: Reranker 도입

```text
top 50 검색
→ rerank
→ top 5 context 구성
```

목표: LLM에 들어가는 근거 품질을 올린다.

### 5단계: OCR/문서 이미지 대응

```text
native parser 우선
→ OCR fallback
→ bbox 저장
→ 문서 뷰어 하이라이트
```

목표: 스캔 문서까지 처리한다.

### 6단계: 평가/회귀 테스트

```text
골든 쿼리
→ Recall@k
→ Citation Accuracy
→ Answer Correctness
→ 변경 시 자동 평가
```

목표: 모델/프롬프트/청킹을 바꿔도 품질을 관리한다.

### 7단계: 플랫폼화

```text
문서 유형별 workflow
→ parser/OCR/reranker/model 버전 관리
→ 사용자별 권한
→ API/연동
→ 운영 대시보드
```

목표: 단순 RAG 기능이 아니라 문서 데이터 플랫폼이 된다.

---

## 16. 구축 체크리스트

### 문서 수집

- [ ] 지원 문서 형식 정의
- [ ] 문서 유형 정의
- [ ] 업로드/연동 방식 정의
- [ ] 문서 권한 모델 정의
- [ ] 문서 버전 정책 정의

### 파싱/OCR

- [ ] Native parser 우선 정책 정의
- [ ] OCR fallback 조건 정의
- [ ] 표/이미지/체크박스 처리 방식 정의
- [ ] page, bbox, block_type 저장
- [ ] OCR confidence 저장

### 청킹/메타데이터

- [ ] 청킹 단위 정의
- [ ] overlap 비율 정의
- [ ] 섹션/조항 기반 청킹 지원
- [ ] 표 단위 청킹 지원
- [ ] chunk metadata schema 정의

### 검색

- [ ] 임베딩 모델 선정
- [ ] Vector DB 선정
- [ ] Keyword/BM25 인덱스 구성
- [ ] Metadata filter 적용
- [ ] Reranker 적용 여부 결정

### 답변 생성

- [ ] RAG 프롬프트 정의
- [ ] 근거 없는 질문 refusal 정책 정의
- [ ] 출처 표시 형식 정의
- [ ] 문서 버전 표시
- [ ] 충돌 문서 처리 방식 정의

### 평가/운영

- [ ] 골든 쿼리 작성
- [ ] Recall@k 평가
- [ ] Citation Accuracy 평가
- [ ] Answer Correctness 평가
- [ ] Latency/Cost 모니터링
- [ ] 문서 변경 시 재색인 정책
- [ ] soft-delete 정책
- [ ] audit log 저장

---

## 17. 결론

문서 데이터 RAG 구축의 핵심 절차는 다음과 같다.

```text
1. 문서 수집 범위 정의
2. parser/OCR 정책 수립
3. 텍스트·표·레이아웃 구조화
4. 청킹 전략 설계
5. 메타데이터/권한/버전 설계
6. 임베딩 생성
7. Vector + Keyword hybrid index 구축
8. Retriever 구성
9. Reranker 적용
10. LLM 답변 생성
11. 출처/citation 제공
12. 골든 쿼리로 평가
13. 문서 변경/삭제/재색인 운영
```

Agentic OCR 또는 문서 플랫폼 기준으로는 단순 RAG가 아니라,  
문서 파싱/OCR, 구조화, Hybrid Search, Citation, 버전관리, 평가셋까지 포함해야 제대로 된 문서 데이터 RAG 플랫폼이 된다.
