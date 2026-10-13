# engine_design.md
# Document Structuring Solution - Engine Design

## 1. 문서 목적

본 문서는 문서 구조 복원 엔진의 상세 설계를 정의한다.  
여기서 말하는 엔진은 단순 텍스트 추출기가 아니라, 문서 원본이 가진 구조적 단서를 최대한 복원하여 이후 정제, 정규화, 청킹, 추론 단계에서 재사용 가능한 **StructuredDocument**를 생성하는 코어 계층이다.

본 문서의 범위는 다음을 포함한다.

- RawParsedDocument의 정의와 한계
- Structure Reconstruction의 목표와 결과물
- block / section / table / figure / caption / header-footer 판정 규칙
- reading order 복원 규칙
- OCR Assist가 구조 복원에 개입하는 방식
- provenance 및 diagnostics 유지 방식

본 문서는 구현 스케줄이나 1차 목표를 다루지 않는다.  
최종적으로 도달해야 할 엔진 설계의 정답 상태를 정의한다.

---

## 2. 엔진의 책임

엔진은 다음 책임을 가진다.

1. 문서 원본으로부터 페이지 단위 / 문단 단위 / 시각 객체 단위의 원시 정보를 추출한다.
2. 원시 정보를 block, section, table, figure 등 문서 구조 객체로 승격시킨다.
3. 표, 캡션, 헤더/푸터, 페이지 번호, 본문, 제목을 구분한다.
4. 필요 시 OCR을 보조적으로 사용하되 native 정보를 우선한다.
5. 사람이 검토 가능한 review 대상 구조를 만든다.
6. 이후 refinement와 semantic normalization이 가능한 수준의 structured object를 만든다.

엔진은 다음 책임을 갖지 않는다.

- 사용자 UI 처리
- 검색 서비스 제공
- 벡터 인덱스 운영
- 대화형 질의응답
- 최종 semantic fact 확정 자체

---

## 3. 입력과 출력

### 3.1 입력
엔진의 직접 입력은 `InputDocument`와 그에 대응하는 adapter 설정이다.

입력에는 최소한 다음 정보가 포함된다.

- `document_id`
- `file_name`
- `file_type`
- `mime_type`
- `source_path`
- `file_hash`
- `ingested_at`
- `adapter_name`
- `processing_options`

### 3.2 중간 입력
구조 복원 엔진이 실제로 다루는 핵심 입력은 `RawParsedDocument`다.  
이 객체는 포맷별 native parse 결과를 담는다.

### 3.3 출력
구조 복원 엔진의 직접 출력은 `StructuredDocument`다.

이 출력은 다음 특징을 가져야 한다.

- 문서 구조 객체가 존재해야 한다.
- 각 객체는 stable id를 가져야 한다.
- provenance가 유지되어야 한다.
- refinement target으로 직접 사용 가능해야 한다.
- canonical schema 전 단계로서 충분한 정보량을 가져야 한다.

---

## 4. RawParsedDocument 정의 및 HWP/HWPX 실제 페이지 분할

`RawParsedDocument`는 포맷별 parser가 생성한 원시 추출 결과다.  
이 객체는 포맷 고유성이 남아 있어도 괜찮지만, 최소한 아래 공통 항목은 유지해야 한다.

### 4.0 HWP/HWPX 페이지 분할: 미구현 설계의 수정

**설계 문제**: HWPX의 `pageBreak` XML 속성이 실제 페이지 경계를 나타낼 것으로 가정했으나, 실제 문서에서 이 속성은 거의 항상 "0"이므로 (페이지 break 없음을 의미) 실제 페이지 번호 복원이 불가능함을 발견.

**현재 구현 (process.py `_repaginate_hwp_like`)**: HWP/HWPX 어댑터는 모든 내용을 단일 RawPage(page_number=1)로 반환 → Structure Reconstruction 이후 `_repaginate_hwp_like()` 함수가 실제 페이지를 재파악.

