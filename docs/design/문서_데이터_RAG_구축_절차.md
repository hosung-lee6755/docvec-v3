# 문서 데이터 RAG 구축 절차

**최종 갱신**: 2026-11-17 (HEAD 0f38033 코드 기준으로 전 항목을 점검했다. 각 절에 근거 코드 위치를 적었다.)

## 0. 개요

문서 데이터 RAG는 단순히 문서를 벡터DB에 넣는 작업이 아니다. 전체 구축 절차는 다음과 같다.

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

### 0.1 현재 구현의 전체 흐름 (실제 구현)

현재 시스템은 위 단계를 전처리 워크플로우(`WorkflowRun`)로 실행한다. 문서를 올리면 컬렉션의 기본 전처리 워크플로우 게시 버전(없으면 시스템 표준 워크플로우의 최신 게시 버전)이 실행된다.

표준 전처리 워크플로우의 블록 순서는 다음과 같다. 이 순서는 마이그레이션 `a2c4e6f8b0d2`의 시드와 `f1a3c5e7b9d1`의 정리를 따른다.

```text
file_validate → format_detect → text_extract → structure_analyze
→ text_clean → user_dict → synonym → stopword → pii_detect
→ chunk_split → quality_check → rag_store
```

| 단계 | 블록 | 주요 결과 |
|---|---|---|
| 파일 검증, 형식 판별 | `file_validate`, `format_detect` | 지원 형식 확인, 텍스트 레이어 여부 판정 |
| 텍스트 추출 | `text_extract` | 본문, 표, 쪽 정보, 쪽 번호 지도(`page_map`) |
| 구조 분석 | `structure_analyze` | 제목 계층과 문단 구조 (`document_nodes`) |
| 정제 | `text_clean` | 유니코드, 전각, 따옴표, 공백 정리와 사용자 정제 규칙 |
| 사전 적용 | `user_dict`, `synonym`, `stopword` | 사용자 사전, 동의어 치환, 불용어 기록 (`dictionary_applications`) |
| 개인정보 탐지 | `pii_detect` | 민감정보 탐지와 마스킹, 임베딩 제외 구간 |
| 분할 | `chunk_split` | 청크 생성 (`document_chunks`) |
| 품질 검증 | `quality_check` | 품질 점수와 검토 필요 여부 판정 |
| RAG 저장 | `rag_store` | 임베딩, Qdrant 벡터와 키워드 색인 저장, 상태를 `INDEXED`로 변경 |

검토 필요 판정을 받은 실행은 `WAITING_REVIEW` 상태에서 멈추고, 검토자가 승인하면 나머지 블록을 이어서 실행한다. 검색은 채팅과 검색 화면이 같은 색인을 읽는다. 골든 평가와 버전 수명주기는 색인 위에서 동작한다.

---

## 1. 문서 수집

먼저 어떤 문서를 RAG 대상으로 삼을지 정의한다.

| 항목 | 예시 | 실제 구현 |
|---|---|---|
| 문서 형식 | PDF, DOCX, HWPX, TXT, Markdown, 이미지 | PDF, DOCX, HWP, HWPX, XLSX, PPTX, TXT, MD, HTML(HTM), 이미지(PNG, JPG, JPEG, TIFF, BMP, WEBP) |
| 문서 유형 | 계약서, 회의록, 보고서, 매뉴얼, 정책문서, 신청서 등 | 문서 유형을 강제로 나누지는 않는다. 분류(`category`)와 태그(`tags`)로 관리한다 |
| 문서 출처 | 업로드, Google Drive, Notion, 사내 DB, S3 | 직접 업로드(단건, ZIP 일괄), SMB 파일 서버 커넥터, 서버 로컬 폴더 커넥터. Google Drive, Notion, S3 커넥터는 구현하지 않았다 |
| 갱신 주기 | 1회성, 매일, 문서 변경 시 | 업로드 시점 처리, 커넥터 동기화(원천 내용이 바뀌면 새 버전), 수동 재처리 |
| 권한 | 사용자별, 조직별, 프로젝트별 접근 제어 | 컬렉션과 프로젝트 권한, 문서별 보안등급(`Public`, `Internal`, `Confidential`)과 ACL |

> **실제 구현과 차이**: 설계는 PPTX, XLSX, 이미지, 외부 커넥터를 포함했다. 지금은 형식 목록이 `backend/app/pipeline/formats.py`의 `SUPPORTED_SUFFIXES`로 정해지며, 업로드 API(`backend/app/api/v1/endpoints/documents/upload.py`)와 커넥터 동기화가 같은 목록을 쓴다. 형식을 추가할 때는 이 파일과 `adapters/__init__.py`의 `get_adapter`를 함께 고친다.

이 단계에서는 파일만 저장해서는 안 되며, 문서의 출처, 소유자, 버전, 권한, 업로드 시점을 함께 저장해야 한다.

### 1.1 업로드 경로와 중복 판정 (실제 구현)

- **단건 업로드** `POST /api/v1/documents/upload`: 파일 하나를 받는다. 같은 사용자가 같은 컬렉션에 같은 내용(SHA-256 해시가 같은 파일)을 이미 올렸다면 409 응답으로 막는다. 다시 처리하려면 기존 문서를 먼저 지워야 한다.
- **ZIP 일괄 업로드** `POST /api/v1/documents/upload-zip`: 압축 파일 안의 지원 형식만 골라 올린다. 지원하지 않는 형식은 건너뛰고 결과에 적는다. 상한은 압축 파일 1GB, 항목 200개, 항목 하나 200MB, 압축을 푼 전체 2GB다.
- **같은 파일명의 새 버전**: 같은 컬렉션에 같은 원본 파일명의 문서가 있으면 새 버전으로 잇는다. 올리는 사람이 이전 버전을 볼 수 없거나 이전 버전이 커넥터 문서이면 이어 붙이지 않고 별개 문서로 둔다. 자세한 규칙은 13.2절에 있다.

### 1.2 문서 레코드의 주요 필드 (실제 구현)

`backend/app/db/models/document.py`의 `Document` 모델이다.

