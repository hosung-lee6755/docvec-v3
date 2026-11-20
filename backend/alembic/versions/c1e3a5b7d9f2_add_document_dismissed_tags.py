"""add documents.dismissed_tags (사용자가 무시한 추천 태그)

분석 출력 블록이 추천 태그를 이전 실행 값과 합치지 않고 이번 실행 결과로 바꿔 넣게 되면서(2026-11-20),
사용자가 무시한 태그를 기억할 곳이 필요해졌다. 기억하지 않으면 다음 분석이 같은 태그를 다시 제안한다.

Revision ID: c1e3a5b7d9f2
Revises: b9d1f3a5c7e9
Create Date: 2026-11-20 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1e3a5b7d9f2"
down_revision: str | None = "b9d1f3a5c7e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("dismissed_tags", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "dismissed_tags")
