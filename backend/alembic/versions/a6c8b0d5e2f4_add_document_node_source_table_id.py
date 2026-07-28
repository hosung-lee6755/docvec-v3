"""add document_nodes.source_table_id

Revision ID: a6c8b0d5e2f4
Revises: f4a6c8b0d5e2
Create Date: 2026-07-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a6c8b0d5e2f4'
down_revision: Union[str, None] = 'f4a6c8b0d5e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 문서 파싱 고도화 Phase 3: links a TABLE node back to its
    # Document.tables[*]["id"] entry. Nullable/additive — existing TABLE
    # nodes simply stay NULL until their document is reprocessed.
    op.add_column("document_nodes", sa.Column("source_table_id", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_nodes", "source_table_id")