| 필드 | 설명 |
|---|---|
| `id`, `original_filename`, `file_hash`, `minio_key` | 문서 식별자, 원본 파일명, 내용 해시, 원본 저장 위치 |
| `status` | 처리 상태 (아래 표 참고) |
| `collection_id`, `created_by`, `security_level` | 컬렉션, 업로더, 보안등급 |
| `lineage_id`, `version_number`, `lifecycle_state`, `expires_at`, `archived_at` | 버전 계보, 버전 번호, 수명주기 상태, 만료일, 보관 시각 |
| `parsed_text`, `page_map`, `tables`, `elements`, `images` | 추출 본문, 쪽 경계, 표, 문서 요소, 그림 |
| `title`, `category`, `tags`, `language`, `page_count` | 메타데이터 |
| `active_run_id`, `quality_status`, `pipeline_version` | 현재 실행, 품질 판정 사본, 처리 버전 |

처리 상태(`status`)는 실행 중인 블록에 따라 바뀐다. 블록과 상태의 대응은 `backend/app/pipeline/tasks/workflow.py`의 `_STATUS_FOR_BLOCK_TYPE`에 있다.

| 블록 | 문서 상태 |
|---|---|
| `file_validate`, `format_detect`, `quality_check` | `VALIDATING` |
| `text_extract` | `PARSING` |
| `structure_analyze` | `STRUCTURING` |
| `text_clean` | `REFINING` |
| `stopword`, `synonym`, `user_dict` | `NORMALIZING` |
| `pii_detect` | `MASKING` |
| `chunk_split` | `CHUNKING` |
| `rag_store` | `EMBEDDING` |
| 검토 게이트 | `WAITING_REVIEW` |
| 실행 완료 | `INDEXED` |
| 실패, 취소 | `FAILED`, `CANCELLED` |

`REVIEW_PENDING`은 예전 고정 파이프라인의 검토 상태이며, 지금의 검토 게이트는 `WAITING_REVIEW`를 쓴다.

### 1.3 예시 메타데이터 (개념 예시)

설계 단계의 메타데이터 예시이다. 실제 필드는 1.2절과 같다.

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

문서 RAG에서 가장 중요한 단계 중 하나다. 단순히 PDF를 텍스트로 긁으면 표, 제목, 페이지 번호, 각주, 헤더/푸터, 이미지 캡션이 깨질 수 있다.

권장 순서는 다음과 같다.

```text
1. Native parser 먼저 시도
2. 텍스트 레이어가 없거나 깨진 경우 OCR
3. 표/이미지는 Layout Analysis로 탐지
4. page, bbox, block_type, reading_order 정보를 보존
```

| 문서 상태 | 처리 방식 | 실제 구현 |
|---|---|---|
| 디지털 PDF (텍스트 레이어 있음) | 구조 인식 파서 | 추출 엔진 `auto`에서 Docling 어댑터(`docling_adapter.py`)가 표, 제목, 읽기 순서를 복원한다 |
| 스캔 PDF (텍스트 레이어 없음) | 전면 OCR | 기존 PDF 어댑터(`pdf_adapter.py`)가 쪽마다 Tesseract(`kor+eng`)로 OCR한다. 표와 그림은 `scan_layout.py`가 따로 찾는다 |
| 표 중심 문서 | 표 탐지 | Docling 표 탐지(텍스트 레이어 PDF), HWPX/HWP 병합 칸 표(`hwpx_structure.py`), XLSX 시트 어댑터 |
| 이미지 포함 문서 | 그림 위치 보존과 선택적 설명 | 그림은 본문의 원래 자리에 넣는다. 로컬 비전 모델(`LOCAL_VISION_MODEL`)은 기본값이 비어 있어 꺼져 있다 |
| 이미지 파일 (PNG, JPG, TIFF 등) | 스캔 PDF와 같은 길 | 쪽마다 한 장짜리 PDF로 바꿔 전면 OCR로 처리한다 (`image_adapter.py`) |
| HWPX/DOCX/HWP | 구조 기반 parser 우선 | `hwp_adapter.py`(HWP/HWPX), `hwpx_structure.py`(HWPX 표와 제목 스타일), `docx_adapter.py`(DOCX) |
| XLSX, PPTX, TXT, MD, HTML | 형식별 어댑터 | `sheet_adapter.py`, `slide_adapter.py`, `text_adapter.py` (HTML과 마크다운은 원본을 `text/plain`으로 저장해 스크립트가 실행되지 않게 한다) |
| 깨진 문서 | OCR + 품질 검수 후보 | 품질 점검에서 실패나 부분 실패가 나오면 검토 대기(`WAITING_REVIEW`)로 보낸다 |

### 2.1 추출 엔진 선택 규칙 (실제 구현)

PDF의 추출 엔진은 설정 `engine`으로 고른다(`extraction_blocks.py`의 `resolve_extract_engine`).

- `auto`(기본): 텍스트 레이어가 있으면 Docling, 없으면 전면 OCR(legacy)을 쓴다. Docling은 비트맵 영역에만 OCR을 돌리기 때문에, 윤곽선으로 된 문서나 이미지 한 장으로 된 스캔본은 거의 빈 결과가 나온다.
- `docling`: 강제로 Docling을 쓴다. 스캔본이면 안내 문구를 붙인다.
- `legacy`: 강제로 기존 PDF 어댑터를 쓴다.

DOCX, HWP, HWPX, 이미지 등 PDF가 아닌 형식은 이 설정과 관계없이 항상 기존 어댑터를 쓴다. Docling 어댑터의 OCR은 EasyOCR을 한국어(`ko`)로 명시해 쓴다.

### 2.2 구조화 예시 (개념 예시)

설계 단계의 구조화 결과이다. 실제 저장은 쪽 정보(`page_map`, `extraction_layout`)와 구조 노드 테이블(`document_nodes`)로 나누어 이루어진다.

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

파싱과 OCR 결과를 그대로 넣으면 검색 품질이 떨어진다. 따라서 RAG용 문서 텍스트를 정리해야 한다.

