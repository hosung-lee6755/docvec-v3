# refinement.md
# Document Structuring Solution - Refinement Specification

## 1. 문서 목적

본 문서는 문서 구조화 이후 사용자가 수행하는 정제(refinement) 기능과 그 후처리 규칙을 정의한다.  
정제 단계는 자동 구조화 결과를 사람이 검토하고 보정하는 필수 계층이며, 이 단계를 통해 문서는 “자동 추출 결과”에서 “신뢰 가능한 구조 데이터”로 승격된다.

본 문서는 다음을 포함한다.

- refinement 대상 단위
- refinement 명령 종류
- 명령별 적용 규칙
- non-destructive 저장 원칙
- refinement 이후 부분 재계산 규칙
- refinement JSON 형식
- provenance 및 audit 기록 방식

---

## 2. refinement의 위치

refinement는 `StructuredDocument`와 `CanonicalDocument` 사이에 위치한다.

흐름:
- RawParsedDocument → Structure Reconstruction → StructuredDocument
- StructuredDocument → Review Bundle → 사용자 판단
- 사용자 refinement → RefinedDocument
- RefinedDocument → Semantic Normalization → CanonicalDocument

즉, refinement는 raw parse 결과가 아니라 **구조가 복원된 결과**에 적용한다.

---

## 3. refinement 설계 원칙

1. 원본 structured data를 파괴적으로 수정하지 않는다.
2. refinement는 delta layer로 저장한다.
3. 모든 수정은 target_id 기반으로 재현 가능해야 한다.
4. refinement 적용 후에는 관련 객체만 부분 재계산한다.
5. refinement는 사람이 한 판단이므로 provenance처럼 추적해야 한다.
6. refinement 가능한 대상은 stable id를 가져야 한다.

---

## 4. 정제 대상 단위

### 4.1 block 단위
- paragraph
- heading
- caption
- header
- footer
- footnote
- page_number

### 4.2 section 단위
최종 목표에서는 section tree 전체를 수정 가능하게 할 수 있으나, section 직접 편집은 구조 영향이 크므로 별도 명령으로 다룬다.

### 4.3 table 단위
- table 전체
- table header 설정
- table 제외
- table 관련 OCR preference

### 4.4 cell 단위
최종 목표에서는 cell value 수정과 cell type 수정이 가능해야 한다.  
다만 cell refinement는 매우 강한 후처리 연쇄를 유발하므로 별도 명령 체계가 필요하다.

### 4.5 figure 단위
- figure 제외
- caption 연결 재지정
- figure OCR 사용 여부

### 4.6 OCR 결과 단위
- page-level OCR 선호도
- region-level OCR 선호도
- native vs OCR source preference

---

## 5. refinement 명령 모델

기본 구조는 아래와 같다.

```json
{
  "document_id": "doc_0001",
  "refinements": [
    {
      "op_id": "ref_0001",
      "type": "block_remove",
      "target_id": "block_0031",
      "payload": {},
      "author": "user",
      "created_at": "2026-04-01T10:20:00+09:00"
    }
  ]
}
```

### 5.1 공통 필드
- `op_id`: refinement operation id
- `type`: 명령 종류
- `target_id`: 수정 대상 객체 id
- `payload`: 명령별 세부 값
- `author`: 수행자
- `created_at`: 수행 시각

---

## 6. refinement 명령 종류

최종 설계 기준으로 정의할 명령은 아래와 같다.

### 6.1 block_remove
특정 block을 제거 대상으로 지정한다.

```json
{
  "type": "block_remove",
  "target_id": "block_0031",
  "payload": {}
}
```

#### 사용 시나리오
- header/footer 제거
- page number 제거
- OCR noise block 제거
- 중복 본문 block 제거
- 불필요한 decorative block 제거

#### 영향
- section tree 재구성 가능
- reading order 변경 가능
- chunk 재생성 필요
- 품질 점수 변동 가능

---

### 6.2 block_role_change
block의 role을 변경한다.

```json
{
  "type": "block_role_change",
  "target_id": "block_0045",
  "payload": {
    "new_role": "section_heading"
  }
}
```

#### 허용 예
- body → section_heading
- section_heading → body
- body → caption
- caption → body

#### 금지 예
- 존재하지 않는 role로 변경
- 시스템이 정의하지 않은 enum 사용

#### 영향
- section tree 재구성
- caption association 재평가
- chunk 재생성
- review hint 재계산 가능

---

### 6.3 table_remove
표 전체를 제외한다.

```json
{
  "type": "table_remove",
  "target_id": "table_0004",
  "payload": {}
}
```

#### 사용 시나리오
- decorative table 제거
- 잘못 인식된 pseudo-table 제거
- 분석 대상 제외 표 제거

