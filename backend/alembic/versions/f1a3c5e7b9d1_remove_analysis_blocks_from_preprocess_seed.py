"""remove leftover ANALYSIS blocks (summarize/extract_keywords/output) from the seeded standard PREPROCESS workflow

Revision ID: f1a3c5e7b9d1
Revises: c4e6a8b0d2f4
Create Date: 2026-07-20 08:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f1a3c5e7b9d1'
down_revision: Union[str, None] = 'c4e6a8b0d2f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# c2d4e6f8a0b1(v1)/d4f6a8b0c2e4(v2)/e6a8c0d2f4b6(v3)/a2c4e6f8b0d2(v4) all seeded
# "표준 전처리 워크플로우" with a copy-pasted tail of summarize/extract_keywords/
# output — ANALYSIS-category blocks (category="분석" in their own block classes,
# output writes doc.summary/tags) that don't belong in a PREPROCESS pipeline.
# Every migration after v1 inserted new PREPROCESS blocks in the middle of the
# chain but never dropped this leftover tail. rag_store is the correct/intended
# terminus (validate_graph already enforces "정확히 1개의 rag_store" for
# PREPROCESS workflows); this migration makes it the actual graph terminus too.
_SYSTEM_VERSION_IDS = [
    '00000000-0000-0000-0000-0000000000f2',  # v1
    '00000000-0000-0000-0000-0000000000f3',  # v2
    '00000000-0000-0000-0000-0000000000f4',  # v3
    '00000000-0000-0000-0000-0000000000f5',  # v4
]
_ANALYSIS_LEFTOVER_TYPES = ('summarize', 'extract_keywords', 'output')


_SYSTEM_WORKFLOW_ID = '00000000-0000-0000-0000-0000000000f1'


def upgrade() -> None:
    conn = op.get_bind()
    # Original description (v1 seed) ends "...→요약→키워드→출력", which is no
    # longer true once the blocks below are removed.
    conn.execute(
        sa.text(
            "UPDATE workflow_definitions SET description = "
            "'시스템 기본 제공 — 파일검증→형식판별→텍스트추출→구조분석→정제·정규화→"
            "민감정보탐지→분할→품질검증→RAG저장' WHERE id = :w"
        ),
        {"w": _SYSTEM_WORKFLOW_ID},
    )
    for version_id in _SYSTEM_VERSION_IDS:
        leftover_ids = [
            row[0] for row in conn.execute(
                sa.text(
                    "SELECT id FROM workflow_block_instances "
                    "WHERE version_id = :v AND block_type = ANY(:types)"
                ),
                {"v": version_id, "types": list(_ANALYSIS_LEFTOVER_TYPES)},
            ).fetchall()
        ]
        if not leftover_ids:
            continue
        conn.execute(
            sa.text(
                "DELETE FROM workflow_edges WHERE version_id = :v "
                "AND (from_block_id = ANY(:ids) OR to_block_id = ANY(:ids))"
            ),
            {"v": version_id, "ids": leftover_ids},
        )
        conn.execute(
            sa.text("DELETE FROM workflow_block_instances WHERE id = ANY(:ids)"),
            {"ids": leftover_ids},
        )


def downgrade() -> None:
    # One-way cleanup of a seeding bug — no reasonable inverse (would need to
    # regenerate deterministic block ids and re-link edges per version).
    pass