| 작업 | 설명 | 실제 구현 |
|---|---|---|
| 불필요 텍스트 제거 | 반복 헤더, 푸터, 페이지 번호 제거 | `text_clean`의 `remove_repeated_headers`(기본 꺼짐)가 여러 쪽에 반복되는 줄을 지운다. 쪽 번호 줄을 따로 지우는 규칙은 없고, 사용자 정제 규칙(`cleaning_rules`)으로 처리한다 |
| 문단 복원 | 줄바꿈으로 깨진 문장 합치기 | `structure_analyze`가 줄을 문단 경계(글꼴 신호, 빈 줄, 목차 등)로 다시 묶는다 |
| 표 정리 | Markdown table 또는 JSON table로 변환 | 표는 `tables`에 저장하고 청크에는 Markdown 표로 넣는다 (`table_markdown.py`) |
| 제목 계층 복원 | h1, h2, h3 구조 부여 | 글꼴 신호, 목차, 스타일(HWPX)로 제목을 판정한다. 결과는 `document_nodes`에 저장한다 |
| OCR 오류 보정 | 자주 깨지는 문자/숫자 보정 | `fix_ocr_errors`(기본 꺼짐). 줄바꿈으로 끊긴 하이픈 단어만 합치는 근사 규칙이며, 자모 단위 보정은 하지 않는다 |
| 중복 제거 | 같은 문서/같은 페이지 반복 제거 | 여러 쪽에 반복되는 줄 제거(위 반복 헤더 옵션)만 구현되어 있다. 청크 단위의 중복 제거는 별도 블록으로 구현되어 있지 않다 |
| 단위 정규화 | 날짜, 금액, 사업자번호 등 정규화 | 날짜와 금액을 표준 형식으로 바꾸는 정규화는 구현하지 않았다. 유니코드(NFC) 정규화, 전각을 반각으로, 스마트 따옴표와 대시를 일반 문자로 바꾸는 작업은 구현되어 있다 |

### 3.1 텍스트 정제 블록의 옵션 (실제 구현)

`text_clean` 블록(`normalization_blocks.py`의 `TextCleanConfig`)의 옵션과 기본값이다. 원문(`Document.parsed_text`)은 바꾸지 않고, 정제 결과를 `DocumentTextRevision`(`source="CLEAN"`)에 따로 남긴다.

| 옵션 | 기본값 | 동작 |
|---|---|---|
| `remove_control_chars` | 켜짐 | 제어 문자 제거 |
| `normalize_unicode` | 켜짐 | NFC 정규화 |
| `normalize_quotes` | 켜짐 | 스마트 따옴표와 긴 대시를 일반 문자로 |
| `normalize_width` | 켜짐 | 전각 문자와 전각 공백을 반각으로 |
| `collapse_whitespace` | 켜짐 | 여러 공백을 하나로, 빈 줄은 최대 한 줄로 |
| `remove_repeated_headers` | 꺼짐 | 여러 쪽에 반복되는 줄 제거 (쪽 정보가 있을 때만) |
| `fix_ocr_errors` | 꺼짐 | 줄바꿈으로 끊긴 하이픈 단어 결합 |
| `apply_custom_rules` | 켜짐 | 컬렉션 정제 규칙(`cleaning_rules`) 적용 |

사용자 정제 규칙은 `REGEX_REPLACE`(정규식 치환), `EXACT_REMOVE`(문자열 제거), `LINE_FILTER`(정규식에 맞는 줄 제거) 세 종류다. 규칙이 바꾼 내용은 정제 비교 화면에서 확인할 수 있다.

### 3.2 사전 적용 블록

`user_dict`, `synonym`, `stopword` 블록은 사용자 사전과 동의어, 불용어를 문서 텍스트에 적용하고 적용 위치를 기록한다. 세부 규칙, 처리 방식별 동작, 적용 취소와 문서별 끄기는 `문서_처리_사전_스키마.md`에 적었다.

### 3.3 개인정보 탐지 (실제 구현)

`pii_detect` 블록(`pii_blocks.py`, `pii_personal.py`, 블록 버전 1.1.0)은 다음 유형을 찾는다.

- 기본으로 탐지하는 유형은 주민등록번호(RRN), 전화번호(PHONE), 이메일(EMAIL), 계좌번호(ACCOUNT), 카드번호(CARD), 이름(NAME), 주소(ADDRESS), 운전면허(DRIVER_LICENSE), 여권번호(PASSPORT)다.
- 사업자등록번호(BIZNO)는 기본 대상이 아니므로, 블록 설정에서 직접 골라야 탐지한다.
- 이름은 호칭이나 라벨 같은 주변 문맥을 함께 보고 찾는다. 주민등록번호는 검증 숫자(체크섬)를 확인하고, 사업자등록번호도 검증 숫자로 걸러낸다.

처리 방식(`action`)은 `mark_only`(표시만), `mask`(기본, 마스킹), `tokenize`, `remove`, `exclude_from_embedding`이다. `exclude_from_embedding`을 쓰면 그 구간과 겹치는 청크는 임베딩하지 않고 `excluded_pii`로 표시한다. `rag_store`는 기본적으로 이 청크를 색인에서 뺀다(`exclude_pii` 기본 켜짐). 블록 설정 `require_admin_approval`을 켜면 탐지 결과를 관리자가 승인할 때까지 실행이 멈춘다.

### 3.4 좋은 청크와 나쁜 청크

```text
계약금액은 금 일천이백만원으로 한다. 제6조 계약해지 갑은...
```

위 예시는 조항 경계가 무시된 나쁜 청크다. 구조 노드(`document_nodes`)를 쓰는 청크 전략(4절)은 조항 경계를 우선한다.

```text
문서: 용역계약서
섹션: 제5조 대금 지급
페이지: 3

계약금액은 금 일천이백만원으로 한다.
지급기한은 2026년 7월 31일까지로 한다.
```

---

## 4. 청킹 전략 설계

청킹은 문서를 검색 가능한 작은 단위로 나누는 작업이다. 문서 RAG 품질은 청킹에서 크게 갈린다.

| 방식 | 설명 | 적합한 경우 |
|---|---|---|
| 고정 길이 청킹 | 일정 길이 단위로 자른다 | 단순 텍스트 |
| Overlap 청킹 | 앞뒤 일부 문맥을 겹친다 | 문맥 단절 방지 |
| 섹션 기반 청킹 | 제목/조항/챕터 기준 | 계약서, 매뉴얼, 정책문서 |
| 페이지 기반 청킹 | 페이지 단위 유지 | PDF 출처 표시 중요 |
| 표 단위 청킹 | 표 하나를 atomic unit으로 유지 | 보고서, 견적서, 세금계산서 |
| 계층형 청킹 | 문서 → 섹션 → 문단 → 표 | 복잡한 문서 |

