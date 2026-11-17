"""관리자 문의 요청과 응답 모양. 글자 수 제한은 여기서 한 번에 건다."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

InquiryCategory = Literal["error", "question", "request", "other"]
InquiryStatus = Literal["open", "in_progress", "resolved", "closed"]

TITLE_MAX = 200
BODY_MAX = 5000


def _required_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise ValueError("내용을 입력하세요")
    return value


class InquiryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    body: str = Field(min_length=1, max_length=BODY_MAX)
    category: InquiryCategory = "question"
    document_id: UUID | None = None

    @field_validator("title", "body")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _required_text(value) or ""


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=BODY_MAX)

    @field_validator("body")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _required_text(value) or ""


class InquiryUpdate(BaseModel):
    """작성자는 제목·내용·분류를 열린 문의에서 고치고, 상태는 관리자가 바꾸거나 작성자가 종료한다."""
    title: str | None = Field(default=None, min_length=1, max_length=TITLE_MAX)
    body: str | None = Field(default=None, min_length=1, max_length=BODY_MAX)
    category: InquiryCategory | None = None
    status: InquiryStatus | None = None

    @field_validator("title", "body")
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        return _required_text(value)


class DocumentRef(BaseModel):
    id: str
    original_filename: str
    status: str


class MessageOut(BaseModel):
    id: str
    author_id: str
    author_name: str
    is_admin: bool
    body: str
    created_at: datetime


class InquiryListItem(BaseModel):
    id: str
    title: str
    category: InquiryCategory
    status: InquiryStatus
    author_id: str
    author_name: str
    document_id: str | None
    created_at: datetime
    updated_at: datetime


class InquiryList(BaseModel):
    total: int
    items: list[InquiryListItem]


class InquiryDetail(InquiryListItem):
    error_snapshot: str | None
    document: DocumentRef | None
    messages: list[MessageOut]
    is_author: bool
    has_admin_reply: bool
    can_edit: bool
    can_reply: bool
    can_delete: bool
