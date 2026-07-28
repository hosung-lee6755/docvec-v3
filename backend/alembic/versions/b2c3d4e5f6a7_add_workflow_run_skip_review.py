"""add workflow_runs.skip_review

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-24 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 9항목 펀치리스트 #1 — 업로드 시 "검토 없이 진행"을 선택하면 이 run에
    # 한해 quality_check의 review_policy를 auto_pass로 낮춘다
    # (app/pipeline/blocks/quality_blocks.py). 기존 timeout_overrides와
    # 동일한 run-level override 컬럼.
    op.add_column(
        "workflow_runs",
        sa.Column("skip_review", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "skip_review")
