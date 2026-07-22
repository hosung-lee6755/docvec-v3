"""add quality_reports.warning_categories

Revision ID: b4c6e8f0a2d3
Revises: a3c5e7b9d1f2
Create Date: 2026-07-21 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b4c6e8f0a2d3'
down_revision: Union[str, None] = 'a3c5e7b9d1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'quality_reports',
        sa.Column('warning_categories', sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('quality_reports', 'warning_categories')