### 4.1 권장 기본값 (설계 권장)

```text
일반 문서: 500~800 tokens
기술/정책 문서: 섹션 기준 + 800~1,200 tokens
계약서: 조항 단위
표 문서: 표 단위 보존
Overlap: 10~20%
```

문서 구조가 중요한 계약서, 정책문서, 기술문서는 고정 길이 청킹보다 섹션/조항 기반 청킹이 적합하다.

### 4.2 실제 청크 전략과 기본값 (실제 구현)

청크 크기 설정 이름은 `tokens`지만, 실제 분할은 글자 수 기준이다. `storage_blocks.py`가 값을 `max_chars`로 넘긴다. 기본값은 설정 `default_chunk_max_tokens`(512), `default_chunk_min_tokens`(50), `default_chunk_overlap_tokens`(64)다(`backend/app/core/config.py`).

컬렉션 설정 `chunk_strategy`는 `size`(기본)와 `semantic` 가운데 하나를 쓴다. 전처리 블록 `chunk_split`의 `strategy`는 다음 값을 받는다.

| 전략 | 동작 |
|---|---|
| `fixed` | 글자 수 기준으로 자른다. 문단, 문장 끝, 줄바꿈, 공백 순서로 자연스러운 자를 곳을 찾는다. 인식하지 못한 값도 이 전략으로 처리한다 |
| `sentence` | 문장 단위로 묶는다 |
| `paragraph` | 구조 노드(문단)를 따른다. 상류에 `structure_analyze`가 있어야 한다 |
| `section_aware` | 제목(섹션) 경계를 지키며 묶는다. 전략을 자동으로 고른 경우에만 짧은 구획을 이웃과 합친다 |
| `table_unit` | 표 하나를 한 청크로 유지한다 |
| `semantic` | 문장 임베딩의 유사도가 떨어지는 지점에서 자른다. 임베딩 모델을 쓴다 |

컬렉션이 `size`이고 블록에서 전략을 지정하지 않으면, 구조 노드가 본문의 80% 이상을 덮을 때만 `section_aware`로 바꾸고, 아니면 `fixed`를 쓴다.

### 4.3 부모-자식 청크 (실제 구현)

구조 기반 청킹은 청크를 `child`(검색 단위)로 만들고, 연속된 자식들을 묶은 `parent`(상위 절) 청크를 함께 저장한다(`chunk_tier`, `parent_chunk_id`). 답변을 만들 때는 컬렉션 검색 설정 `parent_context`(기본 켜짐)에 따라 근거 청크와 같은 상위 절의 앞뒤 청크를 LLM에 함께 넘긴다. 검색 순위와 인용은 바뀌지 않는다.

---

## 5. 메타데이터 설계

RAG에서 메타데이터는 필수다. 검색 품질, 권한 필터링, 출처 표시, 재색인, 버전 관리에 모두 필요하다.

### 5.1 설계 예시 (개념 예시)

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

### 5.2 실제 저장 필드 (실제 구현)

청크의 정본은 Postgres `document_chunks`다. 벡터 검색용 사본은 Qdrant 포인트의 페이로드에 들어간다. `rag_store` 블록(`storage_blocks.py`)이 만든다.

| 저장소 | 주요 필드 |
|---|---|
| `document_chunks` (Postgres) | `document_id`, `run_id`, `chunk_order`, `chunk_text`, `original_text`, `page_start`, `page_end`, `section_path`, `source_node_ids`, `prev_chunk_id`, `next_chunk_id`, `span_start`, `span_end`, `chunk_tier`(parent/child), `parent_chunk_id`, `chunk_type`, `keywords`, `embedding_model`, `version`(임베딩 차원수), `excluded_pii`, `workflow_version`, `dictionary_version`, `context_header` |
| Qdrant 포인트 (페이로드) | `document_id`, `collection_id`, `chunk_index`, `chunk_id`, `text`(원문), `index_text`(문맥을 더한 색인용 텍스트), `filename`, `page_number`, `tags`, `workflow_run_id`, 권한 사본(`sec_rank`, `acl`, `owner_id`, `collection_id`), 수명주기 사본(`lifecycle`) |

Qdrant 점의 ID는 청크 ID와 같다. 인용과 표시는 항상 `text`(원문)를 쓰고, 검색 점수 계산(BM25)은 `index_text`를 쓴다.

### 5.3 검색 필터 (실제 구현)

| 필터 | 구현 여부 | 설명 |
|---|---|---|
| 컬렉션, 프로젝트 범위 | 구현 | `collection_id`를 범위로 건다. 범위 없이 검색하면 접근 가능한 컬렉션 전체로 한다 |
| 권한 (보안등급, ACL, 소유자) | 구현 | `sec_rank`, `acl`, `owner_id`로 거른 뒤 Postgres에서 한 번 더 확인한다 |
| 수명주기 | 구현 | 현재 버전이고 만료되지 않은 문서만 근거로 쓴다 (`can_retrieve`) |
| 임의 키 일치 (`filters`) | 구현 | 요청의 `filters`는 페이로드 키와 값이 정확히 같은 것만 거른다. 예: `filename`, `tags`처럼 페이로드에 있는 키 |
| `document_type`, `project_id` | 미구현 | 페이로드에 없다. 프로젝트 범위는 컬렉션 목록으로 좁힌다 |
| `section_title`, `chunk_type` | 미구현 (검색 필터) | 페이로드에 없다. 청크 상세 화면에서 Postgres 값으로 확인한다 |
| `created_at`, `version` (검색 필터) | 미구현 | 최신 문서 우선 정렬이나 버전 필터는 없다. 버전은 수명주기 조건으로 처리한다 |
| `page` | 페이로드에 있음 | `page_number`로 저장된다. 필터 대신 인용과 표시에 쓴다 |

---

## 6. 임베딩 생성

각 청크를 임베딩 모델로 벡터화한다.

| 모델 유형 | 예시 |
|---|---|
| 다국어 임베딩 | BGE-M3, multilingual-e5, Jina Embeddings |
| 한국어 특화/강한 모델 | 허깅페이스 검토 필요 |
| 상용 API | OpenAI embeddings 등 |
| 로컬 배포 | BGE, e5, Jina 계열 등 |