**동작 방식**:
1. Preview PDF 생성: LibreOffice 렌더링을 통해 각 페이지의 HTML/PDF 변환본 생성 (원문대조 탭과 동일 입력)
2. Per-page 텍스트 추출: `preview_service.pdf_pages_text_for()`로 Preview PDF의 각 페이지 텍스트 추출
3. 텍스트 매칭: 문서 순서대로 각 paragraph/table 텍스트 블록을 추출된 페이지 텍스트 안에서 검색 (monotonic cursor)
4. 테이블 특수 처리: table block의 경우 formatted text("[표 N]\n{cell|cell}") 대신 raw 셀 텍스트 연결 사용 (PDF text에는 " | " 구분자 없음)
5. 앵커 길이 최적화: 60자 단위 추출 (짧은 앵커가 HTML 리플로우 차이에 덜 취약함을 실증적으로 발견)
6. 페이지 재구성: 할당된 페이지 번호별로 새 RawPage 구성

**제한사항**: 일부 블록의 경우 PDF 텍스트와 원본이 미세하게 달라 매치 실패 시 현재 페이지에 머무르는 보수적 전략 사용 (일반적으로 7-14% 블록이 미매칭됨, 앞의 단일 페이지 설계보다 훨씬 개선).

```json
{
  "document_id": "doc_0001",
  "source": {
    "file_name": "sample.pdf",
    "file_type": "pdf",
    "source_path": "/data/input/sample.pdf"
  },
  "raw_pages": [
    {
      "page_id": "raw_page_0001",
      "page_num": 1,
      "width": 595.0,
      "height": 842.0,
      "rotation": 0,
      "raw_text_blocks": [],
      "raw_lines": [],
      "raw_spans": [],
      "raw_words": [],
      "raw_images": [],
      "raw_drawings": [],
      "raw_table_candidates": [],
      "raw_region_candidates": [],
      "diagnostics": {}
    }
  ]
}
```

### 4.1 raw 객체의 원칙
- parser는 의미를 해석하지 않는다.
- parser는 구조 확정을 시도하지 않는다.
- parser는 가능한 한 손실 없이 원시 정보를 보존한다.
- parser는 OCR 결과를 optional metadata로만 추가할 수 있다.

### 4.2 raw 객체가 포함해야 할 최소 단서
- 페이지 기하 정보
- 줄 / span / word 단위 bbox
- font size / font name / emphasis 등 스타일 단서
- image / drawing object
- table candidate
- OCR 후보 페이지 / 영역 정보
- title 후보 / page number 후보 같은 약한 힌트

---

## 5. Structure Reconstruction 개요

Structure Reconstruction은 RawParsedDocument를 받아 StructuredDocument를 생성하는 과정이다.  
이 단계의 목표는 “문서의 논리 구조를 충분히 보존한 공통 형태”를 만드는 것이다.

전체 처리 단계는 아래와 같다.

1. raw block candidate 정리
2. block segmentation
3. block type 분류
4. block role 분류
5. reading order 복원
6. section tree 생성
7. table 구조 복원
8. figure / caption 연결
9. header / footer / page number 판정
10. OCR assist 병합
11. diagnostics / provenance 완성

---

## 6. StructuredDocument 정의

```json
{
  "document_id": "doc_0001",
  "source": {},
  "meta": {},
  "pages": [],
  "blocks": [],
  "sections": [],
  "tables": [],
  "figures": [],
  "warnings": [],
  "diagnostics": {},
  "provenance": {}
}
```

StructuredDocument는 refinement 이전의 기준 문서다.  
이 시점에서는 semantic normalization이 끝난 상태가 아니므로, 단위 정규화나 fact 생성은 보장하지 않는다.  
대신 다음은 반드시 보장해야 한다.

- block, table, figure, section 객체의 존재
- stable target id
- reading order
- 구조 기반의 관계 정보
- OCR / native 출처 추적

---

## 7. Block Segmentation 상세 규칙

Block은 구조 복원의 기본 단위다.  
문단, 제목, 캡션, 헤더, 푸터, 페이지 번호, 각주, 리스트 항목 등이 모두 block으로 표현된다.

