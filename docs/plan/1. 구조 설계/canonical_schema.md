# canonical_schema.md
# Document Structuring Solution - Canonical Schema

## 1. 문서 목적

본 문서는 Document Structuring Solution이 사용하는 Canonical Schema를 정의한다.  
Canonical Schema는 포맷별 추출 방식이 달라도 최종 결과를 동일한 구조로 정규화하기 위한 표준 데이터 모델이다.

이 스키마는 다음 목적을 가진다.

- 포맷 독립적인 출력 구조 보장
- refinement / normalization / chunking의 공통 입력 제공
- provenance와 diagnostics 유지
- record / fact / chunk 생성의 기준 제공
- 사람 검토와 기계 처리를 동시에 지원

---

## 2. 최상위 설계 원칙

1. 입력 포맷은 달라도 출력 스키마는 같아야 한다.
2. semantic 정규화 이전 구조와 이후 구조를 명확히 구분해야 한다.
3. 원문 텍스트와 normalized_text를 분리해야 한다.
4. provenance는 객체 단위로 추적 가능해야 한다.
5. warnings와 diagnostics는 별도 계층으로 유지해야 한다.
6. review와 export를 위해 stable id가 필요하다.

---

## 3. 최상위 CanonicalDocument 구조

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
  "records": [],
  "facts": [],
  "chunks": [],
  "quality": {},
  "warnings": [],
  "diagnostics": {},
  "provenance": {}
}
```

### 3.1 필드 설명
- `document_id`: 문서 고유 식별자
- `source`: 입력 원천 정보
- `meta`: 문서 메타데이터
- `pages`: 페이지 정보
- `blocks`: block 객체 목록
- `sections`: section tree
- `tables`: table 객체 목록
- `figures`: figure 객체 목록
- `records`: 표 레코드 등 정형화된 row 단위 데이터
- `facts`: subject-predicate-object 단위 추론 데이터
- `chunks`: 검색/모델 입력 단위
- `quality`: 문서 수준 품질
- `warnings`: 경고 목록
- `diagnostics`: 내부 판정/분석 정보
- `provenance`: 출처 추적 맵

---

## 4. Source 객체

```json
{
  "file_name": "sample.pdf",
  "file_path": "/data/input/sample.pdf",
  "file_type": "pdf",
  "mime_type": "application/pdf",
  "file_hash": "sha256:...",
  "ingested_at": "2026-04-01T10:00:00+09:00",
  "adapter_name": "PDFAdapter"
}
```

### 4.1 목적
- 원문 식별
- 중복 처리
- 포맷별 adapter 추적
- 재처리 가능성 보장

---

## 5. Meta 객체

```json
{
  "title": "문서 제목",
  "language": "ko",
  "page_count": 12,
  "created_at": null,
  "modified_at": null,
  "author": null,
  "detected_layout_type": "mixed"
}
```

### 5.1 목적
- 문서 수준 일반 메타 저장
- review 상단 요약 표시
- downstream 인덱싱 보조

---

## 6. Page 객체

```json
{
  "page_id": "page_0003",
  "page_num": 3,
  "page_kind": "physical",
  "width": 595.0,
  "height": 842.0,
  "rotation": 0,
  "block_ids": ["block_0031", "block_0032"],
  "table_ids": ["table_0004"],
  "figure_ids": ["figure_0002"],
  "diagnostics": {
    "text_density": 14.2,
    "native_text_coverage": 0.87,
    "visual_content_detected": true,
    "page_classification": "table-heavy",
    "ocr_recommended": false
  }
}
```

### 6.1 page_kind
- `physical`: 실제 페이지 기반
- `virtual`: page-like unit
- `unknown`

---

## 7. Block 객체

```json
{
  "block_id": "block_0031",
  "page_id": "page_0003",
  "type": "paragraph",
  "role": "body",
  "bbox": [72.0, 110.0, 520.0, 145.0],
  "text": "2020년 전력 사용 현황은 ...",
  "normalized_text": "2020년 전력 사용 현황은 ...",
  "style": {
    "font_size": 11.0,
    "font_weight": "normal",
    "alignment": "left",
    "indent": 0,
    "line_spacing": 1.5
  },
  "reading_order": 5,
  "section_id": "sec_0002",
  "source": "native",
  "confidence": {
    "type_confidence": 0.94,
    "role_confidence": 0.88
  },
  "review_hint": null
}
```

### 7.1 type enum
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

### 7.2 role enum
- title
- subtitle
- section_heading
- body
- caption
- note
- metadata
- decorative

---

## 8. Section 객체

```json
{
  "section_id": "sec_0002",
  "title": "2. 전력 사용 현황",
  "normalized_title": "전력 사용 현황",
  "level": 1,
  "parent_section_id": null,
  "child_section_ids": ["sec_0003"],
  "block_ids": ["block_0021", "block_0022"],
  "page_range": [2, 5],
  "section_path": ["2. 전력 사용 현황"]
}
```

### 8.1 목적
- 문맥 구조 보존
- chunk 생성 기준
- refinement 이후 section tree 재구성 대상

---

## 9. Table 객체

```json
{
  "table_id": "table_0004",
  "page_id": "page_0003",
  "section_id": "sec_0002",
  "title": "2020년 전력 사용 현황",
  "bbox": [84.9, 269.7, 538.2, 477.0],
  "table_type": "multi_header_matrix",
  "structure": {
    "n_rows": 12,
    "n_cols": 8,
    "has_merged_cells": true,
    "has_stub_column": true
  },
  "cells": [],
  "expanded_grid": [],
  "header_rows": [0, 1],
  "header_paths": [],
  "record_ids": ["record_0001", "record_0002"],
  "notes": [],
  "source_priority": "native_then_ocr",
  "quality": {
    "score": 0.78,
    "cell_fill_rate": 0.92,
    "header_validated": true,
    "numeric_parse_success_rate": 0.88
  }
}
```

### 9.1 table_type enum
- explicit_grid
- implicit_aligned
- key_value
- multi_header_matrix
- stub_column_table
- note_augmented
- pseudo_table
- unknown

---

## 10. Table Cell 객체

```json
{
  "cell_id": "cell_0004_r02_c03",
  "table_id": "table_0004",
  "row": 2,
  "col": 3,
  "rowspan": 1,
  "colspan": 1,
  "bbox": [310.0, 350.0, 360.0, 370.0],
  "text": "12879",
  "normalized_text": "12879",
  "cell_type": "data",
  "source": "merged",
  "confidence": 0.93,
  "parsed_value": 12879,
  "unit": "kWh"
}
```

### 10.1 cell_type enum
- header
- stub
- data
- note
- empty

---

## 11. Expanded Grid

expanded_grid는 병합 셀을 풀어 downstream이 다루기 쉽게 만든 2차원 배열이다.

```json
[
  ["연월", "전력", "전력", "사용정보"],
  ["연월", "계약전력(kW)", "요금적용전력(kW)", "사용전력량(kWh)"],
  ["2020년07월", "250", "114", "12879"]
]
```

### 11.1 원칙
- merged cell은 propagation 후 채운다.
- downstream chunk/record 생성은 expanded_grid를 참조할 수 있다.
- 원래 셀 구조 정보는 별도로 cells에 남는다.

---

## 12. Header Paths

header path는 다단 헤더의 의미 경로를 유지한다.

```json
[
  ["연월"],
  ["전력", "계약전력(kW)"],
  ["전력", "요금적용전력(kW)"],
  ["사용정보", "사용전력량(kWh)"]
]
```

### 12.1 목적
- table record key 생성
- semantic normalization
- fact generation
- table summary chunk 생성

---

## 13. Record 객체

```json
{
  "record_id": "record_0001",
  "table_id": "table_0004",
  "row_index": 2,
  "stub_value": "2020년07월",
  "values": {
    "연월": "2020년07월",
    "계약전력(kW)": 250,
    "요금적용전력(kW)": 114,
    "사용전력량(kWh)": 12879,
    "전기요금(원)": 2323040
  },
  "confidence": 0.89
}
```

### 13.1 목적
- 표를 row 중심 정형 데이터로 변환
- downstream 분석 / 질의응답
- fact 생성의 상위 단위

---

## 14. Fact 객체

```json
{
  "fact_id": "fact_0001",
  "subject": "2020-07",
  "predicate": "사용전력량",
  "object": 12879,
  "unit": "kWh",
  "qualifiers": {
    "source_table_id": "table_0004",
    "page_num": 3
  },
  "confidence": 0.87
}
```

### 14.1 목적
- 원자적 진술 단위 저장
- reasoning / KG / fact retrieval 입력

---

## 15. Figure 객체

```json
{
  "figure_id": "figure_0002",
  "page_id": "page_0004",
  "section_id": "sec_0002",
  "bbox": [70.0, 150.0, 540.0, 260.0],
  "figure_kind": "chart",
  "caption": "2020년 월별 전력 사용량 추이",
  "caption_block_id": "block_0048",
  "ocr_text": "1월 2월 3월 ...",
  "image_path": "data/visual_regions/doc/page_004_figure_01.png",
  "source": "image",
  "quality": {
    "caption_link_confidence": 0.91,
    "ocr_text_confidence": 0.72
  }
}
```

### 15.1 figure_kind enum
- chart
- diagram
- screenshot
- photo
- mixed_visual

---

## 16. Chunk 객체

```json
{
  "chunk_id": "chunk_0101",
  "document_id": "doc_0001",
  "chunk_type": "table_record",
  "text": "연월=2020년07월; 계약전력=250kW; 요금적용전력=114kW; 사용전력량=12879kWh",
  "page_num": 3,
  "section_path": ["2. 전력 사용 현황"],
  "block_ids": [],
  "table_id": "table_0004",
  "figure_id": null,
  "source_types": ["native", "ocr"],
  "confidence": 0.88,
  "semantic_tags": ["table_record", "energy"],
  "provenance_refs": ["record_0001", "table_0004"]
}
```

### 16.1 chunk_type enum
- section
- paragraph
- heading_context
- table_summary
- table_record
- figure_caption
- fact

---

## 17. Quality 객체

```json
{
  "document_quality": {
    "structure_score": 0.82,
    "table_quality_score": 0.75,
    "text_integrity_score": 0.91,
    "ocr_dependency_ratio": 0.18,
    "grade": "B"
  }
}
```

### 17.1 품질 세분화
- document quality
- page quality
- block quality
- table quality
- figure quality
- chunk quality

---

## 18. Warning 객체

```json
[
  {
    "code": "WARN_TABLE_HEADER_UNCERTAIN",
    "severity": "medium",
    "scope": "table",
    "target_id": "table_0004",
    "message": "Header row detection confidence below threshold"
  }
]
```

### 18.1 severity enum
- low
- medium
- high
- critical

---

## 19. Diagnostics 객체

diagnostics는 판정 근거와 내부 수치를 유지한다.

```json
{
  "page_diagnostics": {
    "page_0003": {
      "text_density": 14.2,
      "visual_content_detected": true,
      "heading_candidates": ["block_0021"],
      "table_detection_score": 0.84
    }
  }
}
```

---

## 20. Provenance Map

```json
{
  "block_0031": {
    "source": "native",
    "page_num": 3,
    "bbox": [72.0, 110.0, 520.0, 145.0],
    "upstream_object_ids": ["raw_line_104", "raw_span_210"]
  },
  "cell_0004_r02_c03": {
    "source": "merged",
    "native_text": "",
    "ocr_text": "12879",
    "decision": "ocr_filled_empty_cell",
    "page_num": 3,
    "bbox": [310.0, 350.0, 360.0, 370.0]
  }
}
```

### 20.1 provenance source enum
- native
- ocr
- merged
- inferred
- refined

---

## 21. Schema 계층 정리 및 실제 구현 현황

### 21.0 주요 설계 변경: HWP/HWPX 페이지 분할

**원 설계**: HWPX `pageBreak` 속성으로 실제 페이지 경계 복원 계획.

**실제 구현**: `pageBreak` 속성이 실제 문서에서 항상 "0"(페이지 break 없음)이므로 사용 불가. 대신 LibreOffice 렌더링 Preview PDF의 per-page 텍스트를 ground truth로 사용하여 각 paragraph/table을 실제 페이지에 할당. 이는 내부 처리일 뿐 `CanonicalDocument` schema는 변경 없음 (page_number 필드가 이미 올바른 값으로 채워짐).

### 21.1 Raw Layer
- raw_pages (HWP/HWPX는 parse 후 단일 page_number=1로 반환, structure reconstruction 단계에서 `_repaginate_hwp_like()로 실제 페이지로 분할됨)
- raw_text_blocks (table blocks는 for display용 "[표 N]\n{cell|cell}" 형식)
- raw_lines
- raw_spans
- raw_images
- raw_table_candidates

