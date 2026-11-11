"""SMB 커넥터 동기화 엔진(v3 마일스톤 3).

원천 목록과 `source_items`(지난 동기화 상태)를 비교해 파일마다 하나를 고른다.
- 신규: 문서를 만들고 원천 권한을 ACL로 옮긴 뒤 전처리 워크플로우를 시작한다.
- 내용 변경: 기존 문서를 지우고 새로 만든다(버전 이력은 마일스톤 7).
- 권한만 변경: ACL과 등급, Qdrant 권한 사본만 고친다(재색인 없음).
- 원천 삭제: 문서를 지운다.
- 권한 표현 불가: 문서를 만들지 않는다. 이미 있으면 지우고 보류로 남긴다(fail-closed).

원천 입출력(목록, 권한, 내용 읽기)은 DB를 바꾸기 전에 끝낸다. 파일 하나의 읽기 오류는 그 파일만
오류로 남기고 다음 파일로 넘어간다. 목록을 못 읽으면 아무것도 지우지 않고 실행을 실패로 끝낸다.

문서 생성 뒤 처리 시작은 업로드와 같은 `_start_workflow_or_mark_failed`를, 삭제는 문서 삭제
엔드포인트를 그대로 쓴다. 문서의 업로더는 커넥터의 시스템 사용자라 삭제 권한 확인을 통과한다.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import posixpath
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.document import Document
from app.db.models.document_acl import DocumentAclEntry
from app.db.models.source_connector import (
    ITEM_ERROR,
    ITEM_HELD,
    ITEM_SKIPPED,
    ITEM_SYNCED,
    RUN_FAILED,
    RUN_PARTIAL,
    RUN_RUNNING,
    RUN_SUCCESS,
    ConnectorRun,
    SourceConnector,
    SourceItem,
)
from app.db.models.user import AUTH_SOURCE_LDAP, User
from app.db.models.user_group import GROUP_SOURCE_LDAP, UserGroup
from app.services.access_payload import sync_document_access
from app.services.access_policy import PRINCIPAL_GROUP, PRINCIPAL_USER
from app.services.connectors.acl_mapping import (
    DECISION_HELD,
    HOLD_NO_PRINCIPAL,
    AclDecision,
    SecurityDescriptorError,
    decide_acl,
    descriptor_hash,
    parse_security_descriptor,
)
from app.services.connectors.smb_client import RemoteFile, SourceClient

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = frozenset({".pdf", ".docx", ".hwp", ".hwpx"})
COUNT_KEYS = (
    "added", "content_changed", "acl_changed", "unchanged", "deleted", "held", "skipped", "deferred", "errors",
)
HOLD_BAD_DESCRIPTOR = "bad_descriptor"
# 이미 가져온 문서의 권한을 다시 읽지 못하면 옛 권한으로 계속 열어 두지 않고 내린다
HOLD_UNREADABLE_DESCRIPTOR = "descriptor_unreadable"
ERROR_ACCESS_SYNC = "access_sync_failed"
SKIP_TOO_LARGE = "too_large"


def level_for(rules: list | None, path: str) -> str | None:
    """경로 접두어 규칙 중 가장 긴 것을 고른다. 대소문자는 구분하지 않는다(Windows 경로)."""
    lowered = path.lower()
    best: tuple[int, str | None] = (-1, None)
    for rule in rules or []:
        prefix = str(rule.get("prefix", "")).strip().lower().lstrip("/")
        if lowered.startswith(prefix) and len(prefix) > best[0]:
            best = (len(prefix), rule.get("level"))
    return best[1]


def _supported(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in SUPPORTED_SUFFIXES


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class _Context:
    connector: SourceConnector
    service_user: User
    items: dict[str, SourceItem]
    sid_to_user: dict[str, str]
    sid_to_group: dict[str, str]
    ignored: frozenset[str]
    budget: int

    @classmethod
    async def load(cls, db: AsyncSession, connector: SourceConnector) -> "_Context":
        items = (await db.scalars(select(SourceItem).where(SourceItem.connector_id == connector.id))).all()
        users = await db.execute(
            select(User.external_id, User.id).where(
                User.auth_source == AUTH_SOURCE_LDAP, User.external_id.is_not(None)
            )
        )
        groups = await db.execute(
            select(UserGroup.external_id, UserGroup.id).where(
                UserGroup.source == GROUP_SOURCE_LDAP, UserGroup.external_id.is_not(None)
            )
        )
        return cls(
            connector=connector,
            service_user=await db.get(User, connector.service_user_id),
            items={i.path: i for i in items},
            sid_to_user={sid: str(uid) for sid, uid in users.all()},
            sid_to_group={sid: str(gid) for sid, gid in groups.all()},
            ignored=frozenset({connector.service_account_sid} - {None}),
            budget=max(0, connector.max_new_per_run or 0),
        )

    def decide(self, raw_descriptor: bytes) -> AclDecision:
        try:
            aces = parse_security_descriptor(raw_descriptor)
        except SecurityDescriptorError:
            return AclDecision(DECISION_HELD, reason=HOLD_BAD_DESCRIPTOR)
        return decide_acl(aces, sid_to_user=self.sid_to_user, sid_to_group=self.sid_to_group,
                          ignored_sids=self.ignored)

    def item(self, db: AsyncSession, path: str) -> SourceItem:
        item = self.items.get(path)
        if item is None:
            item = SourceItem(id=uuid4(), connector_id=self.connector.id, path=path, state=ITEM_SYNCED)
            db.add(item)
            self.items[path] = item
        return item


# -- 문서 조작 -----------------------------------------------------------------

def _acl_rows(document_id, decision: AclDecision) -> list[DocumentAclEntry]:
    rows = [DocumentAclEntry(document_id=document_id, principal_type=PRINCIPAL_USER, principal_id=u)
            for u in sorted(decision.users)]
    rows += [DocumentAclEntry(document_id=document_id, principal_type=PRINCIPAL_GROUP, principal_id=g)
             for g in sorted(decision.groups)]
    return rows


async def _create_document(db, ctx: _Context, path: str, content: bytes, decision: AclDecision,
                           level: str | None, item: SourceItem, remote: RemoteFile, sd_hash: str) -> Document:
    from app.api.v1.endpoints.documents import upload as upload_api
    from app.services.document_storage import release_original
    from app.services.storage import storage_service

    name = posixpath.basename(path)
    doc_id = uuid4()
    key = f"{doc_id}/{name}"
    content_type = upload_api._resolve_content_type(name, None)
    await asyncio.to_thread(storage_service.upload_file, settings.minio_bucket_originals, key, content, content_type)
    document = Document(
        id=doc_id, filename=name, original_filename=name, file_size=len(content), mime_type=content_type,
        file_hash=_sha256(content), minio_key=key, status="QUEUED", created_by=ctx.service_user.id,
        collection_id=ctx.connector.collection_id, security_level=level,
    )
    db.add(document)
    db.add_all(_acl_rows(doc_id, decision))  # 처리 시작 전에 권한을 같은 커밋으로 건다
    # 원천 항목 연결도 같은 커밋에 넣는다. 따로 커밋하면 그 사이에 멈췄을 때 어느 항목에도 묶이지 않은
    # 문서가 남아, 다음 실행이 중복 문서를 만들고 남은 문서는 옛 권한을 영영 유지한다.
    item.document_id, item.size, item.mtime, item.sd_hash = doc_id, remote.size, remote.mtime, sd_hash
    item.content_hash = document.file_hash
    _mark(item, ITEM_SYNCED)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        await release_original(db, storage_service, settings.minio_bucket_originals, key)
        raise
    await upload_api._start_workflow_or_mark_failed(db, document, None, False)
    return document


async def _remove_document(db, ctx: _Context, document_id) -> None:
    from app.api.v1.endpoints.documents import listing as listing_api

    if await db.get(Document, document_id) is not None:
        await listing_api.delete_document(UUID(str(document_id)), db, ctx.service_user)


async def _apply_access(db, document: Document, decision: AclDecision, level: str | None) -> None:
    await db.execute(delete(DocumentAclEntry).where(DocumentAclEntry.document_id == document.id))
    db.add_all(_acl_rows(document.id, decision))
    document.security_level = level
    await db.commit()
    await sync_document_access(db, [str(document.id)])


# -- 파일 한 개 ----------------------------------------------------------------

def _mark(item: SourceItem, state: str, reason: str | None = None, detail: dict | None = None) -> None:
    item.state, item.hold_reason, item.hold_detail = state, reason, detail
    item.last_seen_at = datetime.utcnow()


async def _sync_file(db, ctx: _Context, client: SourceClient, remote: RemoteFile, counts: dict) -> None:
    path = remote.path
    existing = ctx.items.get(path)
    document = await db.get(Document, existing.document_id) if existing and existing.document_id else None

    if remote.size > settings.max_upload_size_bytes:
        if document is not None:
            await _remove_document(db, ctx, document.id)
        item = ctx.item(db, path)
        item.document_id = None
        _mark(item, ITEM_SKIPPED, SKIP_TOO_LARGE)
        counts["skipped"] += 1
        await db.commit()
        return

    # 원천 입출력을 먼저 끝낸다. 실패하면 이 파일만 오류로 남긴다.
    content = None
    try:
        raw_descriptor = await asyncio.to_thread(client.read_security_descriptor, path)
    except Exception as exc:
        logger.warning("커넥터 권한 읽기 실패: connector=%s path=%s err=%s", ctx.connector.id, path, exc)
        if document is None:
            _mark(ctx.item(db, path), ITEM_ERROR, f"read_error:{type(exc).__name__}"[:255])
            counts["errors"] += 1
            await db.commit()
            return
        await _hold(db, ctx, path, remote, document, None, HOLD_UNREADABLE_DESCRIPTOR,
                    {"error": type(exc).__name__}, counts)
        return
    decision = ctx.decide(raw_descriptor)
    try:
        if decision.kind != DECISION_HELD:
            moved = existing is None or (existing.size, existing.mtime) != (remote.size, remote.mtime)
            if document is None and ctx.budget <= 0:
                counts["deferred"] += 1
                return
            if document is None or moved:
                content = await asyncio.to_thread(client.read_file, path, settings.max_upload_size_bytes)
    except Exception as exc:  # 원천 쪽 오류는 다양하다(SMB, 권한, 네트워크)
        logger.warning("커넥터 파일 읽기 실패: connector=%s path=%s err=%s", ctx.connector.id, path, exc)
        item = ctx.item(db, path)
        if document is not None and decision.kind != DECISION_HELD:
            # 내용은 못 읽었어도 권한은 읽었다. 좁아진 권한을 미루지 않고 바로 건다.
            level = level_for(ctx.connector.level_rules, path)
            sd_hash = descriptor_hash(raw_descriptor)
            if item.sd_hash != sd_hash or document.security_level != level:
                try:
                    await _apply_access(db, document, decision, level)
                    item.sd_hash = sd_hash
                except Exception:
                    logger.warning("커넥터 권한 사본 갱신 실패: connector=%s path=%s", ctx.connector.id, path)
        _mark(item, ITEM_ERROR, f"read_error:{type(exc).__name__}"[:255])
        counts["errors"] += 1
        await db.commit()
        return

    level = level_for(ctx.connector.level_rules, path)
    sd_hash = descriptor_hash(raw_descriptor)

    if decision.kind == DECISION_HELD:
        detail = {"unmapped_sids": list(decision.unmapped)} if decision.reason == HOLD_NO_PRINCIPAL else None
        await _hold(db, ctx, path, remote, document, sd_hash, decision.reason, detail, counts)
        return

    item = ctx.item(db, path)
    if document is None:
        await _create_document(db, ctx, path, content, decision, level, item, remote, sd_hash)
        ctx.budget -= 1
        counts["added"] += 1
        return
    if content is not None and _sha256(content) != existing.content_hash:
        await _remove_document(db, ctx, document.id)
        await _create_document(db, ctx, path, content, decision, level, item, remote, sd_hash)
        counts["content_changed"] += 1
        return
    if existing.sd_hash != sd_hash or document.security_level != level:
        try:
            await _apply_access(db, document, decision, level)
        except Exception as exc:  # Qdrant 사본 갱신 실패. Postgres 재확인이 누출을 막고 다음 실행이 다시 맞춘다
            logger.warning("커넥터 권한 사본 갱신 실패: connector=%s path=%s err=%s", ctx.connector.id, path, exc)
            _mark(item, ITEM_ERROR, ERROR_ACCESS_SYNC)  # sd_hash를 그대로 둬 다음 실행이 다시 시도한다
            counts["errors"] += 1
            await db.commit()
            return
        counts["acl_changed"] += 1
    else:
        counts["unchanged"] += 1

    item.document_id, item.size, item.mtime, item.sd_hash = document.id, remote.size, remote.mtime, sd_hash
    if content is not None:
        item.content_hash = _sha256(content)
    _mark(item, ITEM_SYNCED)
    await db.commit()


async def _hold(db, ctx: _Context, path: str, remote: RemoteFile, document: Document | None,
                sd_hash: str | None, reason: str, detail: dict | None, counts: dict) -> None:
    """원천 권한을 그대로 옮길 수 없으면 가져온 문서를 내리고 보류로 남긴다(fail-closed)."""
    if document is not None:
        await _remove_document(db, ctx, document.id)
    item = ctx.item(db, path)
    item.document_id, item.size, item.mtime = None, remote.size, remote.mtime
    if sd_hash is not None:
        item.sd_hash = sd_hash
    _mark(item, ITEM_HELD, reason, detail)
    counts["held"] += 1
    await db.commit()


async def _remove_vanished(db, ctx: _Context, seen: set[str], counts: dict) -> None:
    for path, item in list(ctx.items.items()):
        if path in seen:
            continue
        if item.document_id is not None:
            await _remove_document(db, ctx, item.document_id)
            counts["deleted"] += 1
        await db.delete(item)
        del ctx.items[path]
    await db.commit()


# -- 실행 ---------------------------------------------------------------------

async def _finish(db, connector_id, run_id, counts: dict, status: str, error: str | None) -> ConnectorRun:
    now = datetime.utcnow()
    await db.execute(
        update(ConnectorRun).where(ConnectorRun.id == run_id)
        .values(status=status, finished_at=now, counts=dict(counts), error_message=error)
    )
    await db.execute(
        update(SourceConnector).where(SourceConnector.id == connector_id)
        .values(last_sync_at=now, last_status=status)
    )
    await db.commit()
    run = await db.get(ConnectorRun, run_id)
    await db.refresh(run)
    return run


async def run_connector_sync(db: AsyncSession, connector: SourceConnector, client: SourceClient, *,
                             triggered_by: str | None = None) -> ConnectorRun:
    connector_id = connector.id
    # 이 함수는 커넥터 락을 잡은 채로만 불린다. 남아 있는 running 기록은 끊긴 이전 실행이다.
    await db.execute(
        update(ConnectorRun).where(ConnectorRun.connector_id == connector_id, ConnectorRun.status == RUN_RUNNING)
        .values(status=RUN_FAILED, finished_at=datetime.utcnow(), error_message="작업이 중간에 끊겼습니다")
    )
    run = ConnectorRun(id=uuid4(), connector_id=connector_id, status=RUN_RUNNING, counts={},
                       triggered_by=triggered_by, started_at=datetime.utcnow())
    db.add(run)
    await db.commit()
    run_id = run.id
    counts = dict.fromkeys(COUNT_KEYS, 0)

    try:
        remote = await asyncio.to_thread(lambda: list(client.list_files()))
    except Exception as exc:
        logger.warning("커넥터 목록 읽기 실패: connector=%s err=%s", connector_id, exc)
        return await _finish(db, connector_id, run_id, counts, RUN_FAILED,
                             f"원천 목록을 읽지 못했습니다({type(exc).__name__})")

    try:
        ctx = await _Context.load(db, connector)
        seen: set[str] = set()
        for remote_file in remote:
            if not _supported(remote_file.path):
                counts["skipped"] += 1
                continue
            seen.add(remote_file.path)
            await _sync_file(db, ctx, client, remote_file, counts)
        if not seen and any(i.document_id for i in ctx.items.values()):
            # 하위 경로가 잘못됐거나 잠시 비어 보이는 경우일 수 있다. 가져온 문서를 한꺼번에 지우지 않는다.
            return await _finish(db, connector_id, run_id, counts, RUN_FAILED,
                                 "원천에서 파일을 하나도 찾지 못해 삭제를 멈췄습니다. 하위 경로와 권한을 확인하세요.")
        await _remove_vanished(db, ctx, seen, counts)
    except Exception as exc:
        logger.exception("커넥터 동기화 중단: connector=%s", connector_id)
        await db.rollback()
        return await _finish(db, connector_id, run_id, counts, RUN_FAILED,
                             f"동기화가 중간에 멈췄습니다({type(exc).__name__})")

    status = RUN_PARTIAL if counts["errors"] else RUN_SUCCESS
    return await _finish(db, connector_id, run_id, counts, status, None)
