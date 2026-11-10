"""v3 권한 모델 관리 API 스키마 — 그룹, 문서 ACL, 보안등급."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SecurityLevel = Literal["Public", "Internal", "Confidential"]
PrincipalType = Literal["user", "group"]

# 한 문서의 허용 목록 상한 — 개인을 수백 명 나열하기보다 그룹으로 묶도록 유도하고,
# Qdrant 페이로드·필터 크기를 제한한다.
MAX_ACL_ENTRIES = 200


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)


class GroupUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)


class GroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    member_count: int = 0
    created_at: datetime


class GroupMemberAdd(BaseModel):
    user_id: UUID


class GroupMemberResponse(BaseModel):
    user_id: UUID
    email: str
    username: str
    added_at: datetime | None


class GroupDetailResponse(GroupResponse):
    members: list[GroupMemberResponse] = []


class AclEntryIn(BaseModel):
    principal_type: PrincipalType
    principal_id: UUID


class DocumentAclUpdate(BaseModel):
    """문서 허용 목록 전체 교체. 빈 목록 = 제한 없음(컬렉션 권한·보안등급만 적용)."""

    entries: list[AclEntryIn] = Field(default_factory=list, max_length=MAX_ACL_ENTRIES)


class AclEntryOut(BaseModel):
    principal_type: PrincipalType
    principal_id: UUID
    # 사용자는 username, 그룹은 그룹명. 삭제된 사용자는 None(항목은 제한 유지를 위해 남긴다).
    display_name: str | None


class DocumentAclResponse(BaseModel):
    document_id: UUID
    security_level: SecurityLevel | None
    # 문서 등급 → 컬렉션 기본 등급 → Public 순으로 정해진 실제 적용 등급
    effective_security_level: SecurityLevel
    restricted: bool
    entries: list[AclEntryOut]
