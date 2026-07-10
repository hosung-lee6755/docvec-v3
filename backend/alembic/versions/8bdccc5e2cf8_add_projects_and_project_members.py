"""add projects and project_members, link collections to projects

Revision ID: 8bdccc5e2cf8
Revises: a1c2e5f9d3b7
Create Date: 2026-07-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8bdccc5e2cf8'
down_revision: Union[str, None] = 'a1c2e5f9d3b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'projects',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_projects_name'), 'projects', ['name'])

    op.create_table(
        'project_members',
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('role', sa.Enum('viewer', 'editor', name='project_member_role'), nullable=False),
        sa.Column('invited_by', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['invited_by'], ['users.id']),
        sa.PrimaryKeyConstraint('project_id', 'user_id'),
    )

    op.add_column('collections', sa.Column('project_id', sa.UUID(), nullable=True))
    op.add_column(
        'collections',
        sa.Column('restrict_to_members', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_foreign_key(
        'fk_collections_project_id', 'collections', 'projects', ['project_id'], ['id'],
    )


def downgrade() -> None:
    op.drop_constraint('fk_collections_project_id', 'collections', type_='foreignkey')
    op.drop_column('collections', 'restrict_to_members')
    op.drop_column('collections', 'project_id')
    op.drop_table('project_members')
    sa.Enum(name='project_member_role').drop(op.get_bind(), checkfirst=True)
    op.drop_index(op.f('ix_projects_name'), table_name='projects')
    op.drop_table('projects')