#### 영향
- record 제거
- fact 제거
- table 관련 chunk 제거
- 품질 점수 재계산

---

### 6.4 table_header_override
표의 header row를 수동으로 지정한다.

```json
{
  "type": "table_header_override",
  "target_id": "table_0004",
  "payload": {
    "header_rows": [0, 1]
  }
}
```

#### 사용 시나리오
- header row 자동 판정 오류 수정
- header 범위 축소/확대
- multi-level header 정정

#### 영향
- header_paths 재생성
- expanded_grid 일부 재생성 가능
- records 재생성
- facts 재생성
- table summary chunk 재생성

---

### 6.5 ocr_source_preference
특정 page/region/table/cell에 대해 OCR 사용 우선순위를 지정한다.

```json
{
  "type": "ocr_source_preference",
  "target_id": "page_0008",
  "payload": {
    "preference": "native_only"
  }
}
```

#### preference enum
- `native_only`
- `ocr_preferred`
- `merge_allowed`
- `ocr_disabled`

#### 영향
- affected block text 재결정
- table cell text 재결정
- record / fact 재생성 가능
- OCR dependency score 변동

---

### 6.6 명령 구현 단계 구분

정제 명령은 구현 우선순위에 따라 **Phase 1**과 **Phase 2**로 구분한다.

#### Phase 1 — 핵심 명령 (필수 구현)

아래 5개 명령은 Sections 6.1–6.5에 상세 정의되어 있으며, 초기 구현에서 반드시 지원해야 한다.

| 명령 | 정의 위치 | 필요한 이유 |
|------|----------|------------|
| `block_remove` | 6.1 | 오인식된 블록(머리글/바닥글/공백 등) 제거 — 가장 빈번한 정제 작업 |
| `block_role_change` | 6.2 | heading/paragraph 오분류 수정 — 섹션 구조에 직접 영향 |
| `table_remove` | 6.3 | 잘못 감지된 표 제거 |
| `table_header_override` | 6.4 | 헤더 행 수 수정 — 표 데이터 파싱 정확도에 필수 |
| `ocr_source_preference` | 6.5 | native/OCR 선택 — OCR 품질이 낮은 페이지 보정 |

#### Phase 2 — 확장 명령 (이후 구현)

아래 10개 명령은 최종 설계 범위에 포함되지만, Phase 1 완료 후 단계적으로 구현한다.  
스키마는 Phase 1부터 포함 가능하며, 실제 처리 로직만 이후에 추가한다.

| 명령 | 대상 객체 | 설명 |
|------|----------|------|
| `section_parent_override` | Section | 섹션 계층 부모 재지정 |
| `section_level_override` | Section | 섹션 레벨(depth) 수정 |
| `cell_value_override` | TableCell | 셀 텍스트 값 직접 수정 |
| `cell_type_override` | TableCell | 셀 타입(header/data) 변경 |
| `figure_remove` | Figure | 잘못 감지된 그림 제거 |
| `caption_relink` | Figure/Table | 캡션 연결 재지정 |
| `reading_order_override` | Block[] | 블록 읽기 순서 수동 지정 |
| `unit_override` | Fact | 수치 단위 수정 |
| `fact_remove` | Fact | 잘못 추출된 사실 제거 |
| `lock_object` | 모든 객체 | 이후 자동 처리에서 변경 금지 표시 |

---

## 7. non-destructive 저장 원칙

refinement는 원본 StructuredDocument를 덮어쓰지 않는다.

### 7.1 저장 방식
- original structured document 보존
- refinement json 별도 저장
- applied view는 파생 결과로 생성
- 사용자 텍스트 편집 시 `DocumentTextRevision` 스냅샷 저장 (non-destructive)

### 7.2 장점
- 재현 가능
- 되돌리기 가능
- audit 가능
- refinement 실험 가능
- 버전 관리 가능

### 7.3 applied result
`RefinedDocument`는 원본 + refinement delta를 반영한 파생 상태다.

### 7.4 사용자 텍스트 편집의 non-destructive 구현

**실제 구현 (models/document_revision.py `DocumentTextRevision`)**: RAG 원본 텍스트가 변경될 때마다 스냅샷 저장.

**저장 시점**:
- `PARSE`: 초기 파싱 완료 후 (자동 생성, `created_by` 미지정)
- `REVIEW_EDIT`: 사용자가 Review 단계에서 텍스트 편집
- `RAG_EDIT`: 사용자가 RAG 데이터 탭에서 청킹 결과/parsed_text 편집
- `RESTORE`: 사용자가 특정 revision으로 복원

