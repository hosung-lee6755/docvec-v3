"""seed standard PREPROCESS workflow v3 — insert structure_analyze and pii_detect

Revision ID: e6a8c0d2f4b6
Revises: d4f6a8b0c2e4
Create Date: 2026-07-16 02:00:00.000000

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e6a8c0d2f4b6'
down_revision: Union[str, None] = 'd4f6a8b0c2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Same system workflow as v1/v2 — only a new WorkflowVersion is added (v1/v2
# stay untouched, per "활성 버전은 직접 수정하지 않고 새 버전으로 저장한다").
# _resolve_preprocess_version_id (documents.py) already picks the latest
# published version by version_number DESC, so no application code change
# is needed for new uploads to pick this up.
_SYSTEM_WORKFLOW_ID = '00000000-0000-0000-0000-0000000000f1'
_SYSTEM_VERSION_ID = '00000000-0000-0000-0000-0000000000f4'
_SYSTEM_USER_ID = '00000000-0000-0000-0000-000000000001'
_BLOCK_IDS = {
    "file_validate": '00000000-0000-0000-0000-0000000000c1',
    "format_detect": '00000000-0000-0000-0000-0000000000c2',
    "text_extract": '00000000-0000-0000-0000-0000000000c3',
    "structure_analyze": '00000000-0000-0000-0000-0000000000c4',
    "text_clean": '00000000-0000-0000-0000-0000000000c5',
    "user_dict": '00000000-0000-0000-0000-0000000000c6',
    "synonym": '00000000-0000-0000-0000-0000000000c7',
    "stopword": '00000000-0000-0000-0000-0000000000c8',
    "pii_detect": '00000000-0000-0000-0000-0000000000c9',
    "chunk_split": '00000000-0000-0000-0000-0000000000ca',
    "rag_store": '00000000-0000-0000-0000-0000000000cb',
    "summarize": '00000000-0000-0000-0000-0000000000cc',
    "extract_keywords": '00000000-0000-0000-0000-0000000000cd',
    "output": '00000000-0000-0000-0000-0000000000ce',
}
# Linear chain — 설계서 §14 목표 체인의 부분집합(조건분기/OCR 분기는 이번
# 단계 범위 밖, Phase 3부터의 기존 축소 범위).
_CHAIN = [
    "file_validate", "format_detect", "text_extract", "structure_analyze",
    "text_clean", "user_dict", "synonym", "stopword", "pii_detect",
    "chunk_split", "rag_store", "summarize", "extract_keywords", "output",
]


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO workflow_versions "
            "(id, workflow_id, version_number, published_at, created_by, created_at) "
            "VALUES (:id, :workflow_id, 3, now(), :created_by, now())"
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
