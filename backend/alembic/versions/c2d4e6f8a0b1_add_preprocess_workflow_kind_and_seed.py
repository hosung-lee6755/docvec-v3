"""add workflow_definitions.kind + nullable project_id + seed standard PREPROCESS workflow

Revision ID: c2d4e6f8a0b1
Revises: b7e3f9a1c5d8
Create Date: 2026-07-16 00:00:00.000000

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c2d4e6f8a0b1'
down_revision: Union[str, None] = 'b7e3f9a1c5d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Deterministic ids so upgrade()/downgrade() can reference the same rows.
_SYSTEM_WORKFLOW_ID = '00000000-0000-0000-0000-0000000000f1'
_SYSTEM_VERSION_ID = '00000000-0000-0000-0000-0000000000f2'
_SYSTEM_USER_ID = '00000000-0000-0000-0000-000000000001'
_BLOCK_IDS = {
    "file_validate": '00000000-0000-0000-0000-0000000000a1',
    "format_detect": '00000000-0000-0000-0000-0000000000a2',
    "text_extract": '00000000-0000-0000-0000-0000000000a3',
    "chunk_split": '00000000-0000-0000-0000-0000000000a4',
    "rag_store": '00000000-0000-0000-0000-0000000000a5',
    "summarize": '00000000-0000-0000-0000-0000000000a6',
    "extract_keywords": '00000000-0000-0000-0000-0000000000a7',
    "output": '00000000-0000-0000-0000-0000000000a8',
}
# Linear chain, in this order.
_CHAIN = [
    "file_validate", "format_detect", "text_extract", "chunk_split",
    "rag_store", "summarize", "extract_keywords", "output",
]


def upgrade() -> None:
    # --- workflow_definitions: allow system-owned (project_id NULL) rows ------
    op.alter_column('workflow_definitions', 'project_id', nullable=True)

    workflow_definition_kind = sa.Enum('PREPROCESS', 'ANALYSIS', name='workflow_definition_kind')
    workflow_definition_kind.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'workflow_definitions',
        sa.Column('kind', workflow_definition_kind, nullable=False, server_default='ANALYSIS'),
    )

    # --- seed: system 표준 전처리 워크플로우 (project_id=NULL, kind=PREPROCESS) --
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO workflow_definitions "
            "(id, project_id, name, description, status, kind, created_by, created_at, updated_at) "
            "VALUES (:id, NULL, :name, :description, 'ACTIVE', 'PREPROCESS', :created_by, now(), now())"
        ),
        {
            "id": _SYSTEM_WORKFLOW_ID,
            "name": "표준 전처리 워크플로우",
            "description": "시스템 기본 제공 — 파일검증→형식판별→텍스트추출→분할→RAG저장→요약→키워드→출력",
            "created_by": _SYSTEM_USER_ID,
        },
    )
    conn.execute(
        sa.text(
            "INSERT INTO workflow_versions "
            "(id, workflow_id, version_number, published_at, created_by, created_at) "
            "VALUES (:id, :workflow_id, 1, now(), :created_by, now())"
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
    conn.execute(
        sa.text("DELETE FROM workflow_definitions WHERE id = :w"), {"w": _SYSTEM_WORKFLOW_ID}
    )

    op.drop_column('workflow_definitions', 'kind')
    sa.Enum(name='workflow_definition_kind').drop(op.get_bind(), checkfirst=True)
    op.alter_column('workflow_definitions', 'project_id', nullable=False)
