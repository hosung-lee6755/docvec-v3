"""user_groups.previous_group_id: AD에서 다시 생긴 그룹이 이어받을 수 있는 예전 그룹 id

Revision ID: b9d1f3a5c7e8
Revises: a7c9e1b3d5f6
Create Date: 2026-11-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b9d1f3a5c7e8"
down_revision: Union[str, None] = "a7c9e1b3d5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_groups", sa.Column("previous_group_id", postgresql.UUID(as_uuid=True), nullable=True))


def downgrade() -> None:
    op.drop_column("user_groups", "previous_group_id")