### 7.1 block segmentation의 목표
- 시각적으로 붙어 있는 텍스트를 하나의 구조 단위로 묶는다.
- 다른 역할을 할 가능성이 높은 덩어리는 분리한다.
- semantic normalization 이전에도 사람이 읽을 수 있는 수준의 문서 흐름을 복원한다.

### 7.2 기본 입력 단위
segmentation은 일반적으로 line 또는 span 집합을 기준으로 수행한다.

### 7.3 block 병합 규칙
다음 조건을 동시에 만족하면 같은 block 후보로 병합한다.

- x-range가 충분히 유사하다.
- line spacing이 주변 평균과 유사하다.
- font family / font size / font weight 변화가 급격하지 않다.
- 오른쪽 끝 정렬 또는 왼쪽 들여쓰기 패턴이 일관적이다.
- 중간에 큰 공백이나 도형 영역이 끼어 있지 않다.

### 7.4 block 분리 규칙
다음 조건 중 하나라도 만족하면 새 block으로 분리한다.

- font size가 급격히 변한다.
- centered short line이 나타나고 주변 본문과 스타일이 다르다.
- 앞 줄은 본문인데 다음 줄이 “표”, “그림”, “Figure”, “Table” 등 캡션 패턴이다.
- 큰 vertical gap이 발생한다.
- raw table candidate 영역 안팎을 넘나든다.
- 페이지 상단/하단 반복 영역으로 분류될 가능성이 높다.

### 7.5 리스트와 문단의 분리
다음 패턴은 list block 후보로 간주한다.

- `-`, `•`, `○`, `▪`
- `1.`, `1)`, `(1)`, `가.`, `가)` 등 번호 패턴
- hanging indent가 존재하는 여러 줄

list block은 paragraph와 별도 type을 갖지만, refinement에서 paragraph로 변경될 수 있어야 한다.

---

## 8. Block Type / Role 분류

block에는 type과 role 두 축이 있다.

- type: 구조적 종류
- role: 문서 내 역할

### 8.1 block.type 후보
- paragraph
- heading
- list
- table_caption
- figure_caption
- header
- footer
- footnote
- page_number
- unknown

### 8.2 block.role 후보
- title
- subtitle
- section_heading
- body
- caption
- note
- metadata
- decorative

### 8.3 heading 판정 규칙
heading 판정은 단일 규칙이 아니라 score 기반으로 한다.

#### 사용 특징
- 주변 평균 대비 큰 font size
- bold 또는 semibold
- centered 또는 좌측 정렬이지만 짧은 길이
- 앞뒤 vertical gap이 큼
- 번호 체계 존재 (`1.`, `1.1`, `I.`, `가.` 등)
- 문장 종결 패턴이 적음
- 페이지 상단 가까이 위치

#### 예시 score
```text
heading_score =
  0.30 * font_size_signal +
  0.20 * font_weight_signal +
  0.15 * numbering_pattern_signal +
  0.15 * vertical_gap_signal +
  0.10 * short_text_signal +
  0.10 * position_signal
```

#### 판정 기준
- score >= 0.75 → heading
- 0.55 ~ 0.75 → heading candidate
- 그 외 → paragraph 우선

### 8.4 caption 판정 규칙
caption은 table/figure와의 인접성과 텍스트 패턴을 함께 본다.

#### 사용 특징
- “표”, “그림”, “Figure”, “Table”, “Chart” prefix
- 대상 시각 객체와 매우 가까운 거리
- 텍스트 길이가 짧고 설명형
- 본문보다 작은 폰트
- centered 또는 객체 폭과 유사한 bbox

### 8.5 header/footer 판정 규칙
다음 조건을 강하게 본다.

- 여러 페이지에서 유사 텍스트가 반복
- 상단/하단 고정 영역
- 페이지 번호와 함께 출현
- 문서명, 회사명, 버전, 날짜 등 metadata 패턴

### 8.6 page number 판정 규칙
- 숫자만 존재하거나 `3 / 12`, `- 5 -` 패턴
- 페이지 상하단 고정 영역
- 다수 페이지에서 증가 패턴 존재

---

