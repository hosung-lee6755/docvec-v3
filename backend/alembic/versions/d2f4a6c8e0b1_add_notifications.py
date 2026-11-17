"""화면 알림 표(notifications) 추가

Revision ID: d2f4a6c8e0b1
Revises: c1e3a5b7d9f0
Create Date: 2026-11-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d2f4a6c8e0b1"
down_revision: Union[str, None] = "c1e3a5b7d9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("link", sa.String(length=500), nullable=True),
        sa.Column("resource_type", sa.String(length=40), nullable=True),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_table("notifications")
