"""documents 에 업로드 때 고른 분석 워크플로우(analysis_workflow_id)를 더한다.

문서 업로드 창에서 전처리 워크플로우만 고를 수 있었다(2026-11-24 사용자 지적). 고른 분석 워크플로우를 문서에
남겨, 전처리가 끝난 뒤의 자동 분석과 재처리 뒤의 분석이 컬렉션 기본보다 먼저 이것을 쓴다.

Revision ID: e4a6c8b0d2f5
Revises: d3f5a7b9c1e4
Create Date: 2026-11-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e4a6c8b0d2f5"
down_revision: str | None = "d3f5a7b9c1e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("analysis_workflow_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_documents_analysis_workflow_id_workflow_definitions", "documents", "workflow_definitions",
        ["analysis_workflow_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_documents_analysis_workflow_id_workflow_definitions", "documents", type_="foreignkey")
    op.drop_column("documents", "analysis_workflow_id")
