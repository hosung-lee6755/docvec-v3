"""add documents.extraction_layout

Revision ID: e2f4a6c8b0d5
Revises: d8e0f2a4b6c8
Create Date: 2026-07-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e2f4a6c8b0d5'
down_revision: Union[str, None] = 'd8e0f2a4b6c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 문서 파싱 고도화 Phase 1: per-line font/position signals from adapters
    # that expose them (PDF/DOCX), consumed by structure_analyze for
    # font-aware heading/footnote classification. Nullable/additive — existing
    # rows and formats without a line-layout source (HWP/HWPX) simply stay
    # NULL, and structure_analyze falls back to its regex-only path.
    op.add_column("documents", sa.Column("extraction_layout", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "extraction_layout")
