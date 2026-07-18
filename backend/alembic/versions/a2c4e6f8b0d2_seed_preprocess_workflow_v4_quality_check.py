"""seed standard PREPROCESS workflow v4 — insert quality_check between chunk_split and rag_store

Revision ID: a2c4e6f8b0d2
Revises: e6a8c0d2f4b6
Create Date: 2026-07-17 02:00:00.000000

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a2c4e6f8b0d2'
down_revision: Union[str, None] = 'e6a8c0d2f4b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Same system workflow as v1/v2/v3 — only a new WorkflowVersion is added (v1/v2/v3
# stay untouched, per "활성 버전은 직접 수정하지 않고 새 버전으로 저장한다").
# _resolve_preprocess_version_id (documents.py) already picks the latest
# published version by version_number DESC, so no application code change
# is needed for new uploads to pick this up.
_SYSTEM_WORKFLOW_ID = '00000000-0000-0000-0000-0000000000f1'
_SYSTEM_VERSION_ID = '00000000-0000-0000-0000-0000000000f5'
_SYSTEM_USER_ID = '00000000-0000-0000-0000-000000000001'
# workflow_block_instances.id is a single global primary key (not scoped per
# version_id — confirmed in app/db/models/workflow.py), so unlike a naive
# reading of the v3 migration might suggest, each version's block instances
# need their OWN fresh ids even for block types that are unchanged from the
# prior version — v2 used the 'b*' suffix range, v3 used 'c*', this uses 'd*'.
_BLOCK_IDS = {
    "file_validate": '00000000-0000-0000-0000-0000000000d1',
    "format_detect": '00000000-0000-0000-0000-0000000000d2',
    "text_extract": '00000000-0000-0000-0000-0000000000d3',
    "structure_analyze": '00000000-0000-0000-0000-0000000000d4',
    "text_clean": '00000000-0000-0000-0000-0000000000d5',
    "user_dict": '00000000-0000-0000-0000-0000000000d6',
    "synonym": '00000000-0000-0000-0000-0000000000d7',
    "stopword": '00000000-0000-0000-0000-0000000000d8',
    "pii_detect": '00000000-0000-0000-0000-0000000000d9',
    "chunk_split": '00000000-0000-0000-0000-0000000000da',
    "quality_check": '00000000-0000-0000-0000-0000000000db',
    "rag_store": '00000000-0000-0000-0000-0000000000dc',
    "summarize": '00000000-0000-0000-0000-0000000000dd',
    "extract_keywords": '00000000-0000-0000-0000-0000000000de',
    "output": '00000000-0000-0000-0000-0000000000df',
}
# Linear chain — 설계서 §14 목표 체인의 부분집합(조건분기/OCR 분기는 이번
# 단계 범위 밖, Phase 3부터의 기존 축소 범위). v3 대비 chunk_split과 rag_store
# 사이에 quality_check를 삽입(설계서 §7.3: "rag_store는 chunk_split+quality_check
# 하류").
_CHAIN = [
    "file_validate", "format_detect", "text_extract", "structure_analyze",
    "text_clean", "user_dict", "synonym", "stopword", "pii_detect",
    "chunk_split", "quality_check", "rag_store", "summarize", "extract_keywords", "output",
]


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO workflow_versions "
            "(id, workflow_id, version_number, published_at, created_by, created_at) "
            "VALUES (:id, :workflow_id, 4, now(), :created_by, now())"
        ),
        {"id": _SYSTEM_VERSION_ID, "workflow_id": _SYSTEM_WORKFLOW_ID, "created_by": _SYSTEM_USER_ID},
    )
    for block_type in _CHAIN:
        conn.execute(
            sa.text(
                "INSERT INTO workflow_block_instances "
                "(id, version_id, block_type, label, position, config) "
                "VALUES (:id, :version_id, :block_type, NULL, '{}'::jsonb, '{}'::jsonb)"
            ),
            {"id": _BLOCK_IDS[block_type], "version_id": _SYSTEM_VERSION_ID, "block_type": block_type},
        )
    for from_type, to_type in zip(_CHAIN, _CHAIN[1:]):
        conn.execute(
            sa.text(
                "INSERT INTO workflow_edges (id, version_id, from_block_id, to_block_id, condition) "
                "VALUES (:id, :version_id, :from_id, :to_id, NULL)"
            ),
            {
                "id": str(uuid.uuid4()),
                "version_id": _SYSTEM_VERSION_ID,
                "from_id": _BLOCK_IDS[from_type],
                "to_id": _BLOCK_IDS[to_type],
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM workflow_edges WHERE version_id = :v"), {"v": _SYSTEM_VERSION_ID}
    )
    conn.execute(
        sa.text("DELETE FROM workflow_block_instances WHERE version_id = :v"),
        {"v": _SYSTEM_VERSION_ID},
    )
    conn.execute(sa.text("DELETE FROM workflow_versions WHERE id = :v"), {"v": _SYSTEM_VERSION_ID})
