"""AD가 없는 회사의 계정 관리: 임시 비밀번호 표시와 세션 버전

Revision ID: e3b5d7f9a1c4
Revises: d1a3c5e7f9b2
Create Date: 2026-11-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3b5d7f9a1c4"
down_revision: Union[str, None] = "d1a3c5e7f9b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 관리자가 발급하거나 초기화한 임시 비밀번호는 첫 로그인 뒤 바꿔야 한다
    op.add_column("users", sa.Column(
        "must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()))
    # 토큰에 실린 값과 다르면 그 토큰을 거절한다. 비밀번호를 초기화하면 1 올려 기존 로그인을 끊는다
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("users", "token_version")
    op.drop_column("users", "must_change_password")