## 9. Reading Order 복원

reading order는 단순한 y정렬 문제가 아니다.  
특히 다단 문서, 표/본문 혼합, 이미지 + 캡션이 있는 문서에서 핵심이다.

### 9.1 기본 원칙
- 같은 column 내에서는 top-to-bottom
- column 간에는 좌에서 우
- 표/figure와 캡션은 하나의 그룹으로 묶어 읽기 순서를 조정
- header/footer/page number는 본문 순서에서 기본 제외

### 9.2 multi-column 판정
다음 특징을 사용한다.

- block x-center 분포의 군집
- column 간 x-gap의 일관성
- y-overlap가 큰 block들이 서로 다른 x-band에 반복
- page width 대비 본문 띠가 2개 이상 형성

### 9.3 다단 처리 규칙
1. block의 x-center를 기준으로 column cluster 생성
2. cluster 수가 2 이상이면 column ordering 수행
3. 각 column 내부는 y순 정렬
4. column 간 merge는 좌→우 순서

### 9.4 표/그림 그룹 처리
표 또는 그림과 캡션은 reading order에서 따로 떨어지지 않도록 group block으로 다룬다.

---

## 10. Section Tree 구성

section tree는 LLM 문맥 이해와 chunking 모두에 핵심이다.

### 10.1 section 후보 생성
heading으로 판정된 block을 section candidate로 사용한다.

### 10.2 level 추정 규칙
#### 강한 단서
- 번호 패턴
  - `1.` → level 1
  - `1.1` → level 2
  - `1.1.1` → level 3
- roman numeral / alphabetic numbering

#### 약한 단서
- font size hierarchy
- spacing hierarchy
- style hierarchy

### 10.3 부모-자식 연결 규칙
- 현재 heading보다 level이 낮은 가장 가까운 앞 heading을 parent로 연결
- 갑작스러운 level jump는 보정
- numbering 체계가 깨졌으면 style hierarchy 우선

### 10.4 shallow mode
heading confidence가 낮거나 numbering이 불안정하면 shallow section mode를 허용한다.

- level 1만 유지
- 나머지는 body로 흡수
- warning 생성

---

## 11. Table Reconstruction

표는 이 엔진의 가장 중요한 구조 객체 중 하나다.

### 11.1 표 유형
- explicit grid table
- implicit aligned table
- pseudo table
- key-value table
- multi-header matrix
- stub-column table
- note-augmented table

### 11.2 table candidate source
- raw drawing lines
- text alignment 반복
- dense short text clusters
- cell-like rectangles
- OCR table region

### 11.3 explicit grid 판정
- 수평/수직 선 검출
- 선 교차점 기반 grid 형성
- 셀 후보 bbox 구성

### 11.4 implicit table 판정
- 선은 없지만 수직 alignment가 반복
- 각 row의 셀 수가 유사
- 행 간 간격이 안정적
- 숫자/짧은 문자열이 조밀하게 분포

### 11.5 merged cell 처리
merged cell은 아래 단서를 이용한다.

- 하나의 bbox가 여러 열 폭을 차지
- 같은 row 내 다른 셀 대비 넓이가 큼
- 아래 row들에 세부 header가 있음
- upper header propagation 가능

### 11.6 header row 판정
header row 판정은 중요하다.

#### 사용 특징
- table 상단 위치
- bold / centered
- 수치보다 명칭 중심
- unit 포함 문자열
- merged cell 빈도 높음

### 11.7 stub column 판정
- 첫 열에 범주명 반복
- 숫자보다 문자 비중 큼
- 같은 행의 다른 값들을 설명하는 축 역할

### 11.8 table output
구조 복원 완료 후 표는 다음을 가져야 한다.

- `table_id`
- `page_id`
- `section_id`
- `bbox`
- `structure`
- `cells`
- `header_rows`
- `expanded_grid`
- `header_paths`
- `title`
- `notes`
- `quality`
- `source_priority`

---

## 12. Figure / Caption 연결

### 12.1 figure 유형
- chart
- diagram
- screenshot
- photo
- mixed_visual

