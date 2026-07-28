"""add document_nodes.correction_type/correction_notes

Revision ID: c8b0d5e2f4a6
Revises: a6c8b0d5e2f4
Create Date: 2026-07-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c8b0d5e2f4a6'
down_revision: Union[str, None] = 'a6c8b0d5e2f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 문서 파싱 고도화 Phase 4: audit info alongside the existing
    # user_corrected flag — what changed (correction_type) and why
    # (correction_notes, editor-supplied). Nullable/additive, no separate
    # correction-history table.
    op.add_column("document_nodes", sa.Column("correction_type", sa.Text(), nullable=True))
    op.add_column("document_nodes", sa.Column("correction_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_nodes", "correction_notes")
    op.drop_column("document_nodes", "correction_type")
