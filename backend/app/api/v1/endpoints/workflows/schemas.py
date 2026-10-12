"""워크플로우 API의 요청/응답 스키마."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class WorkflowCreate(BaseModel):
    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)
    kind: str = "ANALYSIS"

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, v: str) -> str:
        if v not in ("PREPROCESS", "ANALYSIS"):
            raise ValueError("kind must be one of PREPROCESS, ANALYSIS")
        return v


class WorkflowResponse(BaseModel):
    id: UUID
    project_id: UUID | None
    name: str
    description: str | None
    status: str
    kind: str
    created_at: datetime

    class Config:
        from_attributes = True


class WorkflowListItem(WorkflowResponse):
    updated_at: datetime
    # No separate updated_by column exists — created_by is the closest
    # attribution available and is shown as the list's "수정자" column.
    created_by_username: str | None
    # True for the single system-seeded PREPROCESS workflow every project falls
    # back to (project_id is None) — see _resolve_preprocess_version_id.
    is_system_default: bool
    # How many of this project's collections have their default_workflow_id
    # pinned to this workflow (documents.py's per-collection override, §2/§13).
    default_for_collection_count: int
    latest_version_number: int | None
    # Populated for the cross-project listing (project_id query param omitted)
    # so the UI can show a project badge per row; None for the system-default
    # workflow (project_id is None) and always populated for the single-project
    # listing too, for consistency.
    project_name: str | None = None


class WorkflowStatusUpdate(BaseModel):
    # 둘 다 선택값 — 이름만 바꾸는 요청과 상태만 바꾸는 기존 요청을 같은 엔드포인트로 받는다.
    status: str | None = None
    name: str | None = Field(None, min_length=1, max_length=200)


class WorkflowDuplicate(BaseModel):
    project_id: UUID


class BlockIn(BaseModel):
    # Client-generated id so a fresh (unsaved) edge can reference a fresh
    # (unsaved) block before either has a real server-assigned id.
    id: UUID | str | None = None
    block_type: str
    label: str | None = None
    position: dict = {}
    config: dict = {}


class EdgeIn(BaseModel):
    from_block_id: UUID | str
    to_block_id: UUID | str
    condition: dict | None = None


class GraphUpdate(BaseModel):
    blocks: list[BlockIn]
    edges: list[EdgeIn]


class VersionResponse(BaseModel):
    id: UUID
    workflow_id: UUID
    version_number: int
    published_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class RunCreate(BaseModel):
    version_id: UUID
    document_id: UUID | None = None
    collection_id: UUID | None = None


class RunResponse(BaseModel):
    id: UUID
    version_id: UUID
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    created_at: datetime

    class Config:
        from_attributes = True
