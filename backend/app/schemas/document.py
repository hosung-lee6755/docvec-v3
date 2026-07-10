from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentUploadResponse(BaseModel):
    id: UUID
    filename: str
    status: str
    created_at: datetime


class DocumentResponse(BaseModel):
    id: UUID
    filename: str
    original_filename: str
    file_size: int
    mime_type: str
    status: str
    collection_id: UUID | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    error_message: str | None
    parsed_text: str | None
    ocr_used: bool
    summary: str | None
    summary_status: str
    tags: list[str] | None = None

    class Config:
        from_attributes = True


class DocumentProceedRequest(BaseModel):
    edited_text: str | None = Field(None, max_length=200_000)


class DocumentReprocessRequest(BaseModel):
    edited_text: str = Field(..., max_length=200_000)


class DocumentListResponse(BaseModel):
    total: int
    page: int
    limit: int
    items: list[DocumentResponse]


class DocumentChunkItem(BaseModel):
    chunk_index: int
    text: str


class DocumentContentResponse(BaseModel):
    document_id: str
    chunks: list[DocumentChunkItem]
    full_text: str
    chunk_count: int = 0


class DocumentDownloadResponse(BaseModel):
    url: str


class DocumentTableItem(BaseModel):
    page_number: int
    rows: list[list[str]]


class DocumentTablesResponse(BaseModel):
    document_id: str
    tables: list[DocumentTableItem]


class DocumentImageItem(BaseModel):
    page_number: int
    text: str
    url: str


class DocumentImagesResponse(BaseModel):
    document_id: str
    images: list[DocumentImageItem]


class DocumentChunkDetail(BaseModel):
    id: str
    chunk_index: int
    text: str
    page_number: int | None = None
    disabled: bool = False
    edited: bool = False
    hit_count: int = 0


class DocumentChunksResponse(BaseModel):
    document_id: str
    chunks: list[DocumentChunkDetail]


class ChunkUpdateRequest(BaseModel):
    text: str | None = Field(None, min_length=1, max_length=20_000)
    disabled: bool | None = None


class DocumentRevisionItem(BaseModel):
    id: UUID
    source: str
    created_by: UUID | None
    created_at: datetime
    text_length: int
    preview: str


class DocumentRevisionsResponse(BaseModel):
    document_id: str
    revisions: list[DocumentRevisionItem]


class DocumentTagsUpdateRequest(BaseModel):
    tags: list[str] = Field(..., max_length=20)
