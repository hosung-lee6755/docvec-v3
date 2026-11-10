from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime


class DocumentAclEntry(Base):
    """문서별 접근 허용 목록 항목(v3 권한 모델).

    문서에 항목이 하나도 없으면 "제한 없음"(컬렉션 권한·보안등급만 적용)이고,
    하나라도 있으면 목록에 있는 사용자/그룹(+업로더 본인)만 볼 수 있다.
    principal_id는 users.id 또는 user_groups.id를 가리키는 다형 참조라 FK가 없다.
    그룹·사용자를 삭제해도 항목은 지우지 않는다(fail-closed) — 지우면 그 주체만 허용하던
    문서의 목록이 비어 "제한 없음"으로 넓어진다. 남은 항목은 아무에게도 매칭되지 않고,
    ACL 조회 화면에는 "삭제된 사용자/그룹"으로 표시되어 문서 편집자가 정리한다.
    """

    __tablename__ = "document_acl_entries"
    __table_args__ = (
        CheckConstraint("principal_type IN ('user', 'group')", name="ck_document_acl_principal_type"),
        Index("ix_document_acl_principal", "principal_type", "principal_id"),
    )

    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    principal_type: Mapped[str] = mapped_column(String(10), primary_key=True)
    principal_id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True)
    created_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
