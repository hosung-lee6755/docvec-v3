"""add summary to documents

Revision ID: b4d8e1f6a2c9
Revises: 0ae30239e2e7
Create Date: 2026-07-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4d8e1f6a2c9'
down_revision: Union[str, None] = '0ae30239e2e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('summary', sa.Text(), nullable=True))
    op.add_column(
        'documents',
        sa.Column('summary_status', sa.String(length=20), nullable=False, server_default='PENDING'),
    )


def downgrade() -> None:
    op.drop_column('documents', 'summary_status')
    op.drop_column('documents', 'summary')
