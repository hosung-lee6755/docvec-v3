"""문서 원천 연결(SMB 커넥터) 관리 API(v3 마일스톤 3). 관리자 전용.

비밀번호는 암호문으로만 저장하고 어떤 응답에도 넣지 않는다. 생성, 수정, 삭제, 즉시 동기화는
감사 로그에 남는다. 커넥터를 지우면 그 커넥터가 만든 문서도 함께 지운다(원천 권한으로 관리되던
문서를 관리 주체 없이 남기지 않기 위해서다). 커넥터의 시스템 계정은 다른 기록이 참조할 수 있어
지우지 않고 비활성으로 남긴다.
"""
import asyncio
import re
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, require_admin
from app.core.crypto import encrypt_secret
from app.db.models.collection import Collection
from app.db.models.source_connector import ITEM_ERROR, ITEM_HELD, ConnectorRun, SourceConnector, SourceItem
from app.db.models.user import User
from app.db.session import get_db
from app.services.access_policy import SECURITY_LEVELS
from app.services.audit import log_audit
from app.services.connectors.registry import new_service_user
from app.services.sync_lock import connector_lock_key, held_lock

router = APIRouter()

_HOST_RE = re.compile(r"^[A-Za-z0-9.\-]{1,255}$")
_SHARE_RE = re.compile(r"^[^\\/:*?\"<>|\x00]{1,80}$")
_SID_RE = re.compile(r"^S-1-\d+(-\d+){1,14}$")
_RECENT_RUNS = 10
_MAX_LISTED_ITEMS = 200


def _check_sid(value: str | None) -> str | None:
    if value and not _SID_RE.match(value):
        raise ValueError("SID 형식이 아닙니다")
    return value or None


class LevelRule(BaseModel):
    prefix: str = Field(min_length=1, max_length=512)
    level: str

    @field_validator("level")
    @classmethod
    def _level(cls, v: str) -> str:
        if v not in SECURITY_LEVELS:
            raise ValueError(f"등급은 {', '.join(SECURITY_LEVELS)} 중 하나여야 합니다")
        return v


class ConnectorBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    host: str
    port: int = Field(default=445, ge=1, le=65535)
    share: str
    base_path: str = Field(default="", max_length=1024)
    username: str = Field(min_length=1, max_length=255)
    service_account_sid: str | None = None
    collection_id: UUID
    level_rules: list[LevelRule] = Field(default_factory=list, max_length=100)
    sync_interval_minutes: int = Field(default=30, ge=5, le=7 * 24 * 60)
    max_new_per_run: int = Field(default=200, ge=1, le=5000)
    enabled: bool = True

    @field_validator("host")
    @classmethod
    def _host(cls, v: str) -> str:
        if not _HOST_RE.match(v):
            raise ValueError("호스트 이름이나 IP 주소만 쓸 수 있습니다")
        return v

    @field_validator("share")
    @classmethod
    def _share(cls, v: str) -> str:
        if not _SHARE_RE.match(v):
            raise ValueError("공유 이름에 쓸 수 없는 문자가 있습니다")
        return v

    @field_validator("base_path")
    @classmethod
    def _base_path(cls, v: str) -> str:
        parts = [p for p in v.replace("\\", "/").split("/") if p]
        if any(p in (".", "..") or ":" in p for p in parts):
            raise ValueError("하위 경로에 '..'이나 ':'를 쓸 수 없습니다")
        return "/".join(parts)

    @field_validator("service_account_sid")
    @classmethod
    def _sid(cls, v: str | None) -> str | None:
        return _check_sid(v)


class ConnectorCreate(ConnectorBase):
    password: str = Field(min_length=1, max_length=256)


class ConnectorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=1, max_length=256)
    level_rules: list[LevelRule] | None = Field(default=None, max_length=100)
    sync_interval_minutes: int | None = Field(default=None, ge=5, le=7 * 24 * 60)
    max_new_per_run: int | None = Field(default=None, ge=1, le=5000)
    enabled: bool | None = None
    service_account_sid: str | None = None

    @field_validator("service_account_sid")
    @classmethod
    def _sid(cls, v: str | None) -> str | None:
        return _check_sid(v)


