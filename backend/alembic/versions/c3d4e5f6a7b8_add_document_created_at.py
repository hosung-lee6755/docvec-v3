"""add documents.document_created_at

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-24 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 메타 정보 생성.txt 1절 — 문서 자체의 작성일. 기존 documents.created_at은
    # DB row 생성(ingestion) 시각이라 별개 개념이므로 신규 컬럼으로 추가한다.
    op.add_column(
        "documents",
        sa.Column("document_created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "document_created_at")