### 6.1 실제 구현

- 기본 임베딩 모델은 `bge-m3`(차원 1024)다(`default_embedding_model`, `default_embedding_dimension`). 컬렉션마다 `embedding_model`을 바꿀 수 있고, 선택지는 `GET /api/v1/collections/embedding-models`가 알려 준다. 목록에는 `bge-m3`, `multilingual-e5-large`, `ko-sroberta-multitask`, `kr-sbert`, `openai`, `mock`이 있다.
- 모델을 바꾸면 기존 청크를 다시 임베딩해야 한다. 워커의 `reembed` 작업이 이 일을 맡는다.
- 청크의 `version` 컬럼에는 임베딩 차원 수를 임베딩 버전으로 기록한다. 별도 버전 태그는 없다.

모델 이름보다 평가셋이 더 중요하다.
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

위 기준 가운데 `Recall@k`(재현율), `MRR`, 정답 포함률(적중률)은 골든 평가가 계산한다(12절). `nDCG`는 계산하지 않는다.

---

## 7. 인덱싱: Vector + Keyword + Metadata

문서 RAG는 벡터 검색만으로 부족한 경우가 많다.
계약번호, 사업자번호, 조항 번호, 날짜, 금액처럼 정확히 매칭해야 하는 값은 Keyword/BM25 검색이 강하다.

### 7.1 실제 색인 구조 (실제 구현)

| 저장소 | 내용 |
|---|---|
| Qdrant 청크 컬렉션 (기본 이름 `documents`) | 청크 벡터와 페이로드. 모든 컬렉션이 이 물리 컬렉션을 함께 쓰고, 컬렉션 ID와 권한 필드로 나눈다 |
| Qdrant 키워드 컬렉션 (`documents_lex`) | 청크를 형태소 토큰으로 나눈 sparse 벡터. 청크 컬렉션 옆의 보조 컬렉션이다 (`services/lexical_index.py`) |
| Postgres | 청크 정본, 문서 레코드, 권한, 버전, 실행 기록 |

키워드 컬렉션은 `rag_store`가 청크 컬렉션에 쓸 때 함께 쓴다. 이미 색인된 문서에는 `backend/scripts/backfill_lexical_index.py`로 한 번 채워야 한다. 사전을 크게 바꾼 뒤에도 다시 실행한다.

### 7.2 권장 구조

```text
Vector Index: 의미 검색
Keyword Index: 정확 키워드 검색
Metadata Filter: 권한/문서유형/날짜 필터
Reranker: 최종 후보 재정렬
```

### 7.3 실무 검색 흐름 (설계 흐름)

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

### 7.4 채팅의 실제 검색 흐름 (실제 구현)

채팅 워커(`pipeline/tasks/chat.py`)는 기본적으로 벡터와 키워드를 결합한 하이브리드 검색을 쓰고, 근거는 5건을 쓰며, 재순위를 적용하고, 벡터 가중치는 0.6으로 둔다. 컬렉션마다 이 값을 바꿀 수 있다.

1. 질문의 의도를 분류한다. `CHUNK_SEARCH`(일반 검색), `TABLE_QUERY`(표 데이터 질의), `SUMMARY_LOOKUP`(요약 질의)로 나뉜다. 요약 질의는 저장된 문서 요약을 먼저 찾고, 결과가 없으면 청크 검색으로 대체한다. 표 질의도 청크 검색을 먼저 하고, 결과가 없을 때 표 목록에서 한 번 더 찾는다.
2. 검색어를 사전의 `SEARCH_EXPAND` 동의어로 확장한다.
3. 확장된 검색어를 임베딩하고, 벡터 후보를 근거 수의 4배만큼 가져온다. 하이브리드이면 키워드 컬렉션에서 찾은 청크를 후보에 더한다.
4. 권한과 수명주기를 Postgres에서 다시 확인해 허용되지 않은 문서를 뺀다.
5. BM25 점수를 벡터 점수와 섞는다(벡터 0.6, 키워드 0.4).
6. 교차 인코더 재순위를 쓰면 상위 후보의 두 배를 원래 질문으로 재정렬해 근거 수만큼 남긴다.

검색 화면(`POST /api/v1/search`)은 채팅과 다르다. 컬렉션 설정이 없으면 벡터 검색만 하고, 재순위는 하지 않으며, 요청 결과 수의 기본값은 10이다. 컬렉션 설정을 저장한 경우에는 그 설정의 방식을 따른다.

---

## 8. Retriever 구성

Retriever는 사용자 질문을 받아 관련 청크를 가져오는 역할이다.

| 방식 | 설명 | 실제 구현 |
|---|---|---|
| Dense retriever | embedding 기반 의미 검색 | 구현 (Qdrant 벡터 검색) |
| Sparse retriever | BM25/키워드 기반 검색 | 구현 (형태소 토큰의 키워드 컬렉션과 BM25 재정렬) |
| Hybrid retriever | dense + sparse 결합 | 구현 (채팅 기본값) |
| Metadata-filtered retriever | 권한/문서유형/날짜 필터 | 권한과 수명주기 필터는 구현. 문서 유형과 날짜 필터는 미구현 (5.3절) |
| Multi-query retriever | 질문을 여러 검색 질의로 확장 | 복합 질문은 하위 질문으로 나눠 찾는 심층 검색(deep search)으로 구현. 사용자가 켠 경우에만 동작한다 |
| Parent-child retriever | 작은 chunk로 검색 후 큰 문맥 반환 | 구현 (4.3절) |
| Self-query retriever | 질문에서 필터 조건 자동 추출 | 미구현 |

### 예시 (설계 예시)

사용자 질문:

```text
2024년에 체결된 계약서 중 지급기한이 30일 이내인 계약을 찾아줘
```

Retriever가 내부적으로 구성해야 하는 검색 요청 (설계 예시. 현재는 `metadata_filter`를 자동으로 만들지 않는다):

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

초기 검색 결과 top 30~100개를 가져온 뒤, reranker가 질문과 가장 관련 있는 청크를 다시 정렬한다.

### 9.1 권장 흐름 (설계 권장)

```text
Vector/BM25 검색 top 50
→ 중복 제거
→ Cross-encoder reranker
→ top 5~10 선택
→ LLM context로 전달
```

