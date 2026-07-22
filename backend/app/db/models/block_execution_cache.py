from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BlockExecutionCache(Base):
    """Memoizes a block's output by input fingerprint — 전처리 워크플로우 통합
    설계서 §2.4 / §21.2. `cache_key` is a sha256 hex digest of (source file
    hash + block type + block version + block config hash + dictionary
    version for dictionary blocks + model version for LLM/embedding blocks),
    computed by the executor (wired in Phase 2). A cache hit lets a partial
    reprocess or a re-run with unchanged upstream inputs skip re-executing
    that block entirely."""

    __tablename__ = "block_execution_cache"

    cache_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    artifact_key: Mapped[str] = mapped_column(String(512))
    output_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    # 캐시로 재생되는 실행도 원본 실행이 검토를 요구했다면 똑같이 WAITING_REVIEW로
    # 멈춰야 한다 — 이전에는 캐시 적중 시 이 값을 전혀 확인하지 않고 무조건
    # _advance()로 넘어가 검토 게이트를 우회하는 버그가 있었다(2026-07-21,
    # quality_check 재실행 테스트 중 발견 — 미승인 상태에서 rag_store가 실행되어
    # 청크가 임베딩되는 사고로 이어짐).
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
