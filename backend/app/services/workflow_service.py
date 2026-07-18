"""Graph validation for workflow versions — run before save (draft) and
required to pass before publish/run (저장 전 워크플로우 유효성 검사를 수행한다)."""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models.workflow import WorkflowBlockInstance, WorkflowDefinition, WorkflowEdge, WorkflowVersion
from app.pipeline.blocks.registry import BLOCK_REGISTRY, BLOCK_TYPE_LABELS

# 이 블록 타입이 그래프에 존재하려면, 그 상류(역방향 도달 가능 집합)에 반드시
# 이 타입들이 있어야 한다 — 통합 설계서 §7.3. 아직 없는 블록 타입(structure_
# analyze 등)이 생기면 이 표에 추가한다.
_REQUIRES_UPSTREAM: dict[str, set[str]] = {
    "text_extract": {"format_detect"},
    "structure_analyze": {"text_extract"},
    "text_clean": {"text_extract"},
    "pii_detect": {"text_extract"},
    "chunk_split": {"text_clean"},
    "quality_check": {"chunk_split"},
    "rag_store": {"chunk_split", "quality_check"},
}


def _display_names(blocks: list[WorkflowBlockInstance]) -> dict[str, str]:
    """Human-readable name per block id for error messages: the user-given
    label if set, otherwise the Korean block-type name — numbered ("전처리 2")
    when the same unlabeled type appears more than once."""
    type_counts: dict[str, int] = {}
    for b in blocks:
        if not b.label:
            type_counts[b.block_type] = type_counts.get(b.block_type, 0) + 1

    names: dict[str, str] = {}
    type_seen: dict[str, int] = {}
    for b in blocks:
        if b.label:
            names[str(b.id)] = b.label
            continue
        base = BLOCK_TYPE_LABELS.get(b.block_type, b.block_type)
        type_seen[b.block_type] = type_seen.get(b.block_type, 0) + 1
        if type_counts.get(b.block_type, 0) > 1:
            names[str(b.id)] = f"{base} {type_seen[b.block_type]}"
        else:
            names[str(b.id)] = base
    return names


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

    names = _display_names(list(blocks))
    for block in blocks:
        name = names[str(block.id)]
        if block.block_type not in BLOCK_REGISTRY:
            errors.append(f"'{name}' 블록의 유형이 올바르지 않습니다: {block.block_type}")
        # "input"은 ANALYSIS 워크플로우의 진입 블록, "file_validate"는 PREPROCESS
        # 워크플로우의 진입 블록 — 둘 다 들어오는 edge가 없는 게 정상이다.
        if block.block_type not in ("input", "file_validate") and not incoming.get(str(block.id)):
            errors.append(f"'{name}' 블록에 연결된 입력이 없습니다")
        if block.block_type != "output" and not outgoing.get(str(block.id)):
            errors.append(f"'{name}' 블록에 연결된 출력이 없습니다")

    cycle_error = _find_cycle(block_by_id, outgoing)
    if cycle_error:
        errors.append(cycle_error)

    for block in blocks:
        required = _REQUIRES_UPSTREAM.get(block.block_type)
        if not required:
            continue
        reachable = _upstream_block_types(str(block.id), block_by_id, incoming)
        missing = required - reachable
        if missing:
            name = names[str(block.id)]
            errors.append(f"'{name}' 블록은 상류에 {', '.join(sorted(missing))} 블록이 필요합니다")

    version = await db.get(WorkflowVersion, version_id)
    workflow = await db.get(WorkflowDefinition, version.workflow_id) if version else None
    if workflow is not None and workflow.kind == "PREPROCESS":
        entry_file_validates = [
            b for b in blocks if b.block_type == "file_validate" and not incoming.get(str(b.id))
        ]
        if len(entry_file_validates) != 1:
            errors.append("전처리(PREPROCESS) 워크플로우는 진입 블록이 '파일 검증' 정확히 1개여야 합니다")
        rag_stores = [b for b in blocks if b.block_type == "rag_store"]
        if len(rag_stores) != 1:
            errors.append("전처리(PREPROCESS) 워크플로우는 'RAG 저장' 블록이 정확히 1개여야 합니다")

    return errors


def _upstream_block_types(
    block_id: str,
    block_by_id: dict[str, WorkflowBlockInstance],
    incoming: dict[str, list[WorkflowEdge]],
) -> set[str]:
    """All block types reachable by walking incoming edges backward from
    `block_id` (excluding `block_id` itself)."""
    seen: set[str] = set()
    stack = [block_id]
    visited_ids: set[str] = set()
    while stack:
        current = stack.pop()
        if current in visited_ids:
            continue
        visited_ids.add(current)
        for edge in incoming.get(current, []):
            source_id = str(edge.from_block_id)
            source = block_by_id.get(source_id)
            if source is not None:
                seen.add(source.block_type)
            stack.append(source_id)
    return seen


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
