"""add documents.elements

Revision ID: f6a8c0d2e4f6
Revises: d1e3f5a7b9c1
Create Date: 2026-07-23 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f6a8c0d2e4f6'
down_revision: Union[str, None] = 'd1e3f5a7b9c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Docling 도입 설계서(2026-07-23) Phase 1: DoclingAdapter(engine="docling",
    # PDF 전용)로 처리된 문서에서만 채워지는 통합 요소 JSON. Nullable/additive —
    # legacy 엔진으로 처리된 기존 문서는 NULL로 남고, structure_analyze/표 탭은
    # 기존 정규식·Document.tables 경로로 계속 동작한다.
    op.add_column("documents", sa.Column("elements", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "elements")
