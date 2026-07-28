"""add workflow_runs.timeout_overrides

Revision ID: d1e3f5a7b9c1
Revises: c8b0d5e2f4a6
Create Date: 2026-07-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd1e3f5a7b9c1'
down_revision: Union[str, None] = 'c8b0d5e2f4a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Per-run {block_type: timeoutSeconds} override, read by the DAG executor
    # (app/pipeline/tasks/workflow.py) ahead of the block's own persisted
    # config.timeoutSeconds. Lets a stuck run be retried with a longer Celery
    # hard time limit without mutating the shared WorkflowBlockInstance.config
    # (which would affect every other document on the same workflow version).
    op.add_column("workflow_runs", sa.Column("timeout_overrides", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("workflow_runs", "timeout_overrides")
