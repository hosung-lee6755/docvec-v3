"""add document_text_revisions table and documents.tags

Revision ID: e5f6a7b8c9d0
Revises: d8e4b2c7a9f1
Create Date: 2026-07-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd8e4b2c7a9f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('tags', sa.JSON(), nullable=True))
    op.create_table(
        'document_text_revisions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'document_id',
            UUID(as_uuid=True),
            sa.ForeignKey('documents.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('source', sa.String(20), nullable=False),
        sa.Column('parsed_text', sa.Text(), nullable=False),
        sa.Column('created_by', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index(
        'ix_document_text_revisions_document_id', 'document_text_revisions', ['document_id']
    )


def downgrade() -> None:
    op.drop_index('ix_document_text_revisions_document_id', table_name='document_text_revisions')
    op.drop_table('document_text_revisions')
    op.drop_column('documents', 'tags')
