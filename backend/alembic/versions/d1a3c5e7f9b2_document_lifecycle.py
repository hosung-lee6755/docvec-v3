"""v3 milestone 7: document versions and lifecycle, asynchronous golden evaluation with baseline and regression

Revision ID: d1a3c5e7f9b2
Revises: c9f1a3b5d7e9
Create Date: 2026-11-12 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d1a3c5e7f9b2"
down_revision: Union[str, None] = "c9f1a3b5d7e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 문서 버전과 수명주기. 기존 문서는 각자 한 계보의 1번 버전이고 현재 버전이다.
    op.add_column("documents", sa.Column("lineage_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("documents", sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("documents", sa.Column(
        "lifecycle_state", sa.String(20), nullable=False, server_default="current"))
    op.add_column("documents", sa.Column("expires_at", sa.DateTime(), nullable=True))
    op.add_column("documents", sa.Column("archived_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE documents SET lineage_id = id WHERE lineage_id IS NULL")
    op.alter_column("documents", "lineage_id", nullable=False)
    op.create_index("ix_documents_lineage_id", "documents", ["lineage_id"])
    op.create_index("ix_documents_collection_lifecycle", "documents", ["collection_id", "lifecycle_state"])
    op.create_index("ix_documents_expires_at", "documents", ["expires_at"])
    # 계보마다 현재 버전은 하나, 버전 번호는 겹치지 않는다(동시 승격·동시 업로드 방어)
    op.create_index("uq_documents_lineage_current", "documents", ["lineage_id"], unique=True,
                    postgresql_where=sa.text("lifecycle_state = 'current'"))
    op.create_unique_constraint("uq_documents_lineage_version", "documents", ["lineage_id", "version_number"])

    # 골든 평가는 워커에서 비동기로 돈다. 기존 실행은 끝난(DONE) 수동 실행이다.
    op.alter_column("golden_eval_runs", "mean_precision", nullable=True)
    op.alter_column("golden_eval_runs", "mean_recall", nullable=True)
    op.alter_column("golden_eval_runs", "results", nullable=True)
    op.add_column("golden_eval_runs", sa.Column("status", sa.String(20), nullable=False, server_default="DONE"))
    op.add_column("golden_eval_runs", sa.Column("trigger", sa.String(30), nullable=False, server_default="manual"))
    op.add_column("golden_eval_runs", sa.Column("mean_hit_rate", sa.Float(), nullable=True))
    op.add_column("golden_eval_runs", sa.Column("mean_mrr", sa.Float(), nullable=True))
    op.add_column("golden_eval_runs", sa.Column(
        "is_baseline", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("golden_eval_runs", sa.Column("is_regression", sa.Boolean(), nullable=True))
    op.add_column("golden_eval_runs", sa.Column("regression", sa.JSON(), nullable=True))
    op.add_column("golden_eval_runs", sa.Column("search_settings", sa.JSON(), nullable=True))
    op.add_column("golden_eval_runs", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column("golden_eval_runs", sa.Column("completed_at", sa.DateTime(), nullable=True))
    op.create_index("ix_golden_eval_runs_collection_status", "golden_eval_runs", ["collection_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_golden_eval_runs_collection_status", table_name="golden_eval_runs")
    for col in ("completed_at", "error_message", "search_settings", "regression", "is_regression",
                "is_baseline", "mean_mrr", "mean_hit_rate", "trigger", "status"):
        op.drop_column("golden_eval_runs", col)
    op.execute("DELETE FROM golden_eval_runs WHERE mean_precision IS NULL OR mean_recall IS NULL OR results IS NULL")
    op.alter_column("golden_eval_runs", "results", nullable=False)
    op.alter_column("golden_eval_runs", "mean_recall", nullable=False)
    op.alter_column("golden_eval_runs", "mean_precision", nullable=False)
    op.drop_constraint("uq_documents_lineage_version", "documents", type_="unique")
    op.drop_index("uq_documents_lineage_current", table_name="documents")
    op.drop_index("ix_documents_expires_at", table_name="documents")
    op.drop_index("ix_documents_collection_lifecycle", table_name="documents")
    op.drop_index("ix_documents_lineage_id", table_name="documents")
    for col in ("archived_at", "expires_at", "lifecycle_state", "version_number", "lineage_id"):
        op.drop_column("documents", col)
