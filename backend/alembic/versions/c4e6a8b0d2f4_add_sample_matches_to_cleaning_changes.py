"""add sample_matches to cleaning_changes

Revision ID: c4e6a8b0d2f4
Revises: b3d5f7a9c1e3
Create Date: 2026-07-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c4e6a8b0d2f4'
down_revision: Union[str, None] = 'b3d5f7a9c1e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'cleaning_changes',
        sa.Column('sample_matches', sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('cleaning_changes', 'sample_matches')
