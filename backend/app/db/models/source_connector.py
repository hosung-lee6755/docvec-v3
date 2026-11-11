"""문서 원천 커넥터(v3 마일스톤 3).

커넥터 하나는 SMB 공유 폴더 하나를 컬렉션 하나에 이어 준다. 파일과 함께 NTFS 권한을 가져와
문서 ACL로 옮긴다. 원천이 기준이므로 커넥터 문서의 ACL과 등급은 화면에서 고치지 않는다.

커넥터마다 로그인할 수 없는 내부 사용자(`service_user_id`, auth_source=system)를 두고 문서의
업로더로 쓴다. 등록한 관리자를 업로더로 쓰면 "업로더는 항상 본다" 규칙 때문에 그 관리자가
원천 권한과 무관하게 모든 파일을 보게 되기 때문이다.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime

CONNECTOR_KIND_SMB = "smb"

ITEM_SYNCED = "synced"
ITEM_HELD = "held"
ITEM_ERROR = "error"
ITEM_SKIPPED = "skipped"

RUN_RUNNING = "running"
RUN_SUCCESS = "success"
RUN_PARTIAL = "partial"
RUN_FAILED = "failed"


class SourceConnector(Base):
    __tablename__ = "source_connectors"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(20), default=CONNECTOR_KIND_SMB)
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=445)
    share: Mapped[str] = mapped_column(String(255))
    base_path: Mapped[str] = mapped_column(String(1024), default="", server_default="")
    username: Mapped[str] = mapped_column(String(255))
    # Fernet 암호문(app/core/crypto.py). 평문은 저장하지도, 응답에 넣지도 않는다.
    password_encrypted: Mapped[str] = mapped_column(Text)
    # 수집용 계정의 SID. 모든 파일에 읽기 권한으로 들어 있으므로 권한 매핑에서 뺀다.
    service_account_sid: Mapped[str | None] = mapped_column(String(184), nullable=True)
    collection_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collections.id", ondelete="CASCADE"), index=True
    )
    service_user_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    # [{"prefix": "exec/", "level": "Confidential"}, ...] — 가장 긴 접두어가 이긴다.
    level_rules: Mapped[list] = mapped_column(JSON, default=list)
    sync_interval_minutes: Mapped[int] = mapped_column(Integer, default=30)
    max_new_per_run: Mapped[int] = mapped_column(Integer, default=200)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class SourceItem(Base):
    """원천 파일 한 개의 동기화 상태. 원천 경로 하나가 문서 하나에 대응한다."""

    __tablename__ = "source_items"
    __table_args__ = (UniqueConstraint("connector_id", "path", name="uq_source_items_connector_path"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    connector_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_connectors.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(2048))
    document_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mtime: Mapped[float | None] = mapped_column(Float, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sd_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state: Mapped[str] = mapped_column(String(20), default=ITEM_SYNCED)
    hold_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hold_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ConnectorRun(Base):
    __tablename__ = "connector_runs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    connector_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_connectors.id", ondelete="CASCADE"), index=True
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=RUN_RUNNING)
    # {"added": n, "content_changed": n, "acl_changed": n, "deleted": n, "held": n, "errors": n, ...}
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
