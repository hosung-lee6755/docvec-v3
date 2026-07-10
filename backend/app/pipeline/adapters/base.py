from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


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
    block_type: str = "paragraph"
    confidence: float = 1.0


@dataclass
class RawTableCandidate:
    page_number: int
    rows: list[list[str]]
    bbox: tuple[float, float, float, float] | None = None


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
