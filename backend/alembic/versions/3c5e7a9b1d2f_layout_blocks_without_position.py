"""lay out workflow blocks that were saved without canvas coordinates

시드/API 로 만든 워크플로우(표준 전처리 v1~v4)는 블록의 position 이 `{}` 로 저장돼 편집기에서 모든
블록이 (0,0) 한 점에 겹쳐 보인다. 좌표가 없는 블록에만 위상 순서대로 위→아래(6개씩, 다음 열로) 배치를 채운다.
이미 좌표가 있는 블록(문서 분석 워크플로우 등)은 건드리지 않는다. position 은 캔버스 표시 전용이라
실행·캐시 키(config_hash)에는 영향이 없다.

배치 규칙은 프런트 `lib/workflowLayout.ts::fallbackPosition` 과 같다(열당 6개, 가로 360, 세로 130).
블록 카드(약 287×68)의 연결 핸들이 위(입력)·아래(출력)라 위에서 아래로 흐르게 놓는다.

Revision ID: 3c5e7a9b1d2f
Revises: 1a2b3c4d5e6f
Create Date: 2026-10-12 17:30:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3c5e7a9b1d2f'
down_revision: Union[str, None] = '1a2b3c4d5e6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LAYOUT_ROWS = 6
LAYOUT_X_GAP = 360
LAYOUT_Y_GAP = 130


def _fallback_position(index: int, y_offset: int = 0) -> dict:
    column, row = divmod(index, LAYOUT_ROWS)
    return {"x": column * LAYOUT_X_GAP, "y": y_offset + row * LAYOUT_Y_GAP}


def _has_position(position) -> bool:
    return (
        isinstance(position, dict)
        and isinstance(position.get("x"), (int, float))
        and isinstance(position.get("y"), (int, float))
    )


def _topological_order(block_ids: list[str], edges: list[tuple[str, str]]) -> list[str]:
    """가장 긴 경로 깊이(깊이 같으면 id 순)로 정렬한 블록 순서. 순환이 있어도 깊이 상한으로 끝난다."""
    depth = {block_id: 0 for block_id in block_ids}
    for _ in range(len(block_ids)):
        changed = False
        for source, target in edges:
            if source in depth and target in depth and depth[target] < depth[source] + 1:
                depth[target] = depth[source] + 1
                changed = True
        if not changed:
            break
    return sorted(block_ids, key=lambda block_id: (depth[block_id], str(block_id)))


def _layout_positions(blocks: list[tuple[str, object]], edges: list[tuple[str, str]]) -> dict[str, dict]:
    """좌표가 없는 블록에만 새 position 을 돌려준다(이미 있는 블록은 결과에 없음)."""
    missing = [block_id for block_id, position in blocks if not _has_position(position)]
    if not missing:
        return {}
    placed_y = [position["y"] for _, position in blocks if _has_position(position)]
    # 일부만 좌표가 있으면 기존 블록 아래 새 줄부터 놓아 겹치지 않게 한다.
    y_offset = int(max(placed_y) + LAYOUT_Y_GAP) if placed_y else 0
    ordered = _topological_order(missing, [(s, t) for s, t in edges if s in missing and t in missing])
    return {block_id: _fallback_position(index, y_offset) for index, block_id in enumerate(ordered)}


def upgrade() -> None:
    bind = op.get_bind()
    version_ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM workflow_versions")).fetchall()]
    for version_id in version_ids:
        blocks = [
            (str(row[0]), row[1])
            for row in bind.execute(
                sa.text("SELECT id, position FROM workflow_block_instances WHERE version_id = :v"),
                {"v": version_id},
            ).fetchall()
        ]
        edges = [
            (str(row[0]), str(row[1]))
            for row in bind.execute(
                sa.text("SELECT from_block_id, to_block_id FROM workflow_edges WHERE version_id = :v"),
                {"v": version_id},
            ).fetchall()
        ]
        for block_id, position in _layout_positions(blocks, edges).items():
            bind.execute(
                sa.text("UPDATE workflow_block_instances SET position = CAST(:p AS json) WHERE id = :i"),
                {"p": json.dumps(position), "i": block_id},
            )


def downgrade() -> None:
    # 이전 값은 모두 빈 객체였고 사용자가 편집기에서 옮긴 좌표와 구분할 수 없어 되돌리지 않는다.
    pass
