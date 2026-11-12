"""문서 버전 이력과 수명주기 API(v3 마일스톤 7, services/document_lifecycle.py).

버전 목록과 비교는 열람 권한으로, 보관·되돌리기·만료일은 문서 편집 권한으로 한다.
"""
import asyncio
import difflib
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.api.v1.permissions import check_document_access
from app.db.models.document import Document
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.document import DocumentResponse
from app.services.access_policy import (
    build_access_context,
    is_lifecycle_active,
    load_document_facts,
    visible_document_ids,
)
from app.services.audit import log_audit
from app.services.document_lifecycle import (
    LifecycleError,
    after_transition,
    archive_document,
    is_connector_lineage,
    restore_version,
)


router = APIRouter()

# 비교 상한. 본문이 아주 길면 앞부분만 비교하고 잘렸다고 알린다. difflib은 최악의 경우
# 줄 수의 제곱에 비례하므로 줄 수와 줄 길이를 모두 묶고, 이벤트 루프 밖에서 돌린다.
_MAX_COMPARE_INPUT_LINES = 5000
_MAX_COMPARE_LINE_CHARS = 1000
_MAX_DIFF_LINES = 2000
_COMPARE_RATE_LIMIT = 20
_COMPARE_RATE_WINDOW_SECONDS = 60
_CONNECTOR_LIFECYCLE_DETAIL = "파일 서버에서 가져온 문서입니다. 버전과 보관 상태는 파일 서버의 원본을 따릅니다."


class DocumentVersionItem(BaseModel):
    id: UUID
    version_number: int
    lifecycle_state: str
    status: str
    filename: str
    file_size: int
    created_at: datetime
    created_by: UUID | None
    expires_at: datetime | None
    archived_at: datetime | None
    # 지금 검색과 답변에 쓰이는가(현재 버전이고 만료되지 않음)
    is_retrievable: bool


class DocumentVersionsResponse(BaseModel):
    lineage_id: UUID
    items: list[DocumentVersionItem]


class VersionCompareResponse(BaseModel):
    base_id: UUID
    base_version: int
    target_id: UUID
    target_version: int
    added_lines: int
    removed_lines: int
    diff: list[str]
    truncated: bool


class ExpiryRequest(BaseModel):
    # 비우면 만료일을 지운다
    expires_at: datetime | None = None


async def _document_or_404(db: AsyncSession, document_id: UUID) -> Document:
    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/{document_id}/versions", response_model=DocumentVersionsResponse)
