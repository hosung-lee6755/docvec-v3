"""add rejected to pii_detections

Revision ID: b3d5f7a9c1e3
Revises: a2c4e6f8b0d2
Create Date: 2026-07-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b3d5f7a9c1e3'
down_revision: Union[str, None] = 'a2c4e6f8b0d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'pii_detections',
        sa.Column('rejected', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('pii_detections', 'rejected')
