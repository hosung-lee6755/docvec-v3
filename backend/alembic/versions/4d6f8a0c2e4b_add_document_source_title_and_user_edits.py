"""add documents.source_title and documents.user_edited_fields

Revision ID: 4d6f8a0c2e4b
Revises: 3c5e7a9b1d2f
Create Date: 2026-10-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '4d6f8a0c2e4b'
down_revision: Union[str, None] = '3c5e7a9b1d2f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # source_title: 원본 파일 내장 제목 속성(제목 판정 후보). user_edited_fields: 사용자가 직접 고쳐
    # 재처리가 덮어쓰면 안 되는 필드 이름 목록. 둘 다 nullable — 기존 문서는 NULL 로 남는다.
    op.add_column("documents", sa.Column("source_title", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("user_edited_fields", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "user_edited_fields")
    op.drop_column("documents", "source_title")
