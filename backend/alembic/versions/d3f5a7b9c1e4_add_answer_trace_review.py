"""answer_traces 에 관리자 검토 칸(원인, 검토자, 검토 시각, 등록한 골든 쿼리)을 더한다.

Revision ID: d3f5a7b9c1e4
Revises: c1e3a5b7d9f2
Create Date: 2026-11-20
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d3f5a7b9c1e4"
down_revision: str | None = "c1e3a5b7d9f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("answer_traces", sa.Column("review_cause", sa.String(16), nullable=True))
    op.add_column("answer_traces", sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("answer_traces", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("answer_traces", sa.Column("golden_query_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_answer_traces_review_cause", "answer_traces", ["review_cause"])
    op.create_foreign_key(
        "fk_answer_traces_reviewed_by_users", "answer_traces", "users", ["reviewed_by"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_answer_traces_golden_query_id_golden_queries", "answer_traces", "golden_queries",
        ["golden_query_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_answer_traces_golden_query_id_golden_queries", "answer_traces", type_="foreignkey")
    op.drop_constraint("fk_answer_traces_reviewed_by_users", "answer_traces", type_="foreignkey")
    op.drop_index("ix_answer_traces_review_cause", table_name="answer_traces")
    op.drop_column("answer_traces", "golden_query_id")
    op.drop_column("answer_traces", "reviewed_at")
    op.drop_column("answer_traces", "reviewed_by")
    op.drop_column("answer_traces", "review_cause")
