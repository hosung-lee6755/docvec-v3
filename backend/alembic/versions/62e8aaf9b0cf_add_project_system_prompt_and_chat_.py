"""add project system_prompt and chat_conversations project_id

Revision ID: 62e8aaf9b0cf
Revises: 8bdccc5e2cf8
Create Date: 2026-07-06 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '62e8aaf9b0cf'
down_revision: Union[str, None] = '8bdccc5e2cf8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('system_prompt', sa.Text(), nullable=True))
    op.add_column('chat_conversations', sa.Column('project_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_chat_conversations_project_id', 'chat_conversations', 'projects', ['project_id'], ['id'],
    )


def downgrade() -> None:
    op.drop_constraint('fk_chat_conversations_project_id', 'chat_conversations', type_='foreignkey')
    op.drop_column('chat_conversations', 'project_id')
    op.drop_column('projects', 'system_prompt')
