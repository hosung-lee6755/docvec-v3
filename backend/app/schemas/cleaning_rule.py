from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

CleaningRuleType = Literal["REGEX_REPLACE", "EXACT_REMOVE", "LINE_FILTER"]
CleaningRuleScope = Literal["DOCUMENT", "PARAGRAPH", "LINE"]


class CleaningRuleCreate(BaseModel):
    rule_name: str = Field(..., min_length=1, max_length=255)
    rule_type: CleaningRuleType
    pattern: str = Field(..., min_length=1)
    replacement: str | None = None
    scope: CleaningRuleScope = "PARAGRAPH"
    priority: int = 0
    enabled: bool = True

    @model_validator(mode="after")
    def _validate_pattern(self) -> "CleaningRuleCreate":
        if self.rule_type == "REGEX_REPLACE":
            import re

            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValueError(f"올바르지 않은 정규식입니다: {exc}") from exc
        return self


class CleaningRuleUpdate(BaseModel):
    rule_name: str | None = Field(None, min_length=1, max_length=255)
    pattern: str | None = Field(None, min_length=1)
    replacement: str | None = None
    scope: CleaningRuleScope | None = None
    priority: int | None = None
    enabled: bool | None = None


class CleaningRuleResponse(BaseModel):
    id: UUID
    rule_name: str
    rule_type: str
    pattern: str | None
    replacement: str | None
    scope: str
    priority: int
    enabled: bool
    version: int
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CleaningRuleListResponse(BaseModel):
    items: list[CleaningRuleResponse]
