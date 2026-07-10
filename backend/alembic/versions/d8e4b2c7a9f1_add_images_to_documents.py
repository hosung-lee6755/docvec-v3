"""add images to documents

Revision ID: d8e4b2c7a9f1
Revises: c7a2f4e8b1d3
Create Date: 2026-07-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd8e4b2c7a9f1'
down_revision: Union[str, None] = 'c7a2f4e8b1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('images', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('documents', 'images')
