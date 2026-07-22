"""add block_execution_cache.requires_review

Revision ID: c5d7f9a1b3e4
Revises: b4c6e8f0a2d3
Create Date: 2026-07-21 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c5d7f9a1b3e4'
down_revision: Union[str, None] = 'b4c6e8f0a2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'block_execution_cache',
        sa.Column('requires_review', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('block_execution_cache', 'requires_review')
