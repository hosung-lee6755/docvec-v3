"""add collections.chunk_strategy

Revision ID: f7b8c9d0e1a2
Revises: e5f6a7b8c9d0
Create Date: 2026-07-09

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f7b8c9d0e1a2'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'collections',
        sa.Column('chunk_strategy', sa.String(20), nullable=False, server_default='size'),
    )


def downgrade() -> None:
    op.drop_column('collections', 'chunk_strategy')
