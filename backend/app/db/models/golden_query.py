from datetime import datetime
from uuid import uuid4

from sqlalchemy import ForeignKey, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.db.types import UTCDateTime

from app.db.base import Base


class GoldenQuery(Base):
    """A user-defined (query, expected documents) pair used to measure
    retrieval quality for a collection — see golden_eval_runs for the
    precision/recall results computed against these."""

    __tablename__ = "golden_queries"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    collection_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collections.id"), index=True
    )
    query: Mapped[str] = mapped_column(Text)
    # list[str] of Document UUIDs the user considers relevant for this query.
    expected_document_ids: Mapped[list] = mapped_column(JSON)
    # 답에 반드시 들어 있어야 할 사실 조각(list[str]). 있으면 "답변까지 평가"에서 답을 만들어 대조한다.
    expected_facts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
