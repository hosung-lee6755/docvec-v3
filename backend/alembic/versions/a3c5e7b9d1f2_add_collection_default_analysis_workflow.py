"""add collection.default_analysis_workflow_id/version + AUTO_ANALYSIS trigger

Revision ID: a3c5e7b9d1f2
Revises: f1a3c5e7b9d1
Create Date: 2026-07-20 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a3c5e7b9d1f2'
down_revision: Union[str, None] = 'f1a3c5e7b9d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'collections',
        sa.Column(
            'default_analysis_workflow_id', postgresql.UUID(as_uuid=True),
            sa.ForeignKey('workflow_definitions.id', ondelete='SET NULL'), nullable=True,
        ),
    )
    op.add_column(
        'collections',
        sa.Column('default_analysis_workflow_version', sa.Integer(), nullable=True),
    )
    # Additive enum value — safe to add inside this migration's transaction as
    # long as it isn't used in the same transaction (PG 12+).
    op.execute("ALTER TYPE workflow_run_trigger ADD VALUE IF NOT EXISTS 'AUTO_ANALYSIS'")


def downgrade() -> None:
    op.drop_column('collections', 'default_analysis_workflow_version')
    op.drop_column('collections', 'default_analysis_workflow_id')
    # Postgres has no DROP VALUE for enums — leaving 'AUTO_ANALYSIS' registered
    # on downgrade is harmless (no row will reference it once the column/logic
    # that produced it is gone).