def _connector_out(c: SourceConnector, collection_name: str | None, held: int = 0, errors: int = 0) -> dict:
    return {
        "id": str(c.id), "name": c.name, "kind": c.kind, "host": c.host, "port": c.port, "share": c.share,
        "base_path": c.base_path, "username": c.username, "service_account_sid": c.service_account_sid,
        "collection_id": str(c.collection_id), "collection_name": collection_name,
        "level_rules": c.level_rules or [], "sync_interval_minutes": c.sync_interval_minutes,
        "max_new_per_run": c.max_new_per_run, "enabled": c.enabled, "last_sync_at": c.last_sync_at,
        "last_status": c.last_status, "held_count": held, "error_count": errors, "created_at": c.created_at,
    }


def _run_out(r: ConnectorRun) -> dict:
    return {
        "id": str(r.id), "started_at": r.started_at, "finished_at": r.finished_at, "status": r.status,
        "counts": r.counts or {}, "error_message": r.error_message,
        "triggered_by": str(r.triggered_by) if r.triggered_by else None,
    }


async def _get(db: AsyncSession, connector_id: UUID) -> SourceConnector:
    connector = await db.get(SourceConnector, connector_id)
    if connector is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    return connector


async def _collection_name(db: AsyncSession, collection_id) -> str | None:
    return await db.scalar(select(Collection.name).where(Collection.id == collection_id))


async def _item_counts(db: AsyncSession) -> dict[str, dict[str, int]]:
    rows = await db.execute(
        select(SourceItem.connector_id, SourceItem.state, func.count())
        .where(SourceItem.state.in_([ITEM_HELD, ITEM_ERROR]))
        .group_by(SourceItem.connector_id, SourceItem.state)
    )
    out: dict[str, dict[str, int]] = {}
    for cid, state, n in rows.all():
        out.setdefault(str(cid), {})[state] = n
    return out


