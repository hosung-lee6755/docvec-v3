"""add collection_members table

Revision ID: 3f7d9b1a5c22
Revises: 9a1f2c7e4b3d
Create Date: 2026-07-04 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f7d9b1a5c22'
down_revision: Union[str, None] = '9a1f2c7e4b3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'collection_members',
        sa.Column('collection_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('role', sa.Enum('viewer', 'editor', name='collection_member_role'), nullable=False),
        sa.Column('invited_by', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['collection_id'], ['collections.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['invited_by'], ['users.id']),
        sa.PrimaryKeyConstraint('collection_id', 'user_id'),
    )


def downgrade() -> None:
    op.drop_table('collection_members')
    sa.Enum(name='collection_member_role').drop(op.get_bind(), checkfirst=True)
