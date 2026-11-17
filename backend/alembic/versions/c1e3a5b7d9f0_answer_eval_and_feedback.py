"""답변 품질 평가와 사용자 피드백: golden_queries.expected_facts, golden_eval_runs 답변 지표, chat_messages 피드백

Revision ID: c1e3a5b7d9f0
Revises: b9d1f3a5c7e8
Create Date: 2026-11-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1e3a5b7d9f0"
down_revision: Union[str, None] = "b9d1f3a5c7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("golden_queries", sa.Column("expected_facts", sa.JSON(), nullable=True))
    op.add_column(
        "golden_eval_runs",
        sa.Column("with_answers", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("golden_eval_runs", sa.Column("mean_fact_recall", sa.Float(), nullable=True))
    op.add_column("chat_messages", sa.Column("feedback", sa.String(length=10), nullable=True))
    op.add_column("chat_messages", sa.Column("feedback_note", sa.Text(), nullable=True))
    op.add_column("chat_messages", sa.Column("feedback_at", sa.DateTime(), nullable=True))
    op.create_index("ix_chat_messages_feedback", "chat_messages", ["feedback"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_feedback", table_name="chat_messages")
    op.drop_column("chat_messages", "feedback_at")
    op.drop_column("chat_messages", "feedback_note")
    op.drop_column("chat_messages", "feedback")
    op.drop_column("golden_eval_runs", "mean_fact_recall")
    op.drop_column("golden_eval_runs", "with_answers")
    op.drop_column("golden_queries", "expected_facts")
