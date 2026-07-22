"""add document_status ANALYZING value

Revision ID: d8e0f2a4b6c8
Revises: c5d7f9a1b3e4
Create Date: 2026-07-21 05:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd8e0f2a4b6c8'
down_revision: Union[str, None] = 'c5d7f9a1b3e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Additive enum value — an AUTO_ANALYSIS run gives the document no other
    # way to signal "still working" (analysis block types aren't in
    # _STATUS_FOR_BLOCK_TYPE, so the document stayed on the stale "INDEXED"
    # label from the prior preprocess completion for the run's whole duration).
    op.execute("ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'ANALYZING'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums — leaving 'ANALYZING' registered on
    # downgrade is harmless once the code path that sets it is reverted.
    pass
