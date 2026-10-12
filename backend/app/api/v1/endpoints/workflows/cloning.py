"""버전 간 그래프(블록·엣지) 복제 — 새 초안 버전 생성과 워크플로우 복제가 함께 쓴다."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow import WorkflowBlockInstance, WorkflowEdge


async def clone_graph(db: AsyncSession, source_version_id, target_version_id) -> None:
    """source 버전의 블록/엣지를 target 버전으로 복사한다. 새 블록 id가 필요해
    블록마다 flush 하며, 커밋은 호출자가 한다."""
    source_blocks = (
        await db.scalars(
            select(WorkflowBlockInstance).where(WorkflowBlockInstance.version_id == source_version_id)
        )
    ).all()
    source_edges = (
        await db.scalars(select(WorkflowEdge).where(WorkflowEdge.version_id == source_version_id))
    ).all()

    id_map: dict[str, str] = {}
    for block in source_blocks:
        new_block = WorkflowBlockInstance(
            version_id=target_version_id,
            block_type=block.block_type,
            label=block.label,
            position=block.position,
            config=block.config,
        )
        db.add(new_block)
        await db.flush()
        id_map[str(block.id)] = str(new_block.id)

    for edge in source_edges:
        db.add(WorkflowEdge(
            version_id=target_version_id,
            from_block_id=id_map[str(edge.from_block_id)],
            to_block_id=id_map[str(edge.to_block_id)],
            condition=edge.condition,
        ))
