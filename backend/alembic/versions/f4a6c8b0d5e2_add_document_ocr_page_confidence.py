"""add documents.ocr_page_confidence

Revision ID: f4a6c8b0d5e2
Revises: e2f4a6c8b0d5
Create Date: 2026-07-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f4a6c8b0d5e2'
down_revision: Union[str, None] = 'e2f4a6c8b0d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 문서 파싱 고도화 Phase 3: per-page mean word OCR confidence, captured via
    # pytesseract.image_to_data instead of image_to_string. Nullable/additive —
    # existing rows and pages OCR'd through a cloud VLM (no word-level
    # confidence available) simply stay NULL, and quality_check falls back to
    # its prior format_detect-based approximation when this is absent.
    op.add_column("documents", sa.Column("ocr_page_confidence", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "ocr_page_confidence")
