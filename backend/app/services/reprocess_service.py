"""부분 재처리(시작 블록 지정) 오케스트레이션 — 통합 설계서 §8/§4.10.

새 WorkflowRun을 원본 런과 같은 version_id로 만들고, 시작 블록의 하류 폐포
밖(상류) 블록들은 원본 런의 완료된 스텝을 그대로 복사해 재사용한 뒤,
시작 블록만 직접 큐잉한다 — 상류를 다시 실행할 필요가 없다(이미 완료된
그대로이므로). `app/pipeline/tasks/workflow.py`의 실행기(캐시/DAG 진행)는
전혀 건드리지 않고 그대로 재사용한다.
"""
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.document import Document
from app.db.models.document_chunk import DocumentChunk
from app.db.models.document_node import DocumentNode
from app.db.models.workflow import WorkflowBlockInstance, WorkflowEdge
from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep
from app.services.dictionary_service import current_dictionary_version


class ReprocessError(ValueError):
    """재처리 요청을 시작할 수 없을 때 — 호출부가 409로 변환."""


async def resolve_start_block(
    db: AsyncSession,
    version_id: str,
    start_block_type: str | None,
    start_block_instance_id: UUID | str | None,
) -> WorkflowBlockInstance:
    if start_block_instance_id is not None:
        block = await db.get(WorkflowBlockInstance, start_block_instance_id)
        if block is None or str(block.version_id) != str(version_id):
            raise ReprocessError("지정한 시작 블록을 찾을 수 없습니다.")
        return block

    matches = (
        await db.scalars(
            select(WorkflowBlockInstance).where(
                WorkflowBlockInstance.version_id == version_id,
                WorkflowBlockInstance.block_type == start_block_type,
            )
        )
    ).all()
    if not matches:
        raise ReprocessError(f"'{start_block_type}' 타입의 블록이 이 워크플로우에 없습니다.")
    if len(matches) > 1:
        raise ReprocessError(
            f"'{start_block_type}' 타입의 블록이 여러 개 있어 특정할 수 없습니다. "
            "start_block_instance_id로 지정하세요."
        )
    return matches[0]


def downstream_closure(
    blocks: list[WorkflowBlockInstance], edges: list[WorkflowEdge], start_block_id: str,
) -> set[str]:
    """start_block_id부터 WorkflowEdge를 따라가는 BFS로 도달 가능한 모든
    블록 id(시작 블록 포함) 집합. 병합/분기가 있는 커스텀 그래프도 순회 자체는
    올바르게 되지만, 폐포 경계에 걸친 병합 블록의 실행 재개는 이 phase의 알려진
    한계(표준 워크플로우는 병합 블록이 없는 선형 체인이라 영향 없음)."""
    outgoing: dict[str, list[str]] = {}
    for e in edges:
        outgoing.setdefault(str(e.from_block_id), []).append(str(e.to_block_id))

    visited = {str(start_block_id)}
    queue = [str(start_block_id)]
    while queue:
        current = queue.pop()
        for target in outgoing.get(current, []):
            if target not in visited:
                visited.add(target)
                queue.append(target)
    return visited


@dataclass
class ReprocessImpact:
    """`compute_reprocess_impact`의 계산 결과 — `impact`는 그대로 API 응답이나
    `WorkflowRun.impact`에 쓸 수 있는 dict, 나머지 필드는 `start_partial_reprocess`가
    실제 run을 만들 때 재계산 없이 재사용하기 위한 것."""

    parent_run: WorkflowRun
    upstream_blocks: list[WorkflowBlockInstance]
    parent_steps_by_block: dict[str, WorkflowRunStep]
    impact: dict


