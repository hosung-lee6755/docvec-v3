"""documents 에 문서 유형(지정값·판별값), collections 에 기본 문서 유형을 더한다.

규정·법령은 조 단위로 구조를 잡고 청크를 나눈다(2026-11-27 사용자 결정). 유형은 사용자가 지정한 값을 먼저 쓰고,
없으면 컬렉션 기본값, 그것도 없으면 구조 분석이 판별한 값을 쓴다(services/document_type.py).

Revision ID: f8c0e2a4b6d8
Revises: e4a6c8b0d2f5
Create Date: 2026-11-27
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f8c0e2a4b6d8"
down_revision: str | None = "e4a6c8b0d2f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("document_type", sa.String(length=20), nullable=True))
    op.add_column("documents", sa.Column("detected_document_type", sa.String(length=20), nullable=True))
    op.add_column("collections", sa.Column("default_document_type", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("collections", "default_document_type")
    op.drop_column("documents", "detected_document_type")
    op.drop_column("documents", "document_type")
