# review_spec.md
# Document Structuring Solution - Review Bundle & Review Markdown Specification

## 1. 문서 목적

본 문서는 사용자가 파싱/구조화 결과를 검토하기 위한 Review Bundle과 Review Markdown의 상세 규칙을 정의한다.  
Review 시스템은 단순 미리보기가 아니라, refinement 대상을 빠르고 정확하게 식별하도록 설계된 검토 전용 출력 계층이다.

본 문서는 다음을 포함한다.

- Review Bundle 구성
- JSON + Markdown 동시 제공 원칙
- Markdown 내 식별자 표기 규칙
- review_hint 체계
- 표 / 블록 / figure 출력 형식
- OCR 텍스트 표시 규칙
- refinement template 제공 방식

---

## 2. Review Bundle의 목적

Review Bundle은 사용자가 자동 구조화 결과를 검토하고 정제 결정을 내릴 수 있도록 하는 산출물 묶음이다.

핵심 목적은 다음과 같다.

1. 문서 전체 흐름을 빠르게 파악할 수 있게 한다.
2. JSON을 열지 않고도 구조 오류를 찾을 수 있게 한다.
3. JSON 기반 refinement를 정확히 작성할 수 있게 한다.
4. warnings, diagnostics, OCR 개입 여부를 함께 보여준다.
5. review와 refinement를 분리하되 유기적으로 연결한다.

---

## 3. Review Bundle 구성

Review Bundle은 최소 아래 4종으로 구성한다.

### 3.1 structured review JSON
- StructuredDocument 기반
- stable id 유지
- refinement target 지정 기준

권장 파일명:
- `doc_0001.review.json`

### 3.2 review markdown
- 사람이 빠르게 읽는 검토용 문서
- 주요 구조와 warnings를 가시화
- ids, review_hint 포함

권장 파일명:
- `doc_0001.review.md`

### 3.3 diagnostics summary
- warnings
- 품질 지표
- OCR 개입 정보
- 표/그림 후보 정보

권장 파일명:
- `doc_0001.diagnostics.json`

### 3.4 refinement template
- 사용자가 정제 명령을 적기 시작하는 빈 템플릿

권장 파일명:
- `doc_0001.refinement.template.json`

---

## 4. JSON + Markdown 동시 제공 원칙

### 4.1 이유
- JSON만 있으면 정밀하지만 검토가 불편하다.
- Markdown만 있으면 보기 쉽지만 정밀 수정 타깃이 모호하다.
- 둘을 같이 줘야 사람이 빠르게 보고, 기계가 정확히 적용할 수 있다.

### 4.2 원칙
1. 같은 StructuredDocument를 기준으로 생성한다.
2. Markdown의 식별자는 JSON의 target_id와 동일해야 한다.
3. Markdown은 가독성을, JSON은 정밀 제어를 담당한다.
4. diagnostics는 JSON과 Markdown 양쪽에서 확인 가능해야 한다.

---

## 5. Review Markdown 전체 구성

권장 순서:

1. 문서 메타 요약
2. 처리 요약
3. warning 요약
4. section / block 본문 검토
5. table 검토
6. figure 검토
7. refinement 안내

---

## 6. 문서 상단 메타 요약 형식

예시:

```md
# Review Bundle - sample.pdf

- document_id: doc_0001
- file_type: pdf
- page_count: 12
- detected_language: ko
- overall_quality: B
- warnings: 4
```

### 6.1 목적
- 문서 전체 상태를 즉시 파악
- review 우선순위 가늠
- 문서 id 복사 가능

---

## 7. 처리 요약 형식

예시:

```md
## Processing Summary

- blocks: 142
- sections: 8
- tables: 6
- figures: 3
- OCR applied pages: 2
- OCR dependency ratio: 0.14
```

### 7.1 목적
- 구조화 결과 규모 파악
- OCR 개입 정도 확인
- 문서 난이도 추정

---

## 8. warning 요약 형식

예시:

```md
## Warnings

- WARN_TABLE_HEADER_UNCERTAIN: table_0004
- WARN_SECTION_TREE_SHALLOW: doc_0001
- WARN_OCR_DEPENDENCY_HIGH: page_0008
```

### 8.1 원칙
- warning code와 target_id를 같이 표기한다.
- 사용자는 무엇을 먼저 봐야 할지 즉시 알 수 있어야 한다.
- severity가 있으면 함께 표기할 수 있다.

---

## 9. Section 표현 규칙

예시:

```md
## [SECTION sec_0002 | level=1 | pages=2-5]
### 2. 전력 사용 현황
```

### 9.1 포함 항목
- section_id
- level
- page_range (HWP/HWPX 문서의 경우 Preview PDF 기반 실제 페이지 번호 반영)
- title

### 9.2 목적
- 문서 논리 구조 파악
- refinement 후 section 변화 확인
- chunking 기준 문맥 확인
- HWP/HWPX 문서의 경우 실제 페이지 범위 확인 가능 (단일 page_number=1에서 벗어남)

---

## 10. Block 표현 규칙

### 10.1 기본 형식
예시:

```md
[BLOCK block_0021 | role=section_heading | page=2 | source=native]
2.1 월별 사용량 현황
```

```md
[BLOCK block_0022 | role=body | page=2 | source=native]
2020년 전력 사용 현황은 ...
```

### 10.2 표시 항목
- block_id
- role
- page
- source

### 10.3 숨길 항목
아래는 기본 md에서는 숨긴다.
- full bbox
- full confidence object
- raw parser internals

이 정보는 review json에서 확인한다.

---

## 11. review_hint 규칙

review_hint는 확정 판정이 아니라 “검토 우선순위 표시”다.

