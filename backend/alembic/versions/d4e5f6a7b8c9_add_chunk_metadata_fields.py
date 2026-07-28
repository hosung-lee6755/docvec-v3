"""add document_chunks heading_path/char_count/language/source_file/version

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-24 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 메타 정보 생성.txt 3절 — 자동 생성 가능한 4개 필드. heading_path는
    # 기존 section_path 컬럼과 동일한 데이터라 추가하지 않는다(중복 방지,
    # 응답 스키마에서 스펙 필드명으로만 노출).
    op.add_column("document_chunks", sa.Column("char_count", sa.Integer(), nullable=True))
    op.add_column("document_chunks", sa.Column("language", sa.String(10), nullable=True))
    op.add_column("document_chunks", sa.Column("source_file", sa.Text(), nullable=True))
    op.add_column("document_chunks", sa.Column("version", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("document_chunks", "version")
    op.drop_column("document_chunks", "source_file")
    op.drop_column("document_chunks", "language")
    op.drop_column("document_chunks", "char_count")