### 12.2 figure candidate source
- raw image objects
- raster-heavy region
- drawing-heavy region
- OCR text가 거의 없는 large visual region

### 12.3 caption association
caption은 다음 점수로 연결한다.

- 거리
- 상대 위치(위/아래)
- prefix 여부
- 폭 유사성
- 폰트 크기
- centered 여부

association score가 일정 기준 미만이면 연결 보류 후 warning 생성

---

## 13. OCR Assist의 구조 복원 개입

OCR은 구조 복원 전체를 대체하지 않는다.

### 13.1 OCR의 역할
- native text 부족한 영역 보완
- 이미지 기반 표 영역 텍스트 보완
- figure 내부 label 수집
- empty cell 보완

### 13.2 OCR 개입 단위
- page-level
- region-level
- table-region
- cell-level
- figure-region

### 13.3 merge 우선순위
1. native
2. trusted OCR supplement
3. merged result

### 13.4 OCR로 할 수 없는 것
- section tree를 OCR만으로 확정하지 않는다.
- heading 여부를 OCR 텍스트만으로 확정하지 않는다.
- table structure 자체를 OCR 문자열만으로 강제 생성하지 않는다.

### 13.5 OCR 트리거 기준

OCR을 보조적으로 활성화할지 여부는 다음 임계값을 기준으로 판단한다.

#### 트리거 조건

| 조건 | 임계값 | OCR 개입 단위 |
|------|--------|--------------|
| `native_text_coverage < 0.3` | 페이지 내 native 텍스트 커버리지 30% 미만 | 페이지 전체 OCR |
| `image_area_ratio > 0.5` | 페이지 내 이미지 영역 비율 50% 초과 | 이미지 영역 OCR |
| `text_density < 5.0 chars/cm²` | 텍스트 밀도 5자/cm² 미만 | OCR 후보 페이지 |

#### OCR 결과 신뢰도 기준

| 신뢰도 범위 | 처리 방식 | 경고 |
|------------|----------|------|
| ≥ 0.7 | 승인 — native 텍스트와 병합 가능 | 없음 |
| 0.5 ~ 0.7 미만 | 경고 생성, 조건부 사용 | `WARN_OCR_DEPENDENCY_HIGH` |
| < 0.5 | OCR 결과 폐기, native 텍스트 유지 | OCR 결과 제외 |

#### 통합 우선순위

1. native text (항상 최우선)
2. OCR supplement (신뢰도 ≥ 0.7인 경우에만 병합)
3. empty (native도 OCR도 없는 경우)

---

## 14. Diagnostics와 Warnings

엔진은 결과뿐 아니라 “왜 그렇게 판단했는지”를 남겨야 한다.

### 14.1 diagnostics 예시
- page_classification
- text_density
- image_area_ratio
- visual_signals
- heading_scores
- table_detection_scores
- caption_association_scores

### 14.2 warnings 예시
- WARN_READING_ORDER_UNCERTAIN
- WARN_SECTION_TREE_SHALLOW
- WARN_TABLE_HEADER_UNCERTAIN
- WARN_OCR_DEPENDENCY_HIGH
- WARN_CAPTION_LINK_UNCERTAIN
- WARN_DUPLICATED_HEADER_FOOTER

---

## 15. Provenance

모든 구조 객체는 provenance를 유지해야 한다.

### 15.1 provenance source
- native
- ocr
- merged
- inferred
- refined

### 15.2 provenance payload 예시
```json
{
  "source": "merged",
  "page_num": 3,
  "bbox": [100, 120, 220, 140],
  "upstream_object_ids": ["raw_line_23", "ocr_region_02"],
  "decision": "ocr_filled_empty_cell"
}
```

---

## 16. 엔진의 최종 산출물

엔진 단계가 끝나면 최소한 다음 산출물이 가능해야 한다.

- StructuredDocument JSON
- Review용 markdown/JSON 생성 가능 상태
- refinement target id 집합
- diagnostics
- warnings
- provenance map

즉, 이 단계는 “semantic 이전의 완성된 구조 문서”를 만드는 단계다.
