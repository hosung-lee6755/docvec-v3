"""add unique constraint on workflow_run_steps (run_id, block_instance_id)

이 마이그레이션은 Defect 5 (fan-in 경합)을 수정한다.
step 조회-후-삽입에서 중복 step이 생기는 것을 방지하기 위해
(run_id, block_instance_id)에 UNIQUE 제약을 추가한다.

기존 중복 행이 있다면, 가장 최근의 rows를 보존하고 나머지는 삭제한다.

Revision ID: 1a2b3c4d5e6f
Revises: 182b35eff691
Create Date: 2026-10-08 16:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a2b3c4d5e6f'
down_revision: Union[str, None] = '182b35eff691'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 중복 제거: UUID 컬럼에는 MAX()가 작동하지 않으므로, 각 (run_id, block_instance_id)
    # 그룹에서 가장 최근 row (created_at 기준)를 보존하고 나머지는 삭제한다.
    # CTE를 사용해 ForeignKey CASCADE 관계를 자동 처리하고 orphaned FK를 피한다.
    op.execute("""
        WITH duplicates_to_keep AS (
            SELECT DISTINCT ON (run_id, block_instance_id)
                id
            FROM workflow_run_steps
            ORDER BY run_id, block_instance_id, created_at DESC
        ),
        duplicates_to_delete AS (
            SELECT id FROM workflow_run_steps
            WHERE id NOT IN (SELECT id FROM duplicates_to_keep)
        )
        DELETE FROM workflow_run_steps
        WHERE id IN (SELECT id FROM duplicates_to_delete)
    """)

    # 이제 고유 제약을 추가할 수 있다
    op.create_unique_constraint(
        'uq_workflow_run_steps_run_id_block_instance_id',
        'workflow_run_steps',
        ['run_id', 'block_instance_id']
    )


def downgrade() -> None:
    op.drop_constraint(
        'uq_workflow_run_steps_run_id_block_instance_id',
        'workflow_run_steps',
        type_='unique'
    )
