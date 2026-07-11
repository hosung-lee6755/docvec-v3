from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

DictionaryEntryType = Literal["stopword", "synonym", "custom_word"]
MatchType = Literal["EXACT", "CONTAINS", "PREFIX", "SUFFIX", "REGEX"]
SynonymDirection = Literal["ONE_WAY", "BIDIRECTIONAL"]
SynonymProcessingMode = Literal["NORMALIZE", "REPLACE", "SEARCH_EXPAND", "TAGGING"]
UserTermType = Literal[
    "TECHNICAL_TERM", "ABBREVIATION", "ORGANIZATION", "PERSON",
    "PRODUCT", "PROJECT", "POLICY", "CUSTOM",
]
UserProcessingRule = Literal["KEEP", "NORMALIZE", "REPLACE", "TAG", "EXTRACT", "MASK", "IGNORE"]


class DictionaryEntryCreate(BaseModel):
    entry_type: DictionaryEntryType
    # Stopword: excluded word. Synonym: canonical/representative term.
    # Custom word: standard term.
    term: str = Field(..., min_length=1, max_length=255)
    # Synonym: the synonym strings. Custom word: aliases/typos/spacing variants.
    # Unused for stopword.
    variants: list[str] = Field(default_factory=list)

    match_type: MatchType | None = None
    direction: SynonymDirection | None = None
    processing_mode: SynonymProcessingMode | None = None
    term_type: UserTermType | None = None
    processing_rule: UserProcessingRule | None = None
    pronunciation: str | None = Field(None, max_length=255)

    case_sensitive: bool = False
    language: str = Field("ko", max_length=10)
    scope: list[str] = Field(default_factory=lambda: ["ALL"])
    description: str | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def _apply_type_defaults(self) -> "DictionaryEntryCreate":
        if self.entry_type == "stopword":
            self.match_type = self.match_type or "EXACT"
        elif self.entry_type == "synonym":
            if not self.variants:
                raise ValueError("동의어 사전은 최소 1개의 동의어(variants)가 필요합니다")
            self.direction = self.direction or "ONE_WAY"
            self.processing_mode = self.processing_mode or "NORMALIZE"
        elif self.entry_type == "custom_word":
            self.term_type = self.term_type or "CUSTOM"
            self.processing_rule = self.processing_rule or "KEEP"
        return self


class DictionaryEntryUpdate(BaseModel):
    """Partial update — only fields explicitly set are applied. `variants`,
    when provided, REPLACES the entry's full variant list (not a merge)."""

    term: str | None = Field(None, min_length=1, max_length=255)
    variants: list[str] | None = None
    match_type: MatchType | None = None
    direction: SynonymDirection | None = None
    processing_mode: SynonymProcessingMode | None = None
    term_type: UserTermType | None = None
    processing_rule: UserProcessingRule | None = None
    pronunciation: str | None = Field(None, max_length=255)
    case_sensitive: bool | None = None
    language: str | None = Field(None, max_length=10)
    scope: list[str] | None = None
    description: str | None = None
    enabled: bool | None = None


class DictionaryEntryResponse(BaseModel):
    id: UUID
    entry_type: DictionaryEntryType
    term: str
    variants: list[str]
    match_type: str | None
    direction: str | None
    processing_mode: str | None
    term_type: str | None
    processing_rule: str | None
    pronunciation: str | None
    case_sensitive: bool
    language: str
    scope: list[str]
    description: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DictionaryEntryListResponse(BaseModel):
    items: list[DictionaryEntryResponse]


class DictionaryImportResult(BaseModel):
    created: int
    updated: int
    skipped: int
    skipped_rows: list[int]