### 21.2 Structural Layer
- pages
- blocks
- sections
- tables
- figures

### 21.3 Canonical Semantic Layer
- normalized_text
- expanded_grid
- header_paths
- records
- facts
- entities

#### 엔티티 분류 체계 (14종)

| 태그 | 설명 | 예시 |
|------|------|------|
| `PERSON` | 인물명 | 홍길동, Kim Minsu |
| `ORG` | 기관·조직명 | 국토교통부, Anthropic |
| `DATE` | 날짜 표현 | 2026년 1월 1일, 2026-01-01 |
| `TIME` | 시각 표현 | 오전 9시, 14:30 |
| `MONEY` | 금액 | 1억 원, $500 |
| `QUANTITY` | 수량·용량 | 3킬로그램, 500ml |
| `LOCATION` | 장소·지명 | 서울특별시, 강남구 |
| `LAW` | 법령명 | 민법 제393조, 개인정보 보호법 |
| `REGULATION` | 규정·고시명 | 건축법 시행령 제14조 |
| `PRODUCT` | 제품·서비스명 | Galaxy S24, Claude |
| `EVENT` | 이벤트·행사명 | 제22대 국회의원선거 |
| `PERCENTAGE` | 백분율 | 75%, 3.5% |
| `CARDINAL` | 기수 (단위 없는 숫자) | 3, 42 |
| `ORDINAL` | 서수 | 첫째, 제1조 |