@router.get("/admin/connectors")
async def list_connectors(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    rows = (
        await db.execute(
            select(SourceConnector, Collection.name)
            .join(Collection, Collection.id == SourceConnector.collection_id)
            .order_by(SourceConnector.created_at)
        )
    ).all()
    counts = await _item_counts(db)
    out = []
    for connector, name in rows:
        c = counts.get(str(connector.id), {})
        out.append(_connector_out(connector, name, c.get(ITEM_HELD, 0), c.get(ITEM_ERROR, 0)))
    return out


@router.post("/admin/connectors", status_code=201)
async def create_connector(
    data: ConnectorCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
):
    require_admin(current_user)
    collection = await db.get(Collection, data.collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    service_user = new_service_user(data.name)
    db.add(service_user)
    await db.flush()
    connector = SourceConnector(
        **data.model_dump(exclude={"password", "level_rules"}),
        level_rules=[r.model_dump() for r in data.level_rules],
        password_encrypted=encrypt_secret(data.password),
        service_user_id=service_user.id,
        created_by=current_user.id,
    )
    db.add(connector)
    await db.flush()
    log_audit(db, str(current_user.id), "connector.create", "connector", str(connector.id),
              detail={"name": data.name, "host": data.host, "share": data.share,
                      "collection_id": str(data.collection_id)})
    await db.commit()
    await db.refresh(connector)
    return _connector_out(connector, collection.name)


@router.get("/admin/connectors/{connector_id}")
async def get_connector(
    connector_id: UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
):
    require_admin(current_user)
    connector = await _get(db, connector_id)
    runs = (
        await db.scalars(
            select(ConnectorRun).where(ConnectorRun.connector_id == connector.id)
            .order_by(ConnectorRun.started_at.desc()).limit(_RECENT_RUNS)
        )
    ).all()
    problems = (
        await db.scalars(
            select(SourceItem).where(
                SourceItem.connector_id == connector.id, SourceItem.state.in_([ITEM_HELD, ITEM_ERROR])
            ).order_by(SourceItem.path).limit(_MAX_LISTED_ITEMS)
        )
    ).all()
    counts = (await _item_counts(db)).get(str(connector.id), {})
    return {
        **_connector_out(connector, await _collection_name(db, connector.collection_id),
                         counts.get(ITEM_HELD, 0), counts.get(ITEM_ERROR, 0)),
        "runs": [_run_out(r) for r in runs],
        "problem_items": [
            {"path": i.path, "state": i.state, "reason": i.hold_reason, "detail": i.hold_detail,
             "last_seen_at": i.last_seen_at}
            for i in problems
        ],
    }


@router.patch("/admin/connectors/{connector_id}")
async def update_connector(
    connector_id: UUID, data: ConnectorUpdate,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    connector = await _get(db, connector_id)
    changes = data.model_dump(exclude_unset=True)
    password = changes.pop("password", None)
    for field, value in changes.items():
        if value is None and field != "service_account_sid":
            continue
        setattr(connector, field, value)
    if password:
        connector.password_encrypted = encrypt_secret(password)
    log_audit(db, str(current_user.id), "connector.update", "connector", str(connector.id),
              detail={"fields": sorted(changes) + (["password"] if password else [])})
    await db.commit()
    await db.refresh(connector)
    return _connector_out(connector, await _collection_name(db, connector.collection_id))


@router.post("/admin/connectors/{connector_id}/sync", status_code=202)
async def sync_connector_now(
    connector_id: UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
):
    from app.pipeline.tasks.connectors import sync_connector_task

    require_admin(current_user)
    connector = await _get(db, connector_id)
    log_audit(db, str(current_user.id), "connector.sync_request", "connector", str(connector.id))
    await db.commit()
    sync_connector_task.delay(str(connector.id), str(current_user.id))
    return {"status": "queued", "requested_at": datetime.utcnow()}


@router.post("/admin/connectors/{connector_id}/test")
async def test_connector(
    connector_id: UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """저장된 설정으로 연결해 앞쪽 파일 몇 개를 읽어 본다. 문서는 만들지 않는다."""
    from app.services.connectors.registry import build_source_client

    require_admin(current_user)
    connector = await _get(db, connector_id)

    def _probe() -> list[str]:
        client = build_source_client(connector)
        try:
            sample = []
            for remote in client.list_files():
                sample.append(remote.path)
                if len(sample) >= 5:
                    break
            return sample
        finally:
            client.close()

    try:
        sample = await asyncio.to_thread(_probe)
    except Exception as exc:  # 연결·인증·경로 오류를 모두 실패로 알린다
        return {"ok": False, "error": type(exc).__name__, "sample": []}
    return {"ok": True, "error": None, "sample": sample}


@router.delete("/admin/connectors/{connector_id}", status_code=204)
async def delete_connector(
    connector_id: UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
):
    require_admin(current_user)
    connector = await _get(db, connector_id)
    # 동기화 도중에 지우면 동기화가 이미 지운 커넥터로 문서를 계속 만든다. 끝날 때까지 막는다.
    with held_lock(connector_lock_key(str(connector_id))) as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="동기화가 진행 중입니다. 끝난 뒤에 지우세요.")
        await _delete_connector_and_documents(db, connector, current_user)


async def _delete_connector_and_documents(db: AsyncSession, connector: SourceConnector, current_user: User) -> None:
    from app.api.v1.endpoints.documents import listing as listing_api

    connector_id = connector.id
    name = connector.name
    service_user = await db.get(User, connector.service_user_id)
    document_ids = list((await db.scalars(
        select(SourceItem.document_id).where(
            SourceItem.connector_id == connector.id, SourceItem.document_id.is_not(None)
        )
    )).all())
    for document_id in document_ids:
        await listing_api.delete_document(UUID(str(document_id)), db, service_user)

    log_audit(db, str(current_user.id), "connector.delete", "connector", str(connector_id),
              detail={"name": name, "documents_removed": len(document_ids)})
    await db.delete(await _get(db, connector_id))
    await db.commit()
