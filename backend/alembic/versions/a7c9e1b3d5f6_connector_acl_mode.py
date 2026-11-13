"""원천 연결의 권한 기준(파일 서버 권한 또는 컬렉션 권한만)과 로컬 폴더 커넥터

Revision ID: a7c9e1b3d5f6
Revises: e3b5d7f9a1c4
Create Date: 2026-11-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c9e1b3d5f6"
down_revision: Union[str, None] = "e3b5d7f9a1c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 기존 커넥터는 지금처럼 파일 서버 권한을 따른다
    op.add_column("source_connectors", sa.Column(
        "acl_mode", sa.String(length=20), nullable=False, server_default="file_acl"))


def downgrade() -> None:
    op.drop_column("source_connectors", "acl_mode")
