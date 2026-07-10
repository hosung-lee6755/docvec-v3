"""add collections.reembed_status and reembed_progress

Revision ID: a3c5d7e9f1b2
Revises: f7b8c9d0e1a2
Create Date: 2026-07-10

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a3c5d7e9f1b2'
down_revision: Union[str, None] = 'f7b8c9d0e1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('collections', sa.Column('reembed_status', sa.String(20), nullable=True))
    op.add_column('collections', sa.Column('reembed_progress', sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column('collections', 'reembed_progress')
    op.drop_column('collections', 'reembed_status')
