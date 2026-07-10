"""add tables to documents

Revision ID: c7a2f4e8b1d3
Revises: b4d8e1f6a2c9
Create Date: 2026-07-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7a2f4e8b1d3'
down_revision: Union[str, None] = 'b4d8e1f6a2c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('tables', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('documents', 'tables')
