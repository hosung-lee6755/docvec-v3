"""seed the system standard ANALYSIS workflow (요약, 키워드, 분류)

전처리가 끝난 문서를 컬렉션에 분석 워크플로우가 없을 때 분석하는 시스템 표준 분석 워크플로우다(2026-11-20).
예전에는 분석 워크플로우가 없으면 워크플로우 밖에서 요약, 메타데이터 작업을 직접 보냈다. 처리 이력에 남지 않고
화면에서 고칠 수도 없었다. 이제 workflow._resolve_analysis_version 이 이 워크플로우(고정 ID)를 고른다.

사슬은 입력 → 요약 → 키워드 → 분류 → 출력이다. 출력은 문서에 저장하고, 분류를 추천 태그에 넣지 않는다
(예전 작업은 분류를 태그로 넣지 않았다).

Revision ID: b9d1f3a5c7e9
Revises: e5b7d9f1a3c6
Create Date: 2026-11-20 00:00:00.000000

"""
import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9d1f3a5c7e9"
down_revision: str | None = "e5b7d9f1a3c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# workflow.STANDARD_ANALYSIS_WORKFLOW_ID 와 같아야 한다
_WORKFLOW_ID = "00000000-0000-0000-0000-0000000000e1"
_VERSION_ID = "00000000-0000-0000-0000-0000000000e2"
_SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000001"
_CHAIN = [
    ("00000000-0000-0000-0000-0000000000e3", "input", {}),
    ("00000000-0000-0000-0000-0000000000e4", "summarize", {"format": "paragraph"}),
    ("00000000-0000-0000-0000-0000000000e5", "extract_keywords", {"max_keywords": 10}),
    ("00000000-0000-0000-0000-0000000000e6", "classify", {}),
    ("00000000-0000-0000-0000-0000000000e7", "output", {"save_to_document": True, "category_as_tag": False}),
]
_ROW_GAP = 130


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO workflow_definitions "
            "(id, project_id, name, description, status, kind, created_by, created_at, updated_at) "
            "VALUES (:id, NULL, :name, :description, 'ACTIVE', 'ANALYSIS', :created_by, now(), now()) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": _WORKFLOW_ID,
            "name": "표준 분석 워크플로우",
            "description": "시스템 기본 제공. 입력, 요약, 키워드, 분류, 출력(문서에 저장) 순서로 실행합니다.",
            "created_by": _SYSTEM_USER_ID,
        },
    )
    conn.execute(
        sa.text(
            "INSERT INTO workflow_versions (id, workflow_id, version_number, published_at, created_by, created_at) "
            "VALUES (:id, :workflow_id, 1, now(), :created_by, now()) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": _VERSION_ID, "workflow_id": _WORKFLOW_ID, "created_by": _SYSTEM_USER_ID},
    )
    for index, (block_id, block_type, config) in enumerate(_CHAIN):
        conn.execute(
            sa.text(
                "INSERT INTO workflow_block_instances (id, version_id, block_type, label, position, config) "
                "VALUES (:id, :version_id, :block_type, NULL, CAST(:position AS json), CAST(:config AS json)) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": block_id, "version_id": _VERSION_ID, "block_type": block_type,
                "position": json.dumps({"x": 0, "y": _ROW_GAP * index}), "config": json.dumps(config),
            },
        )
    for (from_id, _, _), (to_id, _, _) in zip(_CHAIN, _CHAIN[1:], strict=False):
        conn.execute(
            sa.text(
                "INSERT INTO workflow_edges (id, version_id, from_block_id, to_block_id, condition) "
                "SELECT :id, :version_id, :from_id, :to_id, NULL WHERE NOT EXISTS ("
                "SELECT 1 FROM workflow_edges WHERE version_id = :version_id "
                "AND from_block_id = :from_id AND to_block_id = :to_id)"
            ),
            {"id": str(uuid.uuid4()), "version_id": _VERSION_ID, "from_id": from_id, "to_id": to_id},
        )


def downgrade() -> None:
    conn = op.get_bind()
    # 이 워크플로우로 돈 실행 기록이 있으면 버전을 지울 수 없다. 기록을 지우지 않고 실패하게 둔다
    conn.execute(sa.text("DELETE FROM workflow_edges WHERE version_id = :v"), {"v": _VERSION_ID})
    conn.execute(sa.text("DELETE FROM workflow_block_instances WHERE version_id = :v"), {"v": _VERSION_ID})
    conn.execute(sa.text("DELETE FROM workflow_versions WHERE id = :v"), {"v": _VERSION_ID})
    conn.execute(sa.text("DELETE FROM workflow_definitions WHERE id = :w"), {"w": _WORKFLOW_ID})
