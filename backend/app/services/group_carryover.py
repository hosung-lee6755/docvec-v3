"""AD에서 다시 생긴 그룹이 예전 그룹의 문서 권한을 이어받게 한다.

같은 DN의 AD 그룹이 지워졌다 새 SID로 다시 생기면 디렉터리 동기화가 예전 그룹 행을 지우고
새 그룹에 `previous_group_id`를 남긴다(provisioning.sync_directory). 예전 그룹을 가리키는 문서
ACL 항목은 fail-closed로 남아 아무에게도 매칭되지 않는다. 이름이 같아도 구성원이 다를 수 있어
자동으로 옮기지 않고, 관리자가 목록을 보고 옮기거나(이어받기) 그대로 두기로(넘기기) 정한다.

원천 연결(파일 서버)에서 온 문서는 옮기지 않는다. 그 권한은 동기화가 파일 권한의 SID로 다시 건다.
"""
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.document import Document
from app.db.models.document_acl import DocumentAclEntry
from app.db.models.source_connector import SourceItem
from app.db.models.user import User
from app.db.models.user_group import UserGroup
from app.services.access_payload import sync_document_access
from app.services.audit import log_audit

PREVIEW_LIMIT = 20


def _previous_entries(previous_id):
    return (
        select(DocumentAclEntry.document_id)
        .where(DocumentAclEntry.principal_type == "group", DocumentAclEntry.principal_id == previous_id)
    )


def _connector_documents():
    return select(SourceItem.document_id).where(SourceItem.document_id.is_not(None))


async def _movable_document_ids(db: AsyncSession, previous_id) -> list[str]:
    rows = await db.scalars(
        _previous_entries(previous_id).where(DocumentAclEntry.document_id.not_in(_connector_documents()))
    )
    return [str(d) for d in rows.all()]


async def previous_permissions(db: AsyncSession, group: UserGroup) -> dict:
    """예전 그룹에 걸려 있던 문서 권한의 요약. 이어받을 것이 없으면 previous_group_id가 None이다."""
    if group.previous_group_id is None:
        return {"previous_group_id": None, "document_count": 0, "connector_document_count": 0, "documents": []}
    movable = await _movable_document_ids(db, group.previous_group_id)
    connector_count = await db.scalar(
        select(func.count()).select_from(
            _previous_entries(group.previous_group_id)
            .where(DocumentAclEntry.document_id.in_(_connector_documents())).subquery()
        )
    ) or 0
    preview = []
    if movable:
        rows = await db.execute(
            select(Document.id, Document.title, Document.original_filename)
            .where(Document.id.in_(movable[:PREVIEW_LIMIT]))
            .order_by(Document.original_filename)
        )
        preview = [{"id": str(i), "title": title or name} for i, title, name in rows.all()]
    return {
        "previous_group_id": str(group.previous_group_id),
        "document_count": len(movable),
        "connector_document_count": int(connector_count),
        "documents": preview,
    }


async def inherit_previous_permissions(db: AsyncSession, group: UserGroup, actor: User) -> dict:
    """예전 그룹의 문서 ACL 항목을 이 그룹으로 옮기고, 바뀐 문서의 검색 사본 권한을 맞춘다."""
    previous_id = group.previous_group_id
    doc_ids = await _movable_document_ids(db, previous_id)
    already = set()
    if doc_ids:
        already = {str(d) for d in (await db.scalars(
            select(DocumentAclEntry.document_id).where(
                DocumentAclEntry.principal_type == "group", DocumentAclEntry.principal_id == group.id,
                DocumentAclEntry.document_id.in_(doc_ids),
            )
        )).all()}
        for doc_id in doc_ids:
            if doc_id not in already:
                db.add(DocumentAclEntry(
                    document_id=doc_id, principal_type="group", principal_id=group.id, created_by=actor.id,
                ))
        await db.execute(
            delete(DocumentAclEntry).where(
                DocumentAclEntry.principal_type == "group", DocumentAclEntry.principal_id == previous_id,
                DocumentAclEntry.document_id.in_(doc_ids),
            )
        )
    group.previous_group_id = None
    log_audit(db, str(actor.id), "group.inherit_permissions", "group", str(group.id),
              detail={"previous_group_id": str(previous_id), "documents": len(doc_ids)})
    await db.commit()
    failed = await sync_document_access(db, doc_ids) if doc_ids else []
    return {"moved": len(doc_ids), "already_granted": len(already), "sync_failed": len(failed)}


async def dismiss_previous_permissions(db: AsyncSession, group: UserGroup, actor: User) -> None:
    """옮기지 않기로 했다. 예전 항목은 그대로 남아 아무에게도 매칭되지 않는다."""
    previous_id = group.previous_group_id
    group.previous_group_id = None
    log_audit(db, str(actor.id), "group.dismiss_previous_permissions", "group", str(group.id),
              detail={"previous_group_id": str(previous_id)})
    await db.commit()
