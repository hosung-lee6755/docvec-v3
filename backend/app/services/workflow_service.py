"""Graph validation for workflow versions — run before save (draft) and
required to pass before publish/run (저장 전 워크플로우 유효성 검사를 수행한다)."""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models.workflow import WorkflowBlockInstance, WorkflowEdge
from app.pipeline.blocks.registry import BLOCK_REGISTRY


async def validate_graph(db: AsyncSession, version_id: str) -> list[str]:
    """Returns a list of human-readable (Korean) validation errors. Empty
    list means the graph is valid."""
    errors: list[str] = []

    blocks = (
        await db.scalars(
            select(WorkflowBlockInstance).where(WorkflowBlockInstance.version_id == version_id)
        )
    ).all()
    edges = (
        await db.scalars(select(WorkflowEdge).where(WorkflowEdge.version_id == version_id))
    ).all()

    if not blocks:
        return ["워크플로우에 블록이 하나도 없습니다"]

    block_by_id = {str(b.id): b for b in blocks}
    incoming: dict[str, list[WorkflowEdge]] = {str(b.id): [] for b in blocks}
    outgoing: dict[str, list[WorkflowEdge]] = {str(b.id): [] for b in blocks}
    for e in edges:
        outgoing.setdefault(str(e.from_block_id), []).append(e)
        incoming.setdefault(str(e.to_block_id), []).append(e)

    for block in blocks:
        if block.block_type not in BLOCK_REGISTRY:
            errors.append(f"'{block.label or block.id}' 블록의 유형이 올바르지 않습니다: {block.block_type}")
        if block.block_type != "input" and not incoming.get(str(block.id)):
            errors.append(f"'{block.label or block.id}' 블록에 연결된 입력이 없습니다")
        if block.block_type != "output" and not outgoing.get(str(block.id)):
            errors.append(f"'{block.label or block.id}' 블록에 연결된 출력이 없습니다")

    cycle_error = _find_cycle(block_by_id, outgoing)
    if cycle_error:
        errors.append(cycle_error)

    return errors


def _find_cycle(
    block_by_id: dict[str, WorkflowBlockInstance],
    outgoing: dict[str, list[WorkflowEdge]],
) -> str | None:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {block_id: WHITE for block_id in block_by_id}

    def visit(block_id: str) -> bool:
        color[block_id] = GRAY
        for edge in outgoing.get(block_id, []):
            target_id = str(edge.to_block_id)
            if color.get(target_id) == GRAY:
                return True
            if color.get(target_id) == WHITE and visit(target_id):
                return True
        color[block_id] = BLACK
        return False

    for block_id in block_by_id:
        if color[block_id] == WHITE and visit(block_id):
            return "워크플로우에 순환 참조(cycle)가 있습니다"
    return None
