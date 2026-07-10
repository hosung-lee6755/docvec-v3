# adapter_interface_spec.md
# Document Vectorization Platform - Adapter Interface Specification

## 1. 문서 목적

본 문서는 문서 포맷별 파싱 어댑터가 준수해야 하는 공통 계약(contract)을 정의한다.
`AdapterResolutionModule`이 런타임에 포맷을 식별하여 어댑터를 선택하며,
모든 어댑터는 동일한 `BaseAdapter` 인터페이스를 구현해야 한다.

---

## 2. BaseAdapter 계약

### 2.1 추상 클래스 정의

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from pathlib import Path


@dataclass
class AdapterCapabilities:
    native_text: bool        # 네이티브 텍스트 추출 가능
    native_table: bool       # 네이티브 표 구조 추출 가능
    native_image: bool       # 이미지 추출 가능
    native_structure: bool   # 헤딩/섹션 구조 추출 가능
    bbox_available: bool     # 바운딩박스 좌표 제공 가능
    reading_order: bool      # 읽기 순서 메타데이터 제공 가능
    ocr_required: bool       # OCR 없이는 텍스트 추출 불가


class BaseAdapter(ABC):
    """모든 포맷 어댑터의 공통 인터페이스."""

    @property
    @abstractmethod
    def format_id(self) -> str:
        """어댑터가 처리하는 포맷 식별자 (예: 'pdf', 'hwp', 'hwpx', 'docx')."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> AdapterCapabilities:
        """이 어댑터의 기능 집합."""
        ...

    @abstractmethod
    def can_handle(self, file_path: Path, mime_type: str) -> bool:
        """주어진 파일을 이 어댑터가 처리할 수 있는지 판단한다."""
        ...

    @abstractmethod
    def extract(self, file_path: Path, options: "ProcessingOptions") -> "RawParsedDocument":
        """파일을 파싱하여 RawParsedDocument를 반환한다."""
        ...

    @abstractmethod
    def extract_metadata(self, file_path: Path) -> dict:
        """파일 메타데이터(작성자, 생성일, 페이지 수 등)를 반환한다."""
        ...
```

### 2.2 불변 조건

- `extract()`는 파일을 수정하지 않는다.
- `extract()`는 항상 `RawParsedDocument`를 반환하거나 `AdapterError`를 발생시킨다.
- `extract()`는 멱등적이다 — 동일 파일에 대한 반복 호출은 동일한 결과를 반환한다.
- 어댑터는 외부 서비스(OCR API 등)에 직접 의존하지 않는다. OCR은 별도 모듈 책임이다.
- 빈 페이지나 이미지 전용 페이지에서도 예외를 발생시키지 않고 빈 블록으로 처리한다.

### 2.3 HWP/HWPX 어댑터 특수성

HWP/HWPX 어댑터는 **단락당 하나의 RawTextBlock**을 생성한다 (문서 전체를 하나의 블록으로 병합하지 않음).
이는 나중에 `process.py::_repaginate_hwp_like()`에서 각 단락을 렌더링된 프리뷰 PDF의 페이지별 텍스트와 매칭하여 
실제 페이지 번호를 할당하기 위한 설계다. 그때까지 `page_number=1`은 플레이스홀더다.

### 2.3 오류 분류

| 예외 클래스 | 의미 |
|------------|------|
| `AdapterError` | 어댑터 기본 예외 |
| `UnsupportedFormatError` | 포맷 버전 미지원 |
| `CorruptedFileError` | 파일 손상 감지 |
| `PasswordProtectedError` | 암호화된 파일 |
| `EmptyDocumentError` | 추출 가능한 콘텐츠 없음 |

---

## 3. RawParsedDocument 스키마

어댑터가 반환하는 원시 파싱 결과 구조다.

```python
@dataclass
class RawPage:
    page_num: int                        # 1-based
    width_pt: float                      # 포인트 단위
    height_pt: float                     # 포인트 단위
    text_blocks: list[RawTextBlock]
    table_candidates: list[RawTableCandidate]
    image_regions: list[RawImageRegion]
    native_text_coverage: float          # 0.0–1.0
    image_area_ratio: float              # 0.0–1.0
    text_density: float                  # chars/cm²


@dataclass
class RawTextBlock:
    block_id: str
    text: str
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 (pt)
    font_name: str | None
    font_size: float | None
    is_bold: bool
    is_italic: bool
    reading_order_hint: int | None


@dataclass
class RawTableCandidate:
    table_id: str
    bbox: tuple[float, float, float, float]
    rows: int
    cols: int
    cells: list[RawCell]
    confidence: float


@dataclass
class RawCell:
    row: int
    col: int
    row_span: int
    col_span: int
    text: str
    bbox: tuple[float, float, float, float]


@dataclass
class RawImageRegion:
    image_id: str
    bbox: tuple[float, float, float, float]
    image_bytes: bytes | None    # 추출 가능한 경우
    ocr_candidate: bool


@dataclass
class RawParsedDocument:
    document_id: str
    source_format: str
    file_hash: str
    page_count: int
    pages: list[RawPage]
    document_metadata: dict
    adapter_id: str
    parse_warnings: list[str]
```

---

## 4. PDF 어댑터

### 4.1 구현 대상

| 항목 | 내용 |
|------|------|
| format_id | `pdf` |
| 처리 라이브러리 | `pdfplumber` (기본), `PyMuPDF(fitz)` (폴백) |
| 지원 버전 | PDF 1.4 이상 |

### 4.2 기능 명세

| 기능 | 지원 여부 | 비고 |
|------|----------|------|
| 텍스트 추출 | ✅ | 문자 단위 bbox 포함 |
| 표 구조 추출 | ✅ | pdfplumber table detection |
| 이미지 추출 | ✅ | 임베디드 이미지 바이트 |
| bbox 좌표 | ✅ | 포인트 단위 |
| 읽기 순서 | 조건부 | 태그된 PDF만 보장 |
| OCR 필요 여부 | 조건부 | 스캔본 PDF는 OCR 필요 |

### 4.3 OCR 신호 수집

`NativeParseModule`이 OCR 필요 여부를 판단하도록 아래 값을 계산한다.

- `native_text_coverage`: 텍스트 레이어 커버리지 (면적 기준)
- `image_area_ratio`: 페이지 대비 이미지 면적 비율
- `text_density`: 텍스트 밀도 (chars/cm²)

### 4.4 제약 사항

- 암호화된 PDF는 `PasswordProtectedError` 발생
- XFA 기반 폼 PDF는 텍스트 추출만 가능, 구조 추출 불가
- 스캔본 PDF는 `native_text_coverage < 0.3` 조건으로 OCR 위임

---

## 5. HWP 어댑터

### 5.1 구현 대상

| 항목 | 내용 |
|------|------|
| format_id | `hwp` |
| 처리 라이브러리 | `hwp5` (pyhwp) |
| 지원 버전 | HWP 5.0 이상 |

### 5.2 기능 명세

| 기능 | 지원 여부 | 비고 |
|------|----------|------|
| 텍스트 추출 | ✅ | 단락 단위 |
| 표 구조 추출 | ✅ | 중첩 표 포함 |
| 이미지 추출 | ✅ | 임베디드 이미지 |
| bbox 좌표 | 제한적 | HWP 좌표계 변환 필요 |
| 읽기 순서 | ✅ | 단락 순서 기반 |
| OCR 필요 여부 | 조건부 | 이미지 삽입 텍스트만 |

### 5.3 HWP 특이 사항

- **한글 내부 좌표계**: HWP는 1/100mm 단위 좌표를 사용. 포인트로 변환 필요 (1pt = 2.54/72 cm, 1 HWP unit = 0.01mm)
- **글상자(Text Box)**: 별도 블록으로 추출, 본문과 분리하여 처리
- **각주/미주**: `footnote`/`endnote` 블록으로 분류
- **섹션 구분**: HWP 섹션 경계를 페이지 그룹으로 매핑
- **그림 캡션**: `caption` 속성으로 그림 객체와 연결

### 5.4 제약 사항

- HWP 5.0 미만 버전은 `UnsupportedFormatError` 발생
- 암호 설정된 HWP 파일: `PasswordProtectedError`
- OLE 구조 손상 파일: `CorruptedFileError`

---

## 6. HWPX 어댑터

### 6.1 구현 대상

| 항목 | 내용 |
|------|------|
| format_id | `hwpx` |
| 처리 방식 | ZIP 압축 해제 후 XML 파싱 |
| 지원 버전 | HWPX 1.0 이상 (HWP 2010+) |

### 6.2 기능 명세

| 기능 | 지원 여부 | 비고 |
|------|----------|------|
| 텍스트 추출 | ✅ | XML element 기반 |
| 표 구조 추출 | ✅ | `<hp:tbl>` 파싱 |
| 이미지 추출 | ✅ | `BinData/` 폴더에서 추출 |
| bbox 좌표 | ✅ | XML 속성 기반 |
| 읽기 순서 | ✅ | XML 문서 순서 기반 |
| OCR 필요 여부 | 조건부 | 이미지 삽입 텍스트만 |

### 6.3 HWPX 내부 구조

```
content.hpf          # 컨텐츠 목록
Contents/
  section0.xml       # 본문 섹션
  section1.xml       # ...
BinData/             # 이미지, 임베디드 파일
Preview/
  PrvText.txt        # 텍스트 미리보기 (신뢰하지 않음)
```

### 6.4 파싱 전략

1. `content.hpf`에서 섹션 파일 목록 확인
2. 각 섹션 XML에서 `<hp:p>`, `<hp:tbl>`, `<hp:pic>` 요소 순회
3. 텍스트 블록: `<hp:t>` 텍스트 집계
4. 표: `<hp:tbl><hp:tr><hp:tc>` 재귀 파싱
5. 이미지: `<hp:pic>` binItemID로 `BinData/` 파일 참조

---

## 7. DOCX 어댑터

### 7.1 구현 대상

| 항목 | 내용 |
|------|------|
| format_id | `docx` |
| 처리 라이브러리 | `python-docx` |
| 지원 버전 | OOXML (Office 2007+) |

### 7.2 기능 명세

| 기능 | 지원 여부 | 비고 |
|------|----------|------|
| 텍스트 추출 | ✅ | 단락 단위 |
| 표 구조 추출 | ✅ | 병합 셀 포함 |
| 이미지 추출 | ✅ | 임베디드 이미지 |
| bbox 좌표 | 제한적 | 페이지 레이아웃 없음 |
| 읽기 순서 | ✅ | XML 문서 순서 |
| OCR 필요 여부 | 조건부 | 이미지 캡처 텍스트만 |

### 7.3 스타일 → 블록 역할 매핑

| Word 스타일 | 매핑 블록 역할 |
|------------|--------------|
| `Heading 1`–`Heading 9` | `section_heading` (level 1–9) |
| `Normal` | `paragraph` |
| `Caption` | `caption` |
| `Header` | `header` |
| `Footer` | `footer` |
| `Footnote Text` | `footnote` |
| 그 외 | `paragraph` |

### 7.4 제약 사항

- 페이지 번호 정보 없음: 페이지 분할은 휴리스틱으로 추정
- 텍스트박스(`<wp:txbx>`): 별도 블록으로 추출, 위치 정보 미포함
- DOCX 내 OLE 임베디드 파일: 이미지로 처리

---

## 8. AdapterRegistry

### 8.1 레지스트리 구조

```python
class AdapterRegistry:
    _registry: dict[str, type[BaseAdapter]] = {}

    @classmethod
    def register(cls, adapter_cls: type[BaseAdapter]) -> None:
        cls._registry[adapter_cls.format_id] = adapter_cls

    @classmethod
    def resolve(cls, file_path: Path, mime_type: str) -> BaseAdapter:
        for adapter_cls in cls._registry.values():
            instance = adapter_cls()
            if instance.can_handle(file_path, mime_type):
                return instance
        raise UnsupportedFormatError(f"지원하지 않는 포맷: {mime_type}")
```

### 8.2 등록 순서

어댑터는 애플리케이션 시작 시 등록된다.

```python
AdapterRegistry.register(PdfAdapter)
AdapterRegistry.register(HwpAdapter)
AdapterRegistry.register(HwpxAdapter)
AdapterRegistry.register(DocxAdapter)
```

### 8.3 포맷 판별 우선순위

1. 파일 시그니처(magic bytes) 확인
2. MIME type 확인
3. 파일 확장자 폴백

---

## 9. 어댑터 추가 요구 사항

새로운 포맷 어댑터를 추가할 때 충족해야 하는 요구 사항:

- [ ] `BaseAdapter` 모든 추상 메서드 구현
- [ ] `AdapterCapabilities` 정확히 선언
- [ ] `RawParsedDocument` 필드 빠짐없이 채움 (빈 값은 빈 리스트로)
- [ ] `parse_warnings`에 처리 중 발생한 비치명 경고 기록
- [ ] `native_text_coverage`, `image_area_ratio`, `text_density` 계산 포함
- [ ] 단위 테스트: 정상 문서, 빈 문서, 손상 문서 케이스 포함
- [ ] `AdapterRegistry`에 등록

---

## 10. 크로스레퍼런스

- execution_architecture (5.2 AdapterResolutionModule)
- engine_design (OCR 트리거 기준 — 13.5)
- config_schema (ProcessingOptions 스키마)
- error_codes (AdapterError 코드 목록)
