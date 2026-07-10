"""add chat_conversations, restructure chat_messages

Revision ID: a1c2e5f9d3b7
Revises: 3290dcabcdc2
Create Date: 2026-07-05 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c2e5f9d3b7'
down_revision: Union[str, None] = '3290dcabcdc2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'chat_conversations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('collection_id', sa.UUID(), nullable=True),
        sa.Column('model_key', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['collection_id'], ['collections.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )

    # chat_messages so far only contains disposable local test data (curl-based
    # manual testing during this feature's development) — no production rows to
    # migrate, so it's simplest to clear the table before reshaping its columns.
    op.execute("DELETE FROM chat_messages")

    op.add_column('chat_messages', sa.Column('conversation_id', sa.UUID(), nullable=False))
    op.create_foreign_key(
        'fk_chat_messages_conversation_id', 'chat_messages', 'chat_conversations',
        ['conversation_id'], ['id'],
    )
    op.drop_constraint('chat_messages_user_id_fkey', 'chat_messages', type_='foreignkey')
    op.drop_constraint('chat_messages_collection_id_fkey', 'chat_messages', type_='foreignkey')
    op.drop_column('chat_messages', 'user_id')
    op.drop_column('chat_messages', 'collection_id')
    op.drop_column('chat_messages', 'model_key')


def downgrade() -> None:
    op.add_column('chat_messages', sa.Column('model_key', sa.Text(), nullable=True))
    op.add_column('chat_messages', sa.Column('collection_id', sa.UUID(), nullable=True))
    op.add_column('chat_messages', sa.Column('user_id', sa.UUID(), nullable=True))
    op.execute("DELETE FROM chat_messages")
    op.drop_constraint('fk_chat_messages_conversation_id', 'chat_messages', type_='foreignkey')
    op.drop_column('chat_messages', 'conversation_id')
    op.create_foreign_key(
        'chat_messages_collection_id_fkey', 'chat_messages', 'collections',
        ['collection_id'], ['id'],
    )
    op.create_foreign_key(
        'chat_messages_user_id_fkey', 'chat_messages', 'users',
        ['user_id'], ['id'],
    )
    op.alter_column('chat_messages', 'user_id', nullable=False)
    op.alter_column('chat_messages', 'model_key', nullable=False)
    op.drop_table('chat_conversations')