async def compute_reprocess_impact(
    db: AsyncSession, doc: Document, start_block: WorkflowBlockInstance, reason: str | None = None,
) -> ReprocessImpact:
    """재처리 영향도 계산 — WorkflowRun을 만들거나 커밋하지 않는다. 미리보기 전용
    `GET .../reprocess/impact`와 실제 실행하는 `start_partial_reprocess` 양쪽에서
    재사용해, 영향도 계산 로직이 두 곳에서 갈라지지 않게 한다."""
    if not doc.active_run_id:
        raise ReprocessError("이 문서는 아직 워크플로우로 처리된 적이 없어 이 기능을 사용할 수 없습니다.")
    parent_run = await db.get(WorkflowRun, doc.active_run_id)
    if parent_run is None:
        raise ReprocessError("원본 실행 기록을 찾을 수 없습니다.")
    if parent_run.status != "COMPLETED":
        # Document.status는 rag_store 블록이 직접 "INDEXED"로 세팅하는데, 그 시점에도
        # summarize/extract_keywords/output 등 같은 run의 후속 블록은 아직 백그라운드에서
        # 실행 중일 수 있다. 그 상태에서 재처리를 시작하면 새 run이 재실행하는 하류 블록이
        # 원본 run이 아직 끝내지 못한 동일 블록과 동일한 block_execution_cache 키를 두고
        # 경합해 UniqueViolation을 일으킬 수 있으므로, run이 실제로 COMPLETED일 때까지
        # 재처리 시작을 막는다.
        raise ReprocessError(
            "원본 실행이 아직 완료되지 않았습니다(백그라운드 후속 처리 중). 잠시 후 다시 시도하세요."
        )

    blocks = (
        await db.scalars(
            select(WorkflowBlockInstance).where(WorkflowBlockInstance.version_id == parent_run.version_id)
        )
    ).all()
    edges = (
        await db.scalars(select(WorkflowEdge).where(WorkflowEdge.version_id == parent_run.version_id))
    ).all()
    closure = downstream_closure(list(blocks), list(edges), str(start_block.id))
    upstream_blocks = [b for b in blocks if str(b.id) not in closure]

    parent_steps = (
        await db.scalars(select(WorkflowRunStep).where(WorkflowRunStep.run_id == parent_run.id))
    ).all()
    parent_steps_by_block = {str(s.block_instance_id): s for s in parent_steps}

    for b in upstream_blocks:
        step = parent_steps_by_block.get(str(b.id))
        if step is None or step.status not in ("COMPLETED", "SKIPPED"):
            raise ReprocessError(
                f"상류 블록('{b.block_type}')이 완료되지 않아 이 시작점부터 재처리를 시작할 수 없습니다."
            )

    has_incoming = {str(e.to_block_id) for e in edges}
    full_reprocess_required = str(start_block.id) not in has_incoming

    affected_node_count = await db.scalar(
        select(func.count()).select_from(DocumentNode).where(
            DocumentNode.document_id == doc.id, DocumentNode.run_id == parent_run.id
        )
    )
    affected_chunk_count = await db.scalar(
        select(func.count()).select_from(DocumentChunk).where(
            DocumentChunk.document_id == doc.id, DocumentChunk.run_id == parent_run.id
        )
    )

    impact = {
        "reason": reason,
        "changeType": "MANUAL",
        "affectedBlocks": sorted({b.block_type for b in blocks if str(b.id) in closure}),
        "affectedNodeCount": affected_node_count or 0,
        "affectedChunkCount": affected_chunk_count or 0,
        "fullReprocessingRequired": full_reprocess_required,
    }
    return ReprocessImpact(
        parent_run=parent_run, upstream_blocks=upstream_blocks,
        parent_steps_by_block=parent_steps_by_block, impact=impact,
    )


async def start_partial_reprocess(
    db: AsyncSession, doc: Document, start_block: WorkflowBlockInstance, reason: str | None,
) -> WorkflowRun:
    computed = await compute_reprocess_impact(db, doc, start_block, reason=reason)
    parent_run = computed.parent_run
    dictionary_version = await current_dictionary_version(db)

    new_run = WorkflowRun(
        id=uuid4(),
        version_id=parent_run.version_id,
        document_id=doc.id,
        collection_id=parent_run.collection_id,
        status="QUEUED",
        trigger="REPROCESS",
        parent_run_id=parent_run.id,
        started_block_id=start_block.id,
        dictionary_version=dictionary_version,
    )
    db.add(new_run)
    await db.flush()

    # 업로드 시 최초 run을 만들 때와 동일한 패턴(documents.py의 run_workflow) —
    # doc.active_run_id는 항상 "이 문서의 최신 run"을 가리켜야, 연속으로 재처리를
    # 요청했을 때 두 번째 호출이 상류 스텝을 최신 run이 아니라 stale한 원본 run에서
    # 복사해 오는 것을 막는다.
    doc.active_run_id = new_run.id

    for b in computed.upstream_blocks:
        step = computed.parent_steps_by_block[str(b.id)]
        db.add(WorkflowRunStep(
            id=uuid4(),
            run_id=new_run.id,
            block_instance_id=b.id,
            status=step.status,
            input_hash=step.input_hash,
            output=step.output,
            output_hash=step.output_hash,
            artifact_key=step.artifact_key,
            cached=True,
            completed_at=datetime.utcnow(),
        ))

    new_run.impact = computed.impact

    await db.commit()
    await db.refresh(new_run)

    from app.pipeline.tasks.workflow import run_workflow_step, step_queue_for_block

    timeout_seconds = (start_block.config or {}).get("timeoutSeconds", 300)
    run_workflow_step.apply_async(
        args=[str(new_run.id), str(start_block.id)], time_limit=timeout_seconds,
        queue=step_queue_for_block(start_block),
    )

    return new_run
