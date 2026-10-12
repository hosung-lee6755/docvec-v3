from datetime import datetime
from uuid import UUID

from app.api.v1.deps import get_current_user, require_admin
from app.api.v1.endpoints.documents.processing import _resolve_display_run_id
from app.api.v1.permissions import (
    check_document_access,
)
from app.db.models.document import Document
from app.db.models.processing_job import ProcessingJob
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.document import (
    CleaningChangesResponse,
    DictionaryApplicationItem,
    DictionaryApplicationsResponse,
    DocumentContentResponse,
    DocumentTablesResponse,
    PiiDetectionItem,
    PiiDetectionsResponse,
)
from app.schemas.processing_job import ProcessingJobListResponse
from app.services.audit import log_audit
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()
# normalization_blocks.py::TextCleanBlock._apply()가 내장 규칙에 붙이는
# "builtin:xxx" 키 -> 한글 라벨. CleaningRule 테이블에 행이 없는 내장 규칙은
# rule_name 조인이 항상 NULL이라, 이 매핑이 없으면 프런트에 원문 rule_key(영어)가
# 그대로 노출된다.
_BUILTIN_RULE_LABELS: dict[str, str] = {
    "builtin:control_chars": "제어문자 제거",
    "builtin:unicode_nfc": "유니코드 정규화(NFC)",
    "builtin:quotes": "따옴표 정규화",
    "builtin:width": "전각→반각 변환",
    "builtin:ocr_fix": "OCR 오류 보정(줄바꿈 하이픈 결합)",
    "builtin:whitespace": "공백·빈 줄 정리",
    "builtin:repeated_headers": "반복 머리말 제거",
}




def _resolve_cleaning_rule_name(rule_name: str | None, rule_key: str | None) -> str | None:
    """CleaningRule 조인 결과(커스텀 규칙, 이미 한글)를 우선하고, 없으면 내장
    규칙 한글 라벨로, 그마저 없으면(알 수 없는 rule_key) 원문을 그대로 반환한다."""
    if rule_name:
        return rule_name
    if rule_key:
        return _BUILTIN_RULE_LABELS.get(rule_key, rule_key)
    return None


