from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4


@dataclass
class AdapterCapabilities:
    native_text: bool
    native_table: bool
    native_image: bool
    native_structure: bool
    bbox_available: bool
    reading_order: bool
    ocr_required: bool


@dataclass
class RawTextBlock:
    text: str
    page_number: int
    bbox: tuple[float, float, float, float] | None = None
    # "paragraph" | "table" | "ocr" | "header" | "footer" | "footnote" — the
    # last three are assigned post-hoc by TextExtractBlock's repeated-position
    # clustering, not by the adapter itself (문서 파싱 고도화 Phase 1).
    block_type: str = "paragraph"
    confidence: float = 1.0
    # Docling 도입 설계서(2026-07-23) Phase 2 — DoclingAdapter만 채운다. 같은
    # 값을 Document.elements[*]["id"]에도 넣어두므로, TextExtractBlock이
    # full_text를 조립하며 계산한 정확한 (span_start, span_end)를 이 id로
    # 되찾아 해당 element에 그대로 붙일 수 있다(줄 단위 fuzzy 매칭 없이 결정론
    # 적으로 정확). 다른 어댑터는 항상 None — 하위 호환.
    element_id: str | None = None


# A RawTextBlock is deliberately coarse (a whole page's/document's flowing
# text, joined into `parsed_text` as-is) — font signals attached at that
# granularity would just be one smeared "representative" value per page,
# useless for telling an in-page heading from its body text. Font-aware
# structure analysis (문서 파싱 고도화 Phase 2) needs per-LINE signals instead,
# so adapters additionally emit `RawParsedDocument.metadata["line_layout"]`:
# a flat list of dicts, in reading order, independent of and without altering
# `text_blocks`/`parsed_text`:
#   {"page_number": int, "text": str, "bbox": (x0, top, x1, bottom) | None,
#    "font_size": float | None, "is_bold": bool, "is_italic": bool,
#    "style_name": str | None}  # style_name is DOCX-only ("Heading 1" etc.)
# Omitted entirely (empty list) for OCR'd pages and for formats with no
# stable per-run font API (HWP/HWPX — see hwp_adapter.py).


@dataclass
class RawTableCandidate:
    page_number: int
    rows: list[list[str]]
    bbox: tuple[float, float, float, float] | None = None
    # Stable identity carried through to Document.tables[*]["id"] and
    # DocumentNode.source_table_id so a TABLE node can reference its source
    # table across the JSON/tree split (문서 파싱 고도화 Phase 3).
    id: str = field(default_factory=lambda: str(uuid4()))
    confidence: float = 1.0
    # "ruled" (pdfplumber find_tables, bordered) | "implicit_alignment"
    # (whitespace/column clustering, no ruling lines).
    detected_as: str = "ruled"


@dataclass
class RawImageRegion:
    page_number: int
    bbox: tuple[float, float, float, float]
    image_bytes: bytes | None = None


@dataclass
class RawPage:
    page_number: int
    width: float
    height: float
    text_blocks: list[RawTextBlock]
    table_candidates: list[RawTableCandidate]
    image_regions: list[RawImageRegion]
    native_text_coverage: float = 0.0
    image_area_ratio: float = 0.0
    # Mean per-word OCR confidence (0-1) when this page was OCR'd via
    # pytesseract.image_to_data (문서 파싱 고도화 Phase 3). None for
    # natively-extracted pages, and also None when OCR was done through a
    # cloud VLM instead of Tesseract — VLMs don't expose word-level confidence.
    ocr_confidence: float | None = None
    # Word count backing `ocr_confidence`'s average — carried alongside it so
    # Document.ocr_page_confidence can report both without recomputing.
    ocr_word_count: int | None = None


@dataclass
class RawParsedDocument:
    format_id: str
    page_count: int
    pages: list[RawPage]
    metadata: dict
    warnings: list[str]


class BaseAdapter(ABC):
    @property
    @abstractmethod
    def format_id(self) -> str:
        ...

    @property
    @abstractmethod
    def capabilities(self) -> AdapterCapabilities:
        ...

    @abstractmethod
    def can_handle(self, file_path: Path, mime_type: str) -> bool:
        ...

    @abstractmethod
    def extract(self, file_path: Path, options: dict) -> RawParsedDocument:
        ...

    @abstractmethod
    def extract_metadata(self, file_path: Path) -> dict:
        ...