### 11.1 hint enum
- removal_candidate
- heading_candidate
- caption_candidate
- header_review_needed
- ocr_review_needed
- table_review_needed
- low_confidence
- duplicate_suspected

### 11.2 block 예시
```md
[BLOCK block_0003 | role=header | page=1 | source=native | review_hint=removal_candidate]
회사 내부 보고서
```

### 11.3 목적
- 사람이 빠르게 의심 구간 탐색
- refinement 타깃 후보 식별

---

## 12. OCR 텍스트 표시 규칙

OCR 유래 텍스트는 native와 명확히 구분해야 한다.

### 12.1 OCR block 예시
```md
[BLOCK block_0108 | role=body | page=8 | source=ocr | review_hint=ocr_review_needed]
> [OCR] 추출된 텍스트 내용 ...
```

### 12.2 mixed source 예시
```md
[BLOCK block_0110 | role=body | page=8 | source=mixed]
본문 일부는 native이고, 아래 값은 OCR 보강됨.
> [OCR supplement] 12,879
```

### 12.3 목적
- OCR 오류 탐지
- native vs OCR 선호도 결정
- source preference refinement 지원

---

## 13. Table 표현 규칙

표는 본문 속에 흡수하지 않고 별도 검토 섹션으로 명확히 보여준다.

### 13.1 table 메타 헤더
예시:

```md
## [TABLE table_0004 | page=3 | section=sec_0002 | quality=0.78]
- title: 2020년 전력 사용 현황
- header_rows: [0, 1]
- table_type: multi_header_matrix
- source_priority: native_then_ocr
- review_hint: header_review_needed
```

### 13.2 table 내용 표현
가능하면 Markdown 표로 표현한다.

```md
| 연월 | 계약전력(kW) | 요금적용전력(kW) | 사용전력량(kWh) |
|---|---:|---:|---:|
| 2020년07월 | 250 | 114 | 12879 |
| 2020년08월 | 250 | 112 | 12710 |
```

### 13.3 긴 표 처리
긴 표는 전체를 다 보여주지 않고 일부만 노출할 수 있다.

예:
```md
_총 48행 중 상위 10행만 표시_
```

### 13.4 목적
- header row 판단
- 잘못 인식된 표 제거 여부 판단
- OCR 수치 오류 탐색

---

## 14. Table Header 검토 보조 규칙

header 판단이 불안정한 표는 추가 정보와 함께 출력한다.

예시:

```md
- review_hint: header_review_needed
- candidate_header_rows: [0, 1]
- warning: WARN_TABLE_HEADER_UNCERTAIN
```

### 14.1 목적
- 사용자가 `table_header_override` 필요 여부를 빠르게 판단

---

## 15. Figure 표현 규칙

예시:

```md
## [FIGURE figure_0002 | page=4 | section=sec_0002 | kind=chart]
- caption: 2020년 월별 전력 사용량 추이
- caption_block_id: block_0048
- source: image
- review_hint: caption_candidate
```

### 15.1 figure OCR 표시
```md
> [FIGURE OCR]
> 1월 2월 3월 4월 ...
```

### 15.2 목적
- caption 연결 검토
- figure 제거 여부 판단
- OCR label 이상 탐지

---

## 16. ID 표기 규칙

Markdown에서 사용하는 id는 JSON과 동일해야 한다.

### 16.1 권장 형식
- `doc_0001`
- `page_0003`
- `sec_0002`
- `block_0021`
- `table_0004`
- `figure_0002`
- `cell_0004_r02_c03`

### 16.2 원칙
- zero padding 사용
- 복사하기 쉽고 정규식 파싱 가능해야 함
- 동일 문서 내에서 유일해야 함

---

## 17. refinement template 제공

review bundle에는 refinement template를 함께 제공해야 한다.

예시:

```json
{
  "document_id": "doc_0001",
  "refinements": []
}
```

### 17.1 목적
- 사용자가 바로 정제 명령을 쓰기 시작할 수 있음
- review → refinement 전환 비용 감소
- 자동화 스크립트 입력 형식 고정

---

## 18. review markdown 마지막 안내 문구

파일 말미에 사용 가능한 refinement를 안내한다.

예시:

```md
## Refinement Guide

지원되는 refinement:
- block_remove
- block_role_change
- table_remove
- table_header_override
- ocr_source_preference

정제는 refinement json에서 target_id 기준으로 기록한다.
```

### 18.1 목적
- 문서만 보고도 사용자가 다음 행동을 알 수 있게 함
- json 파일 구조를 매번 다시 찾지 않게 함

---

## 19. Review JSON 구조 예시

```json
{
  "document_id": "doc_0001",
  "sections": [
    {"section_id": "sec_0002", "block_ids": ["block_0021", "block_0022"]}
  ],
  "blocks": [
    {"block_id": "block_0021", "role": "section_heading", "page": 2, "source": "native"}
  ],
  "tables": [
    {"table_id": "table_0004", "header_rows": [0], "review_hint": "header_review_needed"}
  ],
  "figures": [],
  "warnings": []
}
```

### 19.1 목적
- refinement automation input
- structured review UI source
- markdown과 동일 대상 참조

---

## 20. Review Bundle 폴더 예시

```text
review_bundle/
├─ doc_0001.review.json
├─ doc_0001.review.md
├─ doc_0001.diagnostics.json
└─ doc_0001.refinement.template.json
```

---

## 21. review 설계 결론

Review 시스템은 단순 미리보기가 아니다.  
이 계층이 있어야 사용자는:

- 빠르게 읽고
- 정확히 target을 식별하고
- refinement json을 작성하며
- 신뢰 가능한 구조 데이터를 확정할 수 있다.

즉 review는 사람용 표현, refinement는 구조 수정 명령, diagnostics는 판단 근거다.
