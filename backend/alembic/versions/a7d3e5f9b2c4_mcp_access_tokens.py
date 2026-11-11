"""v3 personal access tokens for MCP and answer channel

Revision ID: a7d3e5f9b2c4
Revises: 9c4e6a8b1d2f
Create Date: 2026-11-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7d3e5f9b2c4"
down_revision: Union[str, None] = "9c4e6a8b1d2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "personal_access_tokens",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("token_prefix", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_personal_access_tokens_token_hash"),
    )
    op.create_index("ix_personal_access_tokens_user_id", "personal_access_tokens", ["user_id"])

    op.add_column("chat_conversations",
                  sa.Column("channel", sa.String(10), nullable=False, server_default="web"))
    op.add_column("chat_conversations", sa.Column(
        "access_token_id", UUID,
        sa.ForeignKey("personal_access_tokens.id", ondelete="SET NULL", name="fk_chat_conversations_access_token"),
        nullable=True,
    ))
    op.add_column("answer_traces", sa.Column("channel", sa.String(10), nullable=False, server_default="web"))
    # 외래 키를 걸지 않는다. 답변 추적은 감사 증적이라, 사용자를 지워 토큰이 함께 지워져도 어떤 토큰으로 물었는지 남긴다
    op.add_column("answer_traces", sa.Column("access_token_id", UUID, nullable=True))


def downgrade() -> None:
    op.drop_column("answer_traces", "access_token_id")
    op.drop_column("answer_traces", "channel")
    op.drop_constraint("fk_chat_conversations_access_token", "chat_conversations", type_="foreignkey")
    op.drop_column("chat_conversations", "access_token_id")
    op.drop_column("chat_conversations", "channel")
    op.drop_index("ix_personal_access_tokens_user_id", table_name="personal_access_tokens")
    op.drop_table("personal_access_tokens")
