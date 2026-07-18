"""seed standard PREPROCESS workflow v2 — insert text_clean/user_dict/synonym/stopword

Revision ID: d4f6a8b0c2e4
Revises: c2d4e6f8a0b1
Create Date: 2026-07-16 01:00:00.000000

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4f6a8b0c2e4'
down_revision: Union[str, None] = 'c2d4e6f8a0b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Same system workflow definition as v1 (c2d4e6f8a0b1) — this migration only
# adds a new WorkflowVersion (v1 stays untouched, per "활성 버전은 직접 수정하지
# 않고 새 버전으로 저장한다"). _resolve_preprocess_version_id (documents.py)
# already picks the latest published version by version_number DESC, so no
# application code needs to change for new uploads to pick this up.
_SYSTEM_WORKFLOW_ID = '00000000-0000-0000-0000-0000000000f1'
_SYSTEM_VERSION_ID = '00000000-0000-0000-0000-0000000000f3'
_SYSTEM_USER_ID = '00000000-0000-0000-0000-000000000001'
_BLOCK_IDS = {
    "file_validate": '00000000-0000-0000-0000-0000000000b1',
    "format_detect": '00000000-0000-0000-0000-0000000000b2',
    "text_extract": '00000000-0000-0000-0000-0000000000b3',
    "text_clean": '00000000-0000-0000-0000-0000000000b4',
    "user_dict": '00000000-0000-0000-0000-0000000000b5',
    "synonym": '00000000-0000-0000-0000-0000000000b6',
    "stopword": '00000000-0000-0000-0000-0000000000b7',
    "chunk_split": '00000000-0000-0000-0000-0000000000b8',
    "rag_store": '00000000-0000-0000-0000-0000000000b9',
    "summarize": '00000000-0000-0000-0000-0000000000ba',
    "extract_keywords": '00000000-0000-0000-0000-0000000000bb',
    "output": '00000000-0000-0000-0000-0000000000bc',
}
# Linear chain — 사용자사전→동의어→불용어 순서는 설계서 §9.5 권장 배치
# (사용자 사전 보호 -> 동의어 -> 불용어).
_CHAIN = [
    "file_validate", "format_detect", "text_extract", "text_clean",
    "user_dict", "synonym", "stopword", "chunk_split",
    "rag_store", "summarize", "extract_keywords", "output",
]


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO workflow_versions "
            "(id, workflow_id, version_number, published_at, created_by, created_at) "
            "VALUES (:id, :workflow_id, 2, now(), :created_by, now())"
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