### 9.2 실제 구현

- 재순위 모델은 `BAAI/bge-reranker-v2-m3` 교차 인코더다(`services/reranker.py`).
- 채팅 워커에서만 돈다. 검색 화면(API 프로세스)은 재순위를 하지 않는다. API 프로세스에 모델을 올리지 않기 위해서다.
- 재순위는 사용자가 입력한 원래 질문을 기준으로 한다. 사전으로 확장한 검색어는 벡터와 키워드 검색에만 쓴다.
- 재순위 후보는 근거 수의 두 배이고, 최종 근거는 설정한 근거 수(기본 5, 허용 3~10)다.
- 재순위를 끄면 빠르지만 근거의 정확도가 떨어질 수 있다. 컬렉션 검색 설정 `rerank`로 끈다.

Reranker는 비용과 지연 시간을 늘리지만, 문서 RAG에서는 품질 개선 효과가 큰 편이다.

---

## 10. 답변 생성

LLM에 검색된 문맥(context)을 넣고 답변을 생성한다.

프롬프트에는 최소한 아래 규칙이 있어야 한다.

```text
- 제공된 문서 근거만 사용한다.
- 근거가 없으면 모른다고 답한다.
- 답변에는 출처 문서명, 페이지, 섹션을 포함한다.
- 숫자/날짜/계약 조건은 원문 기준으로 답한다.
- 여러 문서가 충돌하면 충돌 사실을 명시한다.
```

### 10.1 실제 구현

채팅 답변 프롬프트(`pipeline/tasks/chat.py`의 `_SYSTEM_PROMPT`)는 다음 규칙을 담는다.

- 제공된 발췌문만 근거로 쓴다.
- 문장이나 문단마다 근거 발췌문 번호를 `[1]`처럼 표시한다. 번호만 단독으로 내는 답은 한 번 더 요청한다.
- 발췌문에서 답을 찾을 수 없으면 그 이유를 문장으로 설명하며 모른다고 답한다.
- 한국어로만 답한다.

그 밖의 처리는 다음과 같다.

- 답변 모델은 컬렉션이나 대화에서 고른 모델이다. 로컬 모델(Ollama의 `qwen2.5` 3B 또는 7B)과 외부 모델(OpenAI, Anthropic)을 쓸 수 있다.
- 근거 문서 가운데 보안등급이 설정 `EXTERNAL_MODEL_MAX_SECURITY_LEVEL`(기본 `Internal`)보다 높은 문서가 있으면 외부 모델로는 답변을 만들지 않는다. 이때는 오류를 내고 로컬 모델을 고르라고 안내한다(`external_model_policy.py`).
- 생성한 답은 근거와 맞는지 한 번 더 검증할 수 있다(자기 검토). 검증은 설정된 클라우드 모델을 우선하지만, 등급이 높은 근거가 있으면 답변을 만든 로컬 모델로 검증해 근거가 밖으로 나가지 않게 한다.
- 답변은 SSE 스트리밍으로 전달한다(`GET /api/v1/chat/{message_id}/stream`).
- 답변 추적 기록(`answer_traces`)에 질문, 답변, 의도, 검색 근거, 사용 모델, 권한 상태를 남긴다.

---

## 11. 출처 표시와 검증

문서 RAG에서는 답변보다 근거 표시가 더 중요하다.

| 항목 | 설명 | 실제 구현 |
|---|---|---|
| 문서명 | 어떤 문서에서 왔는지 | 구현 (`filename`) |
| 페이지 | PDF 기준 페이지 | 구현 (`page_number`) |
| 섹션 | 조항/제목 | 구현 (청크의 `section_path`) |
| 원문 snippet | 답변 근거 | 구현 (원문 `text`) |
| bbox | 가능하면 문서 뷰어에서 하이라이트 | 구현. `GET /api/v1/documents/{id}/chunks/{chunk_id}/highlight`가 근거 쪽의 그림에 근거 영역을 칠해 돌려준다. 영역은 추출 엔진의 좌표(Docling)나 글자 층 검색으로 찾는다. 글자 층이 없는 스캔본은 쪽만 보여 주고 영역은 칠하지 않는다 |
| parser source | native/OCR/LLM/human | 구현 (추출 엔진과 OCR 여부는 문서 레코드와 품질 리포트에 있다) |
| 문서 버전 | 어느 버전 기준인지 | 검색은 현재 버전만 대상으로 한다. 답변 추적 기록에는 버전 번호를 따로 남기지 않는다 |

OCR 문서라면 원문 텍스트만 보여주지 말고, 가능하면 문서 이미지 위의 bbox 하이라이트까지 연결하는 것이 좋다. 현재 구현은 이 방식을 쓰되, 글자 층이 있는 문서에서만 영역이 표시된다.

---

## 12. 골든 쿼리 평가

구축 후에는 골든 쿼리로 평가한다. 실제 구현은 `backend/app/db/models/golden_query.py`(질문 정의)와 `golden_eval_run.py`(실행 기록), `services/golden_eval.py`(평가 로직)다.

### 12.1 골든 쿼리 구조 (실제 구현)

```json
{
  "id": "GQ-001",
  "query": "이 계약서의 계약금액은 얼마야?",
  "expected_document_ids": ["doc_001"],
  "expected_facts": ["12,000,000원"]
}
```

- `expected_document_ids`: 이 질문에 답이 들어 있는 문서 목록이다. 1~50개를 넣는다. 일치는 문서 계보(lineage) 단위로 본다. 기대 문서가 새 버전으로 바뀌어도 같은 문서로 인정한다.
- `expected_facts`: 답변에 반드시 들어 있어야 할 사실 조각이다. 선택 사항이다. 있으면 답변까지 생성해서 대조한다.
- 질문 개수는 컬렉션당 최대 100개다. 골든 쿼리를 바꾸면 감사 기록을 남긴다.

설계 초안의 `expected_page`, `expected_section`, `answerable`, `evaluation_type` 필드는 구현하지 않았다. 페이지와 섹션 단위 정답 판정은 하지 않으며, 문서 단위로만 판정한다.

### 12.2 평가 실행 (실제 구현)

