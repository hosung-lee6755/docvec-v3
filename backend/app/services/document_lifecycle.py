"""문서 버전과 수명주기(v3 마일스톤 7, .claude/plans/m7-data-lifecycle.plan.md).

한 문서의 버전들은 lineage_id를 공유한다. 상태는 다음처럼 바뀐다.
  - 첫 버전: current로 시작한다(지금까지와 같다).
  - 새 버전: pending으로 시작하고, 처리가 끝나 INDEXED가 되는 순간 current가 되며 같은 계보의
    current를 superseded로 바꾼다(promote_pending_version_sync). 처리에 실패하면 이전 버전이 계속
    현재 버전이다. 번호가 더 큰 버전이 이미 현재 버전이면 늦게 끝난 옛 버전은 바로 이전 버전이 된다.
  - 보관(archived): 사람이 하거나 만료일이 지나면 된다. 검색에서 빠지고 다시 꺼낼 수 있다.
  - 되돌리기: 이전 버전이나 보관 문서를 current로 만들고 같은 계보의 current를 superseded로 바꾼다.

권한(보안등급, ACL)은 계보 전체가 같은 값을 가진다. 새 버전은 이전 버전의 권한을 물려받고, 권한 변경은
모든 버전에 적용한다(copy_access). 그래야 되돌리기나 삭제 뒤 승격이 더 느슨한 옛 권한을 되살리지 않는다.

이전 버전의 벡터는 지우지 않는다. 검색에서는 Qdrant 페이로드의 lifecycle과 Postgres 재확인
(access_policy.can_retrieve)으로 빠지고, 되돌리기는 재처리 없이 상태만 바꾼다. 상태 전환은 계보의 행을
잠근 뒤에 하고, 계보마다 현재 버전이 하나뿐이라는 조건은 부분 유일 인덱스가 지킨다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import delete, exists, func, select, update

from app.db.models.document import Document
from app.db.models.document_acl import DocumentAclEntry
from app.services.access_policy import (
    LIFECYCLE_ARCHIVED,
    LIFECYCLE_CURRENT,
    LIFECYCLE_PENDING,
    LIFECYCLE_SUPERSEDED,
    can_view,
    load_document_facts,
)

logger = logging.getLogger(__name__)

RESTORABLE_STATES = (LIFECYCLE_SUPERSEDED, LIFECYCLE_ARCHIVED)
# 페이로드 동기화가 실패한 문서를 다시 맞추기까지 기다리는 시간(초)
PAYLOAD_RETRY_DELAY_SECONDS = 60


class LifecycleError(ValueError):
    """지금 상태에서 할 수 없는 수명주기 조작."""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 계보 조회와 잠금
# ---------------------------------------------------------------------------

def _lock_lineage_stmt(lineage_id):
    """같은 계보의 상태 전환을 줄 세운다. 두 워커가 동시에 승격하거나 되돌리기와 승격이 겹쳐도
    한쪽이 끝난 뒤에 다른 쪽이 커밋된 상태를 보고 판단한다."""
    return select(Document.id).where(Document.lineage_id == lineage_id).with_for_update()


def _newer_current_stmt(doc: Document):
    return select(
        exists().where(
            Document.lineage_id == doc.lineage_id,
            Document.id != doc.id,
            Document.lifecycle_state == LIFECYCLE_CURRENT,
            Document.version_number > doc.version_number,
        )
    )


def _connector_lineage_stmt(lineage_id):
    from app.db.models.source_connector import SourceItem

    return select(
        exists().where(
            SourceItem.document_id.in_(select(Document.id).where(Document.lineage_id == lineage_id))
        )
    )


async def is_connector_lineage(db, lineage_id) -> bool:
    """원천 커넥터가 관리하는 문서의 계보인가. 그런 계보는 사람이 버전·수명주기를 바꾸지 않는다."""
    return bool(await db.scalar(_connector_lineage_stmt(lineage_id)))


async def lineage_documents(db, lineage_id) -> list[Document]:
    """같은 계보의 모든 버전. 현재 버전을 맨 뒤에 둔다 — 차례로 지울 때 현재 버전을 먼저 지우면
    삭제 뒤 승격이 이전 버전을 현재 버전으로 올려 버린다."""
    docs = (await db.scalars(select(Document).where(Document.lineage_id == lineage_id))).all()
    return sorted(docs, key=lambda d: (d.lifecycle_state == LIFECYCLE_CURRENT, d.version_number))


async def lineage_siblings(db, doc: Document) -> list[Document]:
    return [d for d in await lineage_documents(db, doc.lineage_id) if d.id != doc.id]


async def copy_access(db, source: Document, targets: list[Document]) -> None:
    """source의 보안등급과 ACL을 targets에 그대로 건다. 커밋은 호출하는 쪽이 한다."""
    if not targets:
        return
    rows = (
        await db.scalars(select(DocumentAclEntry).where(DocumentAclEntry.document_id == source.id))
    ).all()
    for target in targets:
        await db.execute(delete(DocumentAclEntry).where(DocumentAclEntry.document_id == target.id))
        db.add_all([
            DocumentAclEntry(
                document_id=target.id, principal_type=r.principal_type, principal_id=r.principal_id,
                created_by=r.created_by,
            )
            for r in rows
        ])
        target.security_level = source.security_level


# ---------------------------------------------------------------------------
# 새 버전 판정(업로드, API async 세션)
# ---------------------------------------------------------------------------

def _latest_by_filename_stmt(collection_id, original_filename: str):
    return (
        select(Document)
        .where(Document.collection_id == collection_id, Document.original_filename == original_filename)
        .order_by(Document.version_number.desc(), Document.created_at.desc())
        .limit(1)
    )


def _next_version_stmt(lineage_id):
    return select(func.coalesce(func.max(Document.version_number), 0)).where(Document.lineage_id == lineage_id)


async def new_version_fields(db, ctx, collection_id, original_filename: str) -> tuple[dict, Document | None]:
    """같은 컬렉션에 같은 원본 파일명의 문서가 있으면 (그 계보의 다음 버전 필드, 이전 버전)을 돌려준다.

    다음 경우에는 새 버전으로 잇지 않고 별개 문서로 둔다({}, None).
      - 올리는 사람이 이전 버전을 볼 수 없다. 볼 수 없는 문서를 새 내용으로 밀어내 검색에서 빼는 일을 막는다.
      - 이전 버전이 원천 커넥터가 관리하는 문서다. 원천에서 사라지면 계보 전체가 지워지기 때문이다.
    새 버전은 이전 버전의 보안등급과 ACL을 물려받아야 한다(호출하는 쪽이 copy_access를 부른다).
    """
    if collection_id is None:
        return {}, None
    parent = await db.scalar(_latest_by_filename_stmt(collection_id, original_filename))
    if parent is None:
        return {}, None
    facts = (await load_document_facts(db, [str(parent.id)])).get(str(parent.id))
    if facts is None or not can_view(ctx, facts) or await is_connector_lineage(db, parent.lineage_id):
        return {}, None
    next_version = (await db.scalar(_next_version_stmt(parent.lineage_id)) or 0) + 1
    fields = {
        "lineage_id": parent.lineage_id,
        "version_number": next_version,
        "lifecycle_state": LIFECYCLE_PENDING,
        "security_level": parent.security_level,
    }
    return fields, parent


async def next_version_fields(db, lineage_id) -> dict:
    """커넥터(같은 원천 경로의 내용 변경)용. 권한은 원천 ACL이 정하므로 따로 보지 않는다."""
    next_version = (await db.scalar(_next_version_stmt(lineage_id)) or 0) + 1
    return {"lineage_id": lineage_id, "version_number": next_version, "lifecycle_state": LIFECYCLE_PENDING}


# ---------------------------------------------------------------------------
# 상태 전환 — 반환값은 Qdrant 페이로드를 다시 맞춰야 할 문서 id 목록이다
# ---------------------------------------------------------------------------

def _supersede_others_stmt(doc: Document):
    return (
        update(Document)
        .where(
            Document.lineage_id == doc.lineage_id,
            Document.id != doc.id,
            Document.lifecycle_state == LIFECYCLE_CURRENT,
        )
        .values(lifecycle_state=LIFECYCLE_SUPERSEDED)
        .returning(Document.id)
        .execution_options(synchronize_session=False)
    )


async def restore_version(db, doc: Document) -> list[str]:
    """이전 버전이나 보관 문서를 현재 버전으로 만든다. 커밋은 호출하는 쪽이 한다."""
    await db.execute(_lock_lineage_stmt(doc.lineage_id))
    await db.refresh(doc)
    if doc.lifecycle_state not in RESTORABLE_STATES:
        raise LifecycleError("이전 버전이나 보관된 문서만 현재 버전으로 되돌릴 수 있습니다")
    if doc.status != "INDEXED":
        raise LifecycleError("처리가 끝난(INDEXED) 버전만 현재 버전으로 되돌릴 수 있습니다")
    superseded = [str(i) for i in (await db.scalars(_supersede_others_stmt(doc))).all()]
    doc.lifecycle_state = LIFECYCLE_CURRENT
    doc.archived_at = None
    if doc.expires_at is not None and _as_aware(doc.expires_at) <= datetime.now(timezone.utc):
        # 만료로 보관된 문서를 꺼내면 만료일도 지운다. 그대로 두면 다음 점검에서 바로 다시 보관된다
        doc.expires_at = None
    return [str(doc.id), *superseded]


async def archive_document(db, doc: Document) -> list[str]:
    await db.execute(_lock_lineage_stmt(doc.lineage_id))
    await db.refresh(doc)
    if doc.lifecycle_state != LIFECYCLE_CURRENT:
        raise LifecycleError("현재 버전만 보관할 수 있습니다")
    doc.lifecycle_state = LIFECYCLE_ARCHIVED
    doc.archived_at = _now()
    return [str(doc.id)]


async def promote_after_delete(db, lineage_id, deleted_state: str) -> list[str]:
    """현재 버전을 지웠으면 남은 이전 버전 가운데 가장 최근의 INDEXED 버전을 현재 버전으로 올린다.
    삭제를 커밋한 뒤에 부르고, 커밋은 호출하는 쪽이 한다. 권한은 계보 전체가 같아 그대로 둔다."""
    if deleted_state != LIFECYCLE_CURRENT:
        return []
    await db.execute(_lock_lineage_stmt(lineage_id))
    has_current = await db.scalar(
        select(exists().where(Document.lineage_id == lineage_id, Document.lifecycle_state == LIFECYCLE_CURRENT))
    )
    if has_current:
        return []
    successor = await db.scalar(
        select(Document)
        .where(
            Document.lineage_id == lineage_id,
            Document.lifecycle_state == LIFECYCLE_SUPERSEDED,
            Document.status == "INDEXED",
        )
        .order_by(Document.version_number.desc())
        .limit(1)
    )
    if successor is None:
        return []
    successor.lifecycle_state = LIFECYCLE_CURRENT
    return [str(successor.id)]


def promote_pending_version_sync(db, doc: Document) -> list[str]:
    """새 버전이 INDEXED가 된 순간 current로 올리고 같은 계보의 current를 superseded로 바꾼다.
    pending이 아니면 아무것도 하지 않는다(첫 버전, 재처리). 번호가 더 큰 버전이 이미 현재 버전이면
    이 버전은 늦게 끝난 옛 버전이므로 바로 superseded로 둔다. 커밋까지 한다."""
    if doc is None or doc.lifecycle_state != LIFECYCLE_PENDING:
        return []
    db.execute(_lock_lineage_stmt(doc.lineage_id))
    db.refresh(doc)
    if doc.lifecycle_state != LIFECYCLE_PENDING:
        db.commit()
        return []
    if db.scalar(_newer_current_stmt(doc)):
        doc.lifecycle_state = LIFECYCLE_SUPERSEDED
        db.commit()
        return [str(doc.id)]
    superseded = [str(i) for i in db.scalars(_supersede_others_stmt(doc)).all()]
    doc.lifecycle_state = LIFECYCLE_CURRENT
    db.commit()
    return [str(doc.id), *superseded]


def expire_due_documents_sync(db, now: datetime | None = None) -> list[Document]:
    """만료일이 지난 현재 버전을 보관하고 감사 로그를 남긴다. 커밋까지 하고 보관한 문서를 돌려준다."""
    from app.services.audit import log_audit

    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(tzinfo=None)
    due = db.scalars(
        select(Document).where(
            Document.lifecycle_state == LIFECYCLE_CURRENT,
            Document.expires_at.is_not(None),
            Document.expires_at <= moment,
        ).with_for_update(skip_locked=True)
    ).all()
    for doc in due:
        doc.lifecycle_state = LIFECYCLE_ARCHIVED
        doc.archived_at = moment
        log_audit(
            db, None, "document.expire", "document", str(doc.id),
            detail={"filename": doc.original_filename, "version": doc.version_number,
                    "expires_at": _as_aware(doc.expires_at).isoformat()},
        )
    if due:
        db.commit()
    return list(due)


# ---------------------------------------------------------------------------
# 후속 처리 — 페이로드 동기화와 골든 재평가 예약. 실패해도 상태 전환은 되돌리지 않는다
# ---------------------------------------------------------------------------

def _schedule_payload_retry(failed: list[str]) -> None:
    """Qdrant 사본이 늦으면 새 현재 버전이 검색에서 통째로 빠질 수 있어 다시 맞추기를 예약한다.
    그동안에도 Postgres 재확인이 정본이라 이전 버전이 답에 섞이지는 않는다."""
    if not failed:
        return
    try:
        from app.pipeline.tasks.golden_eval import resync_document_access

        resync_document_access.apply_async(args=[failed], countdown=PAYLOAD_RETRY_DELAY_SECONDS)
    except Exception:  # noqa: BLE001
        logger.warning("payload resync scheduling failed: documents=%s", failed, exc_info=True)


def after_transition_sync(db, document_ids: list[str], collection_id, trigger: str) -> None:
    """워커(sync 세션)용."""
    if not document_ids:
        return
    from app.services.access_payload import sync_document_access_sync
    from app.services.golden_eval import schedule_golden_eval_sync

    try:
        _schedule_payload_retry(sync_document_access_sync(db, document_ids))
    except Exception:  # noqa: BLE001
        logger.warning("lifecycle payload sync failed: documents=%s", document_ids, exc_info=True)
        _schedule_payload_retry(list(document_ids))
    if collection_id is not None:
        try:
            schedule_golden_eval_sync(db, str(collection_id), trigger)
        except Exception:  # noqa: BLE001
            logger.warning("golden eval scheduling failed: collection=%s", collection_id, exc_info=True)


async def after_transition(db, document_ids: list[str], collection_id, trigger: str) -> None:
    """API(async 세션)용."""
    if not document_ids:
        return
    from app.services.access_payload import sync_document_access
    from app.services.golden_eval import schedule_golden_eval

    try:
        _schedule_payload_retry(await sync_document_access(db, document_ids))
    except Exception:  # noqa: BLE001
        logger.warning("lifecycle payload sync failed: documents=%s", document_ids, exc_info=True)
        _schedule_payload_retry(list(document_ids))
    if collection_id is not None:
        try:
            await schedule_golden_eval(db, str(collection_id), trigger)
        except Exception:  # noqa: BLE001
            logger.warning("golden eval scheduling failed: collection=%s", collection_id, exc_info=True)


def promote_on_indexed_sync(db, doc: Document | None) -> None:
    """INDEXED가 되는 모든 지점(rag_store, 워크플로 완료, 레거시 처리)에서 부른다. 멱등이다."""
    if doc is None:
        return
    try:
        changed = promote_pending_version_sync(db, doc)
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.warning("new version promotion failed: document=%s", getattr(doc, "id", None), exc_info=True)
        return
    after_transition_sync(db, changed, doc.collection_id, "new_version")


def lineage_document_ids_sync(db, lineage_id) -> list[str]:
    return [str(i) for i in db.scalars(select(Document.id).where(Document.lineage_id == lineage_id)).all()]
