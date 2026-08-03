from datetime import datetime
from uuid import uuid4

from sqlalchemy import Float, ForeignKey, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.db.types import UTCDateTime

from app.db.base import Base


class GoldenEvalRun(Base):
    """One execution of the golden-query evaluation for a collection — runs
    every GoldenQuery through the same retrieval path as chat/search and
    records precision/recall per query plus the aggregate mean."""

    __tablename__ = "golden_eval_runs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    collection_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collections.id"), index=True
    )
    created_by: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    top_k: Mapped[int] = mapped_column(Integer)
    mean_precision: Mapped[float] = mapped_column(Float)
    mean_recall: Mapped[float] = mapped_column(Float)
    # Per-query breakdown: [{golden_query_id, query, expected_document_ids,
    # retrieved_document_ids, precision, recall}, ...]
    results: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
