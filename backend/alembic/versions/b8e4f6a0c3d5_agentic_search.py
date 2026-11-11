"""v3 agentic (deep) search mode on chat messages and answer traces

Revision ID: b8e4f6a0c3d5
Revises: a7d3e5f9b2c4
Create Date: 2026-11-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8e4f6a0c3d5"
down_revision: Union[str, None] = "a7d3e5f9b2c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("chat_messages", "answer_traces")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("mode", sa.String(10), nullable=False, server_default="standard"))
        op.add_column(table, sa.Column("agent_steps", sa.JSON(), nullable=True))


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "agent_steps")
        op.drop_column(table, "mode")