- 평가는 워커에서 채팅과 같은 검색 경로로 돈다. 컬렉션 검색 설정, 재순위, 사전 확장, 권한 필터, 현재 버전 조건이 모두 같다. 실행자의 권한으로 검색하므로 실행자가 볼 수 없는 문서는 결과에 나오지 않는다.
- 편집 권한이 있는 사용자가 `POST /api/v1/collections/{id}/golden-eval-runs`로 실행한다. `top_k`는 1~20이며 기본값은 컬렉션 검색 설정의 근거 수다. `with_answers`를 켜면 답변을 만들어 `expected_facts`를 대조한다.
- 자동 실행(`trigger`)은 검색 설정이 바뀔 때(`search_settings`), 사전이 바뀔 때(`dictionary`), 새 버전이 승격될 때(`new_version`), 버전 수명주기가 바뀔 때(`lifecycle`), 문서가 삭제될 때(`document_deleted`) 예약된다. 자동 실행은 컬렉션 소유자의 권한으로 돈다.
- 30분 넘게 대기하거나 실행 중인 평가는 실패로 정리한다.
- 결과 조회는 조회하는 사람의 권한으로 내용을 가린다. 볼 수 없는 문서가 결과에 있으면 가린 항목으로 표시한다.

### 12.3 지표 (실제 구현)

| 지표 | 설명 | 실제 구현 |
|---|---|---|
| Recall@k (재현율) | 기대 문서 가운데 top-k 안에 들어온 비율 | 구현 (질의별 `recall`, 평균 `mean_recall`) |
| MRR | 첫 정답의 역순위(1/순위)의 평균 | 구현 (`mean_mrr`) |
| hit@k (적중률) | top-k 안에 정답이 하나라도 있는 질의의 비율 | 구현 (`mean_hit_rate`) |
| Precision | top-k 가운데 정답 문서의 비율 | 구현 (`mean_precision`) |
| Fact recall | 기대 사실 가운데 답변에 든 비율 | 구현 (`with_answers`를 켠 경우, `mean_fact_recall`) |
| Faithfulness | 답변이 검색 근거에 충실한지 | 미구현 |
| Answer Correctness | 최종 답이 맞는지 | 미구현 (사실 포함 여부로만 근사한다) |
| Citation Accuracy | 인용 출처가 맞는지 | 미구현 |
| Refusal Accuracy | 근거 없을 때 모른다고 하는지 | 미구현 |
| Latency | 응답 시간 | 미구현 (골든 평가 결과에 없다. 운영 지표는 Prometheus 지표로 본다) |
| Cost/query | 질의당 비용 | 미구현 (사용량 기록은 `llm_usage_logs`에 있다) |

### 12.4 회귀 판정 (실제 구현)

컬렉션의 기준 실행(`is_baseline`)을 정해 두면, 새 실행은 기준과 비교한다. `POST /api/v1/collections/{id}/golden-eval-runs/{run_id}/baseline`으로 끝난 실행을 기준으로 지정한다. 기준이 없으면 첫 실행이 기준이 된다.

적중률, 재현율, MRR 가운데 하나라도 기준보다 설정값(`GOLDEN_REGRESSION_TOLERANCE`, 기본 0.05)을 넘게 떨어지면 회귀로 표시한다. 기준에서 맞혔는데 이번에 놓친 질의도 목록으로 보여 준다.

RAG 평가는 한 번만 하는 것이 아니라, 청킹 방식, 임베딩 모델, reranker, 프롬프트, LLM을 바꿀 때마다 회귀 테스트해야 한다. 위의 자동 실행이 사전, 설정, 버전 변경 때 이 과정을 대신한다.

---

## 13. 운영 파이프라인

문서가 수정되거나 삭제될 수 있으므로 운영 절차가 필요하다.

### 13.1 문서 업로드 시 (실제 구현)

```text
문서 업로드 (레코드 생성, 원본 저장)
→ 전처리 워크플로우 실행 (WorkflowRun, trigger=UPLOAD)
→ 블록 순서대로 실행 (실행 결과는 블록 캐시에 저장)
→ 검토 필요 판정 시 WAITING_REVIEW에서 멈춤
→ 승인 (POST /api/v1/workflows/runs/{run_id}/resume) 또는 검토 없이 진행 옵션
→ rag_store: 임베딩, 청크 컬렉션과 키워드 컬렉션에 저장
→ INDEXED (검색 가능 상태)
```

검토 게이트는 품질 검증 블록의 `review_policy`가 정한다. 기본값(`review_on_warning`)은 경고가 있으면 검토를 요구하고, `always_review`는 모든 문서를 검토하고, `auto_pass`는 검토를 요구하지 않는다. 실패(`FAILURE`)와 부분 실패(`PARTIAL_FAILURE`)는 정책과 관계없이 항상 검토를 요구한다. 업로드 시 "검토 없이 진행"을 고르면 그 실행에 한해 `auto_pass`로 바뀌지만, 실패는 여전히 검토를 요구한다.

검토 대기와 실패는 목록 화면에서 따로 본다(`GET /api/v1/documents/review-queue`, `GET /api/v1/documents/failure-queue`). 검토 대기, 처리 실패, 동기화 실패는 알림으로도 전달한다.

### 13.2 문서 변경 시 (실제 구현): 버전 수명주기

같은 컬렉션에 같은 원본 파일명으로 다시 올리면 새 버전으로 잇는다(`document_lifecycle.py`). 버전들은 `lineage_id`를 공유한다.

```text
새 버전 업로드 (상태 pending, 보안등급과 ACL은 이전 버전에서 물려받음)
→ 처리 완료 (INDEXED)
→ 새 버전이 current, 같은 계보의 이전 current는 superseded
→ 검색과 답변은 current 버전만 사용
→ 이전 버전의 벡터는 지우지 않고 남긴다
```

- 처리에 실패하면 이전 버전이 계속 현재 버전이다.
- 권한 변경은 계보 전체에 적용한다. 되돌리기나 삭제 뒤 승격이 옛 권한을 되살리지 않도록 하기 위해서다.
- 되돌리기(`POST /api/v1/documents/{id}/restore`)는 이전 버전이나 보관 문서를 현재 버전으로 만든다. 재처리하지 않고 상태만 바꾼다. 처리가 끝난(`INDEXED`) 버전만 되돌릴 수 있다.
- 버전 비교는 `GET /api/v1/documents/{id}/versions/compare`로 한다.
- 커넥터 문서는 원천 쪽에서 버전이 정해지므로 사람이 버전과 수명주기를 바꿀 수 없다.