**효과**:
- 모든 revision의 parsed_text를 보관 → 각 revision마다 chunking/embedding 재시작 가능
- 편집 이력 추적 및 특정 시점으로 롤백 가능
- Refinery JSON 명령이 아닌 직접 텍스트 편집도 audit 가능

---

## 8. refinement 적용 순서

명령 순서는 중요하다.  
권장 순서는 아래와 같다.

1. remove 계열
2. role/type override 계열
3. table header / structure override 계열
4. source preference 계열
5. lock / freeze 계열
6. recompute

### 8.1 이유
제거와 role 변경이 가장 큰 구조 변화를 일으키므로 먼저 적용해야 downstream recompute 비용을 줄일 수 있다.

---

## 9. refinement validity 검사

적용 전 다음 검사를 수행해야 한다.

### 9.1 target 존재 여부
- target_id가 현재 StructuredDocument에 존재하는가

### 9.2 target type 적합성
- `table_header_override`가 table에만 적용되는가
- `block_role_change`가 block에만 적용되는가

### 9.3 payload 형식 검사
- enum 값 유효성
- header_rows 형식
- numeric / list / string 타입 일치 여부

### 9.4 충돌 검사
- 제거된 객체에 다시 role_change를 적용하지 않는가
- 같은 table에 상충하는 header override가 중복되는가

---

## 10. Post-Refinement Recompute

refinement 이후에는 무조건 관련 영역을 재계산해야 한다.  
이 단계가 없으면 refinement는 단순 표시 정보에 그치게 된다.

### 10.1 recompute 대상 원칙
- 전체 재계산은 지양
- 영향 범위 기반 부분 재계산
- 단, dependency가 너무 넓으면 문서 단위 재계산 허용

---

## 11. 명령별 재계산 영향

### 11.1 block_remove
재계산:
- page.block_ids
- reading order
- section membership
- section tree
- chunk set
- quality score

### 11.2 block_role_change
재계산:
- section tree
- caption association
- chunk generation
- review hints
- quality

### 11.3 table_remove
재계산:
- page.table_ids
- table list
- record list
- fact list
- table-related chunk set
- quality

### 11.4 table_header_override
재계산:
- header_rows
- header_paths
- expanded_grid
- records
- facts
- table summary chunk
- table record chunks
- quality

### 11.5 ocr_source_preference
재계산:
- affected block text
- affected cell text
- merged text
- records/facts/chunks
- OCR dependency score
- warnings

---

## 12. refinement history / audit

모든 refinement는 audit 가능해야 한다.

### 12.1 예시 구조
```json
{
  "op_id": "ref_0010",
  "type": "table_header_override",
  "target_id": "table_0004",
  "before": {
    "header_rows": [0]
  },
  "after": {
    "header_rows": [0, 1]
  },
  "author": "user",
  "created_at": "2026-04-01T11:00:00+09:00"
}
```

### 12.2 목적
- 변경 추적
- rollback
- 품질 비교
- 협업 검토

---

## 13. RefinedDocument 구조 예시

```json
{
  "document_id": "doc_0001",
  "base_structured_document_id": "doc_0001",
  "applied_refinements": ["ref_0001", "ref_0002"],
  "removed_block_ids": ["block_0031"],
  "role_overrides": {
    "block_0045": "section_heading"
  },
  "table_header_overrides": {
    "table_0004": [0, 1]
  },
  "ocr_preferences": {
    "page_0008": "native_only"
  },
  "recompute_targets": {
    "sections": true,
    "tables": ["table_0004"],
    "chunks": true,
    "quality": true
  }
}
```

---

## 14. refinement와 provenance의 관계

refinement는 provenance source 중 하나로 들어갈 수 있다.

### 14.1 예시
- `source = refined`
- `decision = block_removed_by_user`
- `decision = header_rows_overridden_by_user`

### 14.2 이유
최종 산출물이 자동 추출인지 사용자 보정 결과인지 구분 가능해야 한다.

---

## 15. refinement와 review의 관계

review는 refinement의 전 단계다.

- review markdown / json으로 사용자는 이상 후보를 확인
- refinement json에 실제 수정 내용을 기록
- refinement 적용 후 recompute
- recompute 결과가 canonical document에 반영

즉, review는 “검토 표현”이고 refinement는 “구조 수정 명령”이다.

---

## 16. refinement 설계 결론

정제 단계는 단순 예외 처리 기능이 아니다.  
이 계층이 존재해야 시스템은 “자동 추출기”에서 “운영 가능한 구조화 솔루션”으로 올라간다.

따라서 refinement는 다음을 만족해야 한다.

- stable id 기반
- non-destructive
- recompute 연계
- provenance 반영
- audit 가능
- semantic / chunk / quality에 실제 영향
