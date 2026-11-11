"""v3 milestone 6: search settings per collection, citation evidence, dictionary context and per-document exclusions

Revision ID: c9f1a3b5d7e9
Revises: b8e4f6a0c3d5
Create Date: 2026-11-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9f1a3b5d7e9"
down_revision: Union[str, None] = "b8e4f6a0c3d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("collections", sa.Column("search_settings", sa.JSON(), nullable=True))
    op.add_column("chat_messages", sa.Column("expanded_terms", sa.JSON(), nullable=True))
    op.add_column("answer_trace_sources", sa.Column("evidence", sa.JSON(), nullable=True))
    op.add_column("dictionary_applications", sa.Column("context_before", sa.Text(), nullable=True))
    op.add_column("dictionary_applications", sa.Column("context_after", sa.Text(), nullable=True))
    op.create_table(
        "document_dictionary_exclusions",
        sa.Column("document_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("entry_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("dictionary_entries.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("document_dictionary_exclusions")
    op.drop_column("dictionary_applications", "context_after")
    op.drop_column("dictionary_applications", "context_before")
    op.drop_column("answer_trace_sources", "evidence")
    op.drop_column("chat_messages", "expanded_terms")
    op.drop_column("collections", "search_settings")