@router.get("/{document_id}/cleaning-changes", response_model=CleaningChangesResponse)
async def list_cleaning_changes(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.db.models.cleaning_rule import CleaningChange, CleaningRule

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")

    run_id = await _resolve_display_run_id(db, doc)
    items: list[dict] = []
    if run_id:
        rows = (
            await db.execute(
                select(CleaningChange, CleaningRule.rule_name)
                .outerjoin(CleaningRule, CleaningChange.rule_id == CleaningRule.id)
                .where(CleaningChange.run_id == run_id)
                .order_by(CleaningChange.created_at.asc())
            )
        ).all()
        for change, rule_name in rows:
            items.append({
                "id": change.id,
                "rule_id": change.rule_id,
                "rule_key": change.rule_key,
                "rule_name": _resolve_cleaning_rule_name(rule_name, change.rule_key),
                "node_id": change.node_id,
                "before_sample": change.before_sample,
                "after_sample": change.after_sample,
                "change_count": change.change_count,
                "sample_matches": change.sample_matches,
                "created_at": change.created_at,
            })

    distinct_rules = {(item["rule_id"], item["rule_key"]) for item in items}
    return {
        "document_id": str(document_id),
        "run_id": run_id,
        "total_changes": sum(item["change_count"] for item in items),
        "distinct_rule_count": len(distinct_rules),
        "changes": items,
    }


@router.get("/{document_id}/dictionary-applications", response_model=DictionaryApplicationsResponse)
async def list_dictionary_applications(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.db.models.dictionary_application import DictionaryApplication

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")

    run_id = await _resolve_display_run_id(db, doc)
    applications = []
    if run_id:
        applications = (
            await db.scalars(
                select(DictionaryApplication)
                .where(DictionaryApplication.run_id == run_id)
                .order_by(DictionaryApplication.created_at.asc())
            )
        ).all()
    pending_revert_count = sum(1 for app_row in applications if app_row.reverted)
    return {
        "document_id": str(document_id),
        "run_id": run_id,
        "pending_revert_count": pending_revert_count,
        "applications": applications,
    }


@router.post(
    "/{document_id}/dictionary-applications/{app_id}/revert",
    response_model=DictionaryApplicationItem,
)
async def revert_dictionary_application(
    document_id: UUID,
    app_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.db.models.dictionary_application import DictionaryApplication

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    application = await db.scalar(
        select(DictionaryApplication).where(
            DictionaryApplication.id == app_id,
            DictionaryApplication.document_id == document_id,
        )
    )
    if not application:
        raise HTTPException(status_code=404, detail="Dictionary application not found")

    application.reverted = True
    await db.commit()
    await db.refresh(application)
    return application


@router.get("/{document_id}/pii", response_model=PiiDetectionsResponse)
async def list_pii_detections(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.db.models.pii_detection import PiiDetection

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")

    run_id = await _resolve_display_run_id(db, doc)
    detections = []
    if run_id:
        detections = (
            await db.scalars(
                select(PiiDetection)
                .where(PiiDetection.run_id == run_id)
                .order_by(PiiDetection.created_at.asc())
            )
        ).all()
    return {"document_id": str(document_id), "run_id": run_id, "detections": detections}


@router.post("/{document_id}/pii/{detection_id}/approve", response_model=PiiDetectionItem)
async def approve_pii_detection(
    document_id: UUID,
    detection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    from app.db.models.pii_detection import PiiDetection

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    detection = await db.scalar(
        select(PiiDetection).where(
            PiiDetection.id == detection_id, PiiDetection.document_id == document_id
        )
    )
    if not detection:
        raise HTTPException(status_code=404, detail="PII detection not found")

    detection.approved_by = current_user.id
    detection.approved_at = datetime.utcnow()
    detection.rejected = False
    await db.commit()
    await db.refresh(detection)
    return detection


@router.post("/{document_id}/pii/{detection_id}/reject", response_model=PiiDetectionItem)
async def reject_pii_detection(
    document_id: UUID,
    detection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.db.models.pii_detection import PiiDetection

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    detection = await db.scalar(
        select(PiiDetection).where(
            PiiDetection.id == detection_id, PiiDetection.document_id == document_id
        )
    )
    if not detection:
        raise HTTPException(status_code=404, detail="PII detection not found")

    detection.rejected = True
    detection.approved_by = None
    detection.approved_at = None
    await db.commit()
    await db.refresh(detection)
    return detection


class PiiRevealResponse(BaseModel):
    value: str


@router.post("/{document_id}/pii/{detection_id}/reveal", response_model=PiiRevealResponse)
async def reveal_pii_detection(
    document_id: UUID,
    detection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """민감정보 원문 열람 — 문서별 editor 권한이 아니라 전역 admin 롤로 게이팅한다
    (9c에서 만든 목록/승인/반려 엔드포인트는 그대로 두고, 원문 노출만 별도 엔드포인트로
    분리해 PiiDetectionsResponse가 여전히 original_encrypted를 절대 반환하지 않는다는
    보안 보장을 유지한다). 모든 열람은 감사 로그에 남긴다."""
    from app.core import crypto
    from app.db.models.pii_detection import PiiDetection

    require_admin(current_user)

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    detection = await db.scalar(
        select(PiiDetection).where(
            PiiDetection.id == detection_id, PiiDetection.document_id == document_id
        )
    )
    if not detection:
        raise HTTPException(status_code=404, detail="PII detection not found")
    if not detection.original_encrypted:
        raise HTTPException(status_code=404, detail="원문이 저장되어 있지 않습니다")

    value = crypto.decrypt_secret(detection.original_encrypted)
    log_audit(
        db, str(current_user.id), "pii.reveal",
        resource_type="pii_detection", resource_id=str(detection_id),
    )
    await db.commit()
    return {"value": value}


@router.get("/{document_id}/jobs", response_model=ProcessingJobListResponse)
async def get_document_jobs(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")

    result = await db.execute(
        select(ProcessingJob)
        .where(ProcessingJob.document_id == document_id)
        .order_by(ProcessingJob.created_at.asc())
    )
    jobs = result.scalars().all()
    return {"items": jobs}


@router.get("/{document_id}/content", response_model=DocumentContentResponse)
async def get_document_content(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.document_service import get_document_content as fetch_content

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")
    return fetch_content(document_id)


@router.get("/{document_id}/tables", response_model=DocumentTablesResponse)
async def get_document_tables(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")
    return {"document_id": str(doc.id), "tables": doc.tables or []}



