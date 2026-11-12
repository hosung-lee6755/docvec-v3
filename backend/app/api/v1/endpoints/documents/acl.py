"""문서 접근 허용 목록(ACL) 조회·교체 — v3 권한 모델.

목록이 비어 있으면 제한 없음(컬렉션 권한·보안등급만 적용), 항목이 있으면 목록의
사용자·그룹과 업로더 본인만 볼 수 있다. 조회·수정 모두 문서 editor 권한이 필요하다 —
누가 볼 수 있는지 자체도 관리 정보이기 때문이다.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.access_sync import sync_access_or_502
from app.api.v1.deps import get_current_user
from app.api.v1.permissions import check_document_access
from app.db.models.document import Document
from app.db.models.document_acl import DocumentAclEntry
from app.db.models.user import User
from app.db.models.user_group import UserGroup
from app.db.session import get_db
from app.schemas.access import AclEntryOut, DocumentAclResponse, DocumentAclUpdate
from app.services.access_policy import (
    PRINCIPAL_GROUP,
    PRINCIPAL_USER,
    SECURITY_LEVELS,
    effective_level_rank,
    RELAX_FORBIDDEN_DETAIL,
    can_relax_document,
    is_relaxing_acl,
    load_document_facts,
)
from app.services.audit import log_audit
from app.services.document_lifecycle import copy_access, lineage_siblings
from app.services.source_locks import ensure_not_connector_document, is_connector_document

router = APIRouter()


async def _get_editable_document(db: AsyncSession, document_id: UUID, user: User) -> Document:
    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, user, min_role="editor")
    return doc


async def _display_names(
    db: AsyncSession, entries: list[DocumentAclEntry]
) -> dict[tuple[str, str], str]:
    user_ids = [e.principal_id for e in entries if e.principal_type == PRINCIPAL_USER]
    group_ids = [e.principal_id for e in entries if e.principal_type == PRINCIPAL_GROUP]
    names: dict[tuple[str, str], str] = {}
    if user_ids:
        rows = await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))
        for uid, username in rows.all():
            names[(PRINCIPAL_USER, str(uid))] = username
    if group_ids:
        rows = await db.execute(
            select(UserGroup.id, UserGroup.name).where(UserGroup.id.in_(group_ids))
        )
        for gid, name in rows.all():
            names[(PRINCIPAL_GROUP, str(gid))] = name
    return names


async def _acl_response(db: AsyncSession, doc: Document, user: User) -> DocumentAclResponse:
    entries = (
        await db.scalars(
            select(DocumentAclEntry)
            .where(DocumentAclEntry.document_id == doc.id)
            .order_by(DocumentAclEntry.principal_type, DocumentAclEntry.created_at)
        )
    ).all()
    names = await _display_names(db, list(entries))
    facts = (await load_document_facts(db, [str(doc.id)]))[str(doc.id)]
    return DocumentAclResponse(
        document_id=doc.id,
        security_level=doc.security_level,
        effective_security_level=SECURITY_LEVELS[effective_level_rank(facts)],
        restricted=bool(entries),
        can_relax=await can_relax_document(db, user, doc),
        source_managed=await is_connector_document(db, doc.id),
        entries=[
            AclEntryOut(
                principal_type=e.principal_type,
                principal_id=e.principal_id,
                display_name=names.get((e.principal_type, str(e.principal_id))),
            )
            for e in entries
        ],
    )


async def _validate_principals(db: AsyncSession, keys: set[tuple[str, str]]) -> None:
    """존재하지 않는 사용자·그룹을 넣으면 400 — 오타로 아무도 못 보는 문서가 생기지 않게."""
    user_ids = {pid for ptype, pid in keys if ptype == PRINCIPAL_USER}
    group_ids = {pid for ptype, pid in keys if ptype == PRINCIPAL_GROUP}
    found: set[str] = set()
    if user_ids:
        stmt = select(User.id).where(User.id.in_(user_ids))
        found |= {str(u) for u in (await db.scalars(stmt)).all()}
    if group_ids:
        stmt = select(UserGroup.id).where(UserGroup.id.in_(group_ids))
        found |= {str(g) for g in (await db.scalars(stmt)).all()}
    missing = sorted((user_ids | group_ids) - found)
    if missing:
        raise HTTPException(
            status_code=400, detail=f"존재하지 않는 사용자 또는 그룹입니다: {', '.join(missing)}"
        )


@router.get("/{document_id}/acl", response_model=DocumentAclResponse)
async def get_document_acl(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = await _get_editable_document(db, document_id, current_user)
    return await _acl_response(db, doc, current_user)


@router.put("/{document_id}/acl", response_model=DocumentAclResponse)
async def replace_document_acl(
    document_id: UUID,
    body: DocumentAclUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """허용 목록 전체 교체. 빈 목록을 보내면 제한을 해제한다."""
    doc = await _get_editable_document(db, document_id, current_user)
    await ensure_not_connector_document(db, doc.id)

    new_keys = {(e.principal_type, str(e.principal_id)) for e in body.entries}
    await _validate_principals(db, new_keys)

    old_entries = (
        await db.scalars(select(DocumentAclEntry).where(DocumentAclEntry.document_id == doc.id))
    ).all()
    old_keys = {(e.principal_type, str(e.principal_id)) for e in old_entries}
    if is_relaxing_acl(old_keys, new_keys) and not await can_relax_document(db, current_user, doc):
        # v3 마일스톤 2: 제한 해제·허용 대상 추가는 업로더·컬렉션 소유자만 할 수 있다.
        raise HTTPException(status_code=403, detail=RELAX_FORBIDDEN_DETAIL)

    if new_keys != old_keys:
        await db.execute(delete(DocumentAclEntry).where(DocumentAclEntry.document_id == doc.id))
        for ptype, pid in sorted(new_keys):
            db.add(
                DocumentAclEntry(
                    document_id=doc.id, principal_type=ptype, principal_id=pid,
                    created_by=str(current_user.id),
                )
            )
        # 같은 계보의 다른 버전에도 똑같이 건다. 한 버전만 바꾸면 되돌리기·승격 때 예전 권한이 되살아난다.
        siblings = await lineage_siblings(db, doc)
        await db.flush()
        await copy_access(db, doc, siblings)
        log_audit(
            db, str(current_user.id), "document.acl_update", "document", str(doc.id),
            detail={
                "added": [f"{t}:{i}" for t, i in sorted(new_keys - old_keys)],
                "removed": [f"{t}:{i}" for t, i in sorted(old_keys - new_keys)],
                "restricted": bool(new_keys),
                "versions": len(siblings) + 1,
            },
        )
        await db.commit()
        await sync_access_or_502(db, [doc.id, *(s.id for s in siblings)], "허용 목록")

    return await _acl_response(db, doc, current_user)
