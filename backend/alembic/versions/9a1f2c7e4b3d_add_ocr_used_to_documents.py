"""add ocr_used to documents

Revision ID: 9a1f2c7e4b3d
Revises: 313b3f79856a
Create Date: 2026-07-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a1f2c7e4b3d'
down_revision: Union[str, None] = '313b3f79856a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column('ocr_used', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('documents', 'ocr_used')