### 21.4 Export Layer
- review markdown
- canonical json
- chunks jsonl
- records jsonl
- facts jsonl
- diagnostics json

#### chunks.jsonl 필드 명세

각 줄은 청크 1개를 표현하는 JSON 객체다.

| 필드 | 타입 | 설명 |
|------|------|------|
| `chunk_id` | string (UUID v7) | 청크 고유 식별자 |
| `document_id` | string (UUID v7) | 원본 문서 식별자 |
| `chunk_type` | string | `section` \| `paragraph` \| `heading_context` \| `table_summary` \| `table_record` \| `figure_caption` \| `fact` |
| `text` | string | 청크 전체 텍스트 |
| `page_num` | integer | 시작 페이지 번호 (1-based) |
| `section_id` | string \| null | 소속 섹션 식별자 |
| `section_path` | string[] | 섹션 계층 경로 (예: `["1장", "1.2절"]`) |
| `block_ids` | string[] | 구성 블록 식별자 목록 |
| `table_id` | string \| null | 청크 타입이 table_* 일 때 대상 표 식별자 |
| `figure_id` | string \| null | 청크 타입이 figure_caption일 때 대상 그림 식별자 |
| `source_types` | string[] | 텍스트 출처 (`native`, `ocr`, `merged`) |
| `confidence` | float | 청크 품질 신뢰도 (0.0 ~ 1.0) |
| `semantic_tags` | string[] | 의미 태그 목록 (엔티티 태그 포함 가능) |
| `provenance_refs` | string[] | 원본 블록/셀 provenance 참조 |
| `embedding_model` | string \| null | 임베딩 생성에 사용된 모델 ID |

---

## 22. 설계 결론

Canonical Schema는 단순 출력 형식이 아니라 시스템 전체를 묶는 공통 언어다.  
Parser, Structurer, Refinement, Normalizer, Chunker, Exporter는 모두 이 스키마를 중심으로 연결되어야 한다.
