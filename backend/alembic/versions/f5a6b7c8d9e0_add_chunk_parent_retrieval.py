"""add document_chunks parent_chunk_id/chunk_tier

Revision ID: f5a6b7c8d9e0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-24 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f5a6b7c8d9e0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 메타 정보 생성.txt 3절 Parent Retrieval — 계층형(parent/child) 청킹
    # 신규 구현(사용자 확정, 2026-07-24). parent_chunk_id는 자기참조 FK.
    op.add_column(
        "document_chunks",
        sa.Column("parent_chunk_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("chunk_tier", sa.String(10), nullable=False, server_default="child"),
    )
    op.create_foreign_key(
        "fk_document_chunks_parent_chunk_id",
        "document_chunks", "document_chunks",
        ["parent_chunk_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_document_chunks_parent_chunk_id", "document_chunks", type_="foreignkey")
    op.drop_column("document_chunks", "chunk_tier")
    op.drop_column("document_chunks", "parent_chunk_id")