설계 초안의 "기존 document_version 비활성화 → 새 version → index 교체" 절차는 이 방식으로 구현했다. 차이는 이전 벡터를 지우지 않는다는 점이다. 대신 검색 단계에서 수명주기 조건으로 거른다.

### 13.3 문서 삭제 시 (실제 구현)

삭제는 소프트 삭제(soft delete)가 아니다. `DELETE /api/v1/documents/{id}`(또는 일괄 삭제 `DELETE /api/v1/documents/batch`)는 다음을 수행한다.

1. Postgres에서 문서 레코드를 지운다. 삭제 기록(audit log)은 남긴다.
2. Qdrant 청크 컬렉션과 키워드 컬렉션에서 해당 문서의 포인트를 지운다.
3. 문서 요약 색인과 원본 파일, 그림 파일을 지운다. 외부 저장소 정리는 최선 노력(best-effort) 방식이라, 실패해도 DB 삭제는 되돌리지 않는다.
4. 같은 계보의 current 버전을 지웠다면 이전 버전을 현재 버전으로 승격한다.

### 13.4 보관과 만료 (실제 구현)

- 보관(`POST /api/v1/documents/{id}/archive`): 검색과 답변에서 빠지고, 다시 꺼낼 수 있다(restore).
- 만료일(`PUT /api/v1/documents/{id}/expiry`): 만료일이 지나면 주기 작업(`expire_documents`, 약 10분 간격)이 문서를 보관 상태로 바꾼다.

### 13.5 재처리 (실제 구현)

| 방법 | API | 설명 |
|---|---|---|
| 기본 재처리 | `POST /api/v1/documents/{id}/reprocess` (옵션 없음) | 문서를 `CHUNKING`으로 되돌리고, 저장된 본문(편집본이 있으면 그 본문)으로 분할과 저장을 다시 한다. 워크플로우 전체를 다시 실행하지는 않는다 |
| 최신 게시 버전으로 재처리 | 같은 API, `use_latest_version` | 전처리 워크플로우를 새 실행으로 처음부터 다시 돌린다. 게시된 최신 버전을 쓴다 |
| 부분 재처리 | 같은 API, `start_block_type` 또는 `start_block_instance_id` | 지정한 블록부터 다시 실행한다. 그 앞 블록의 완료 결과는 복사해 쓴다 |
| 일괄 재처리 | `POST /api/v1/documents/batch-reprocess`, `POST /api/v1/collections/{id}/reprocess` | 여러 문서를 한 번에 다시 처리한다 |
| 영향 미리보기 | `GET /api/v1/documents/{id}/reprocess/impact` | 재처리로 바뀌는 범위를 미리 보여 준다 |

재처리 실행은 실행 시점의 최신 사전 버전을 새로 고정한다. 이전 실행 기록은 바뀌지 않는다.

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

### 14.1 저장소 구성

| 저장소 | 역할 |
|---|---|
| Object Storage | 원본 문서, 페이지 이미지, artifact (MinIO) |
| PostgreSQL | 문서 메타데이터, chunk, 권한, 버전, 실행 이력 |
| Vector DB | embedding 검색 (Qdrant) |
| Search Engine | BM25/keyword 검색. 구현은 Qdrant 보조 컬렉션의 sparse 벡터와 Python BM25 재정렬이다 (별도 검색 엔진 없음) |
| Redis/Queue | parsing/embedding 비동기 작업 (Celery 브로커). 작업 큐는 워커 종류별로 나뉜다 |
| Observability | latency, cost, 실패율, 검색 품질. Prometheus 지표, 감사 기록, LLM 사용량 기록 |

### 14.2 현재 구성 요소 (실제 구현)

`docker-compose.yml`의 서비스는 다음과 같다. `minio`, `postgres`, `qdrant`, `redis`, `api`, `frontend`, `caddy`, `flower`, `beat`, `worker`, `worker-embed`, `worker-extract`, 그리고 로컬 LLM 서버 `llm`(Ollama)이다.

GPU를 쓰는 작업은 큐를 나눠서 처리한다(`pipeline/tasks/workflow.py`의 `step_queue_for_block`). 임베딩과 로컬 LLM을 쓰는 블록(`rag_store`, 분석 블록)은 `embed` 큐로 가서 `worker-embed`가 맡는다. Docling과 EasyOCR을 쓰는 추출 블록은 `extract` 큐로 가서 `worker-extract`가 맡는다. 검색 질의의 임베딩은 API 프로세스에서 계산하고, 재순위 모델은 채팅 워커에서만 올린다.

---

## 15. MVP 구축 순서

처음부터 완성형을 노리지 말고 아래 순서로 구축하는 것이 안전하다.

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

### 15.1 현재 구현 단계 (실제 구현)

| 단계 | 상태 | 비고 |
|---|---|---|
| 1단계 | 구현 | |
| 2단계 | 구현 | 쪽과 섹션 정보, 표 구조를 저장하고 근거 위치를 표시한다 |
| 3단계 | 구현 | 벡터, 키워드 컬렉션, 권한 필터를 함께 쓴다. 메타데이터 필터는 권한과 수명주기 위주다 (5.3절) |
| 4단계 | 구현 | 채팅에서만 재순위한다 |
| 5단계 | 구현 | 스캔 PDF 전면 OCR, 그림 위치 보존, 인용 위치 표시(PDF) |
| 6단계 | 부분 구현 | 적중률, 재현율, MRR, 회귀 판정과 자동 실행은 구현. 자기 검토, 인용 정확도 등은 미구현 (12.3절) |
| 7단계 | 부분 구현 | 문서 버전 수명주기, 워크플로우 버전 관리, 권한, OIDC 로그인, 커넥터, 백업과 복원 스크립트. SAML 로그인은 구현하지 않았다 |

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
- [ ] soft-delete 정책 (현재 구현은 삭제를 영구 삭제로 처리한다. 13.3절)
- [ ] audit log 저장

---

## 17. 결론

문서 데이터 RAG 구축의 핵심 절차는 다음과 같다.

```text
1. 문서 수집 범위 정의
2. parser/OCR 정책 수립
3. 텍스트, 표, 레이아웃 구조화
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
