"""관리자 문의 표(inquiries, inquiry_messages) 추가

Revision ID: e5b7d9f1a3c6
Revises: d2f4a6c8e0b1
Create Date: 2026-11-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e5b7d9f1a3c6"
down_revision: Union[str, None] = "d2f4a6c8e0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inquiries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "author_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "document_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("error_snapshot", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_inquiries_author_id", "inquiries", ["author_id"])
    op.create_index("ix_inquiries_status_updated", "inquiries", ["status", "updated_at"])

    op.create_table(
        "inquiry_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "inquiry_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inquiries.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "author_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_inquiry_messages_inquiry_created", "inquiry_messages", ["inquiry_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_inquiry_messages_inquiry_created", table_name="inquiry_messages")
    op.drop_table("inquiry_messages")
    op.drop_index("ix_inquiries_status_updated", table_name="inquiries")
    op.drop_index("ix_inquiries_author_id", table_name="inquiries")
    op.drop_table("inquiries")