async def list_document_versions(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """같은 문서의 버전 이력. 볼 수 있는 버전만 돌려준다."""
    doc = await _document_or_404(db, document_id)
    await check_document_access(db, doc, current_user, min_role="viewer")
    versions = (
        await db.scalars(
            select(Document).where(Document.lineage_id == doc.lineage_id).order_by(Document.version_number.desc())
        )
    ).all()
    facts = await load_document_facts(db, [str(v.id) for v in versions])
    visible = visible_document_ids(await build_access_context(db, current_user), facts)
    items = [
        {
            "id": v.id, "version_number": v.version_number, "lifecycle_state": v.lifecycle_state,
            "status": v.status, "filename": v.original_filename, "file_size": v.file_size,
            "created_at": v.created_at, "created_by": v.created_by, "expires_at": v.expires_at,
            "archived_at": v.archived_at,
            "is_retrievable": str(v.id) in facts and is_lifecycle_active(facts[str(v.id)]),
        }
        for v in versions
        if str(v.id) in visible
    ]
    return {"lineage_id": doc.lineage_id, "items": items}


def _bounded_lines(text: str) -> tuple[list[str], bool]:
    lines = text.splitlines()
    truncated = len(lines) > _MAX_COMPARE_INPUT_LINES or any(len(x) > _MAX_COMPARE_LINE_CHARS for x in lines)
    return [x[:_MAX_COMPARE_LINE_CHARS] for x in lines[:_MAX_COMPARE_INPUT_LINES]], truncated


def _line_diff(base: str, target: str) -> tuple[list[str], int, int, bool]:
    base_lines, base_cut = _bounded_lines(base)
    target_lines, target_cut = _bounded_lines(target)
    truncated = base_cut or target_cut
    diff = list(difflib.unified_diff(
        base_lines, target_lines, fromfile="base", tofile="target", lineterm="", n=2,
    ))
    added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
    if len(diff) > _MAX_DIFF_LINES:
        diff, truncated = diff[:_MAX_DIFF_LINES], True
    return diff, added, removed, truncated


@router.get("/{document_id}/versions/compare", response_model=VersionCompareResponse)
async def compare_document_versions(
    document_id: UUID,
    other_id: UUID = Query(..., description="비교할 다른 버전. 같은 문서의 버전이어야 한다"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """두 버전의 본문(처리된 텍스트)을 줄 단위로 비교한다. 번호가 작은 버전이 기준이다."""
    from app.core.rate_limit import enforce_user_rate_limit

    enforce_user_rate_limit(
        str(current_user.id), "version_compare", limit=_COMPARE_RATE_LIMIT,
        window_seconds=_COMPARE_RATE_WINDOW_SECONDS,
    )
    doc = await _document_or_404(db, document_id)
    other = await _document_or_404(db, other_id)
    await check_document_access(db, doc, current_user, min_role="viewer")
    await check_document_access(db, other, current_user, min_role="viewer")
    if doc.lineage_id != other.lineage_id:
        raise HTTPException(status_code=400, detail="같은 문서의 버전끼리만 비교할 수 있습니다")
    base, target = sorted((doc, other), key=lambda d: d.version_number)
    diff, added, removed, truncated = await asyncio.to_thread(
        _line_diff, base.parsed_text or "", target.parsed_text or ""
    )
    return {
        "base_id": base.id, "base_version": base.version_number,
        "target_id": target.id, "target_version": target.version_number,
        "added_lines": added, "removed_lines": removed, "diff": diff, "truncated": truncated,
    }


async def _ensure_not_connector(db, doc: Document) -> None:
    """원천 커넥터가 관리하는 문서는 원천이 상태를 정한다. 사람이 보관·되돌리기·만료를 바꾸지 않는다."""
    if await is_connector_lineage(db, doc.lineage_id):
        raise HTTPException(status_code=409, detail=_CONNECTOR_LIFECYCLE_DETAIL)


async def _transition(db, doc: Document, user: User, action: str, change) -> Document:
    await check_document_access(db, doc, user, min_role="editor")
    await _ensure_not_connector(db, doc)
    before = doc.lifecycle_state
    before_expiry = doc.expires_at
    try:
        changed = await change(db, doc)
    except LifecycleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    log_audit(
        db, str(user.id), action, "document", str(doc.id),
        detail={"filename": doc.original_filename, "version": doc.version_number, "from": before,
                "to": doc.lifecycle_state, "superseded": [i for i in changed if i != str(doc.id)],
                "cleared_expiry": before_expiry.isoformat() if before_expiry and not doc.expires_at else None},
    )
    await db.commit()
    await db.refresh(doc)
    await after_transition(db, changed, doc.collection_id, "lifecycle")
    return doc


@router.post("/{document_id}/archive", response_model=DocumentResponse)
async def archive(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """현재 버전을 보관한다. 검색과 답변에서 빠지고, 되돌리기로 다시 꺼낼 수 있다."""
    doc = await _document_or_404(db, document_id)
    return await _transition(db, doc, current_user, "document.archive", archive_document)


@router.post("/{document_id}/restore", response_model=DocumentResponse)
async def restore(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """이전 버전이나 보관 문서를 현재 버전으로 만든다. 같은 문서의 현재 버전은 이전 버전이 된다."""
    doc = await _document_or_404(db, document_id)
    return await _transition(db, doc, current_user, "document.restore_version", restore_version)


@router.put("/{document_id}/expiry", response_model=DocumentResponse)
async def set_expiry(
    document_id: UUID,
    body: ExpiryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """만료일을 정하거나 지운다. 만료일이 지나면 자동으로 보관된다(10분 간격 점검)."""
    doc = await _document_or_404(db, document_id)
    await check_document_access(db, doc, current_user, min_role="editor")
    await _ensure_not_connector(db, doc)
    expires_at = body.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=422, detail="만료일은 지금보다 뒤여야 합니다")
    previous = doc.expires_at
    doc.expires_at = expires_at
    log_audit(
        db, str(current_user.id), "document.set_expiry", "document", str(doc.id),
        detail={"filename": doc.original_filename,
                "from": previous.isoformat() if previous else None,
                "to": expires_at.isoformat() if expires_at else None},
    )
    await db.commit()
    await db.refresh(doc)
    return doc
