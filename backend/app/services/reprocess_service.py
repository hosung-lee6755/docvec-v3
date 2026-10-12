"""부분 재처리(시작 블록 지정) 오케스트레이션 — 통합 설계서 §8/§4.10.

새 WorkflowRun을 원본 런과 같은 version_id로 만들고, 시작 블록의 하류 폐포
밖(상류) 블록들은 원본 런의 완료된 스텝을 그대로 복사해 재사용한 뒤,
시작 블록만 직접 큐잉한다 — 상류를 다시 실행할 필요가 없다(이미 완료된
그대로이므로). `app/pipeline/tasks/workflow.py`의 실행기(캐시/DAG 진행)는
전혀 건드리지 않고 그대로 재사용한다.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.collection import Collection
from app.db.models.document import Document
from app.db.models.document_chunk import DocumentChunk
from app.db.models.document_node import DocumentNode
from app.db.models.workflow import WorkflowBlockInstance, WorkflowEdge, WorkflowVersion
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
    parent_run: WorkflowRun | None = None,
) -> ReprocessImpact:
    """재처리 영향도 계산 — WorkflowRun을 만들거나 커밋하지 않는다. 미리보기 전용
    `GET .../reprocess/impact`와 실제 실행하는 `start_partial_reprocess` 양쪽에서
    재사용해, 영향도 계산 로직이 두 곳에서 갈라지지 않게 한다."""
    if not doc.active_run_id:
        raise ReprocessError("이 문서는 아직 워크플로우로 처리된 적이 없어 이 기능을 사용할 수 없습니다.")
    active_run = await db.get(WorkflowRun, doc.active_run_id)
    if active_run is None:
        raise ReprocessError("원본 실행 기록을 찾을 수 없습니다.")
    # parent_run 이 따로 주어지면(분석 run 이 active 인 문서의 전처리 재처리) 그 run 을 기준으로 하되,
    # 문서의 최신 run(active)이 아직 도는 중이면 새 run 과 경합하므로 똑같이 막는다.
    if parent_run is None:
        parent_run = active_run
    elif active_run.status not in ("COMPLETED", "FAILED"):
        raise ReprocessError(
            "문서의 최신 실행이 아직 완료되지 않았습니다(백그라운드 후속 처리 중). 잠시 후 다시 시도하세요."
        )
    if parent_run.status not in ("COMPLETED", "FAILED"):
        # Document.status는 rag_store 블록이 직접 "INDEXED"로 세팅하는데, 그 시점에도
        # summarize/extract_keywords/output 등 같은 run의 후속 블록은 아직 백그라운드에서
        # 실행 중일 수 있다. 그 상태에서 재처리를 시작하면 새 run이 재실행하는 하류 블록이
        # 원본 run이 아직 끝내지 못한 동일 블록과 동일한 block_execution_cache 키를 두고
        # 경합해 UniqueViolation을 일으킬 수 있으므로, run이 실제로 COMPLETED(정상 종료) 또는
        # FAILED(watchdog가 시간초과 등으로 확정 종료 처리)일 때까지 재처리 시작을 막는다 —
        # RUNNING/QUEUED인 동안은 여전히 막아야 위 경합을 피할 수 있다.
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
            DocumentChunk.document_id == doc.id, DocumentChunk.run_id == parent_run.id,
            # Chunk 계층형 Parent Retrieval(메타 정보 생성.txt 3절, Phase 9) —
            # 사용자에게 보여주는 "영향받는 청크 수"는 실제 사용자가 인지하는
            # 청크(child)만 세야 한다. parent까지 세면 배너 숫자가 부풀려진다.
            DocumentChunk.chunk_tier == "child",
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


async def resolve_reprocess_parent(
    db: AsyncSession, doc: Document, start_block_type: str | None,
    start_block_instance_id: UUID | str | None,
) -> tuple[WorkflowRun, WorkflowBlockInstance]:
    """재처리의 기준 run 과 시작 블록. 기본은 문서의 active run 이지만, 컬렉션에 기본 분석 워크플로우가
    있으면 active run 이 AUTO_ANALYSIS run 이라 전처리 블록(file_validate, quality_check 등)은 그 워크플로우에
    없다 — 그 경우 문서의 최근 PREPROCESS run 을 기준으로 삼는다. 어디에도 없으면 원래 오류를 그대로 올린다."""
    if not doc.active_run_id:
        raise ReprocessError("이 문서는 아직 워크플로우로 처리된 적이 없어 이 기능을 사용할 수 없습니다.")
    active_run = await db.get(WorkflowRun, doc.active_run_id)
    if active_run is None:
        raise ReprocessError("원본 실행 기록을 찾을 수 없습니다.")
    try:
        return active_run, await resolve_start_block(
            db, active_run.version_id, start_block_type, start_block_instance_id,
        )
    except ReprocessError as active_error:
        preprocess_run = await find_preprocess_run(db, doc)
        if preprocess_run is None or preprocess_run.id == active_run.id:
            raise
        try:
            return preprocess_run, await resolve_start_block(
                db, preprocess_run.version_id, start_block_type, start_block_instance_id,
            )
        except ReprocessError:
            raise active_error from None


async def start_partial_reprocess(
    db: AsyncSession, doc: Document, start_block: WorkflowBlockInstance, reason: str | None,
    timeout_overrides: dict[str, int] | None = None, parent_run: WorkflowRun | None = None,
) -> WorkflowRun:
    computed = await compute_reprocess_impact(db, doc, start_block, reason=reason, parent_run=parent_run)
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
        # 이 run에서만 적용되는 timeoutSeconds 오버라이드(§ "설정을 바꿔서라도
        # 다시 처리") — WorkflowBlockInstance.config는 건드리지 않으므로 같은
        # workflow version을 쓰는 다른 문서에는 영향이 없다.
        timeout_overrides=timeout_overrides,
        # WorkflowRun.skip_review는 컬럼 기본값이 False라, 여기서 명시적으로
        # parent_run에서 복사하지 않으면 "검토 없이 자동 진행"으로 업로드된
        # 문서도 재처리할 때마다 조용히 검토 게이트가 켜져 WAITING_REVIEW에
        # 멈춘다(2026-07-27 E2E 검증 중 발견).
        skip_review=parent_run.skip_review,
    )
    db.add(new_run)
    await db.flush()

    # 업로드 시 최초 run을 만들 때와 동일한 패턴(documents.py의 run_workflow) —
    # doc.active_run_id는 항상 "이 문서의 최신 run"을 가리켜야, 연속으로 재처리를
    # 요청했을 때 두 번째 호출이 상류 스텝을 최신 run이 아니라 stale한 원본 run에서
    # 복사해 오는 것을 막는다.
    doc.active_run_id = new_run.id
    # run_workflow_step의 _update_document_status는 block_type이
    # _STATUS_FOR_BLOCK_TYPE에 있을 때만 doc.status를 바꾼다 — 매핑에 없는
    # 분석 계열 블록(classify/extract_entities/extract_keywords/summarize)에서
    # 재처리를 시작하면 그 블록이 실제로 도는 동안에도 doc.status가 이전
    # 실행의 terminal 값(FAILED/INDEXED)에 그대로 머물러, 대시보드 "처리중"
    # 집계에서 빠진다(item #2와 같은 부류의 버그, 2026-08-03 실측 — 일괄
    # 재처리한 15건 중 classify/extract_entities/extract_keywords로 시작한
    # 10건이 처리 중에도 계속 FAILED로 표시됨). _maybe_trigger_analysis가
    # 이미 쓰는 것과 같은 패턴으로, 매핑에 없으면 "ANALYZING"으로 fallback.
    from app.pipeline.tasks.workflow import _STATUS_FOR_BLOCK_TYPE

    doc.status = _STATUS_FOR_BLOCK_TYPE.get(start_block.block_type, "ANALYZING")

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

    timeout_seconds = (timeout_overrides or {}).get(start_block.block_type) or (
        start_block.config or {}
    ).get("timeoutSeconds", 1800)
    run_workflow_step.apply_async(
        args=[str(new_run.id), str(start_block.id)], time_limit=timeout_seconds,
        queue=step_queue_for_block(start_block),
    )

    return new_run


async def find_preprocess_run(db: AsyncSession, doc: Document) -> WorkflowRun | None:
    """문서의 가장 최근 PREPROCESS 워크플로우 run. 컬렉션에 기본 분석 워크플로우가 있으면
    문서의 active run 은 전처리가 끝난 뒤 자동으로 시작된 AUTO_ANALYSIS run 이라, active run 의
    워크플로우로는 "전처리를 다시 돌릴 대상"을 알 수 없다."""
    from app.db.models.workflow import WorkflowDefinition

    return await db.scalar(
        select(WorkflowRun)
        .join(WorkflowVersion, WorkflowVersion.id == WorkflowRun.version_id)
        .join(WorkflowDefinition, WorkflowDefinition.id == WorkflowVersion.workflow_id)
        .where(WorkflowRun.document_id == doc.id, WorkflowDefinition.kind == "PREPROCESS")
        .order_by(WorkflowRun.created_at.desc())
        .limit(1)
    )


async def resolve_latest_version(db: AsyncSession, parent_run: WorkflowRun) -> WorkflowVersion:
    """문서가 처리된 워크플로우의 "지금 쓰는" 버전. 컬렉션이 이 워크플로우의 특정 버전을
    고정(default_workflow_version)했으면 그 버전, 아니면 최신 게시 버전 — 업로드 시
    `_resolve_preprocess_version_id`와 같은 기준이라 새로 올린 문서와 같은 버전으로 처리된다."""
    parent_version = await db.get(WorkflowVersion, parent_run.version_id)
    if parent_version is None:
        raise ReprocessError("원본 실행의 워크플로우 버전을 찾을 수 없습니다.")

    query = select(WorkflowVersion).where(WorkflowVersion.workflow_id == parent_version.workflow_id)
    collection = await db.get(Collection, parent_run.collection_id) if parent_run.collection_id else None
    if (
        collection is not None
        and collection.default_workflow_id == parent_version.workflow_id
        and collection.default_workflow_version is not None
    ):
        query = query.where(WorkflowVersion.version_number == collection.default_workflow_version)
    else:
        query = query.where(WorkflowVersion.published_at.is_not(None))
    version = await db.scalar(query.order_by(WorkflowVersion.version_number.desc()).limit(1))
    if version is None:
        raise ReprocessError("이 워크플로우에 게시된 버전이 없습니다.")
    return version


async def start_reprocess_on_latest_version(
    db: AsyncSession, doc: Document, reason: str | None,
    timeout_overrides: dict[str, int] | None = None,
) -> WorkflowRun:
    """문서를 워크플로우의 최신 게시 버전으로 처음부터 다시 처리한다.

    부분 재처리(`start_partial_reprocess`)는 상류 스텝을 복사해 이전 버전 설정 그대로
    쓰므로 새 버전(예: text_extract.engine 변경)이 반영되지 않는다. 여기서는 스텝을
    복사하지 않고 진입 블록부터 새 run을 실행한다 — 설정이 같은 블록은
    block_execution_cache(config_hash 키)가 알아서 재사용한다."""
    if not doc.active_run_id:
        raise ReprocessError("이 문서는 아직 워크플로우로 처리된 적이 없어 이 기능을 사용할 수 없습니다.")
    parent_run = await db.get(WorkflowRun, doc.active_run_id)
    if parent_run is None:
        raise ReprocessError("원본 실행 기록을 찾을 수 없습니다.")
    if parent_run.status not in ("COMPLETED", "FAILED"):
        raise ReprocessError(
            "원본 실행이 아직 완료되지 않았습니다(백그라운드 후속 처리 중). 잠시 후 다시 시도하세요."
        )

    # 처리 대상은 active run 이 아니라 문서의 전처리 워크플로우다(active run 이 분석 run 일 수 있다).
    base_run = await find_preprocess_run(db, doc) or parent_run
    version = await resolve_latest_version(db, base_run)
    dictionary_version = await current_dictionary_version(db)

    blocks = (
        await db.scalars(select(WorkflowBlockInstance).where(WorkflowBlockInstance.version_id == version.id))
    ).all()
    edges = (await db.scalars(select(WorkflowEdge).where(WorkflowEdge.version_id == version.id))).all()
    has_incoming = {e.to_block_id for e in edges}
    entry_blocks = [b for b in blocks if b.id not in has_incoming]
    if not entry_blocks:
        raise ReprocessError("최신 버전에 시작 블록이 없습니다.")

    new_run = WorkflowRun(
        id=uuid4(),
        version_id=version.id,
        document_id=doc.id,
        collection_id=parent_run.collection_id,
        status="QUEUED",
        trigger="REPROCESS",
        parent_run_id=parent_run.id,
        dictionary_version=dictionary_version,
        timeout_overrides=timeout_overrides,
        skip_review=parent_run.skip_review,
        impact={
            "reason": reason,
            "changeType": "VERSION_UPGRADE",
            "affectedBlocks": sorted({b.block_type for b in blocks}),
            "affectedNodeCount": 0,
            "affectedChunkCount": 0,
            "fullReprocessingRequired": True,
        },
    )
    db.add(new_run)
    await db.flush()
    doc.active_run_id = new_run.id

    from app.pipeline.tasks.workflow import _STATUS_FOR_BLOCK_TYPE, run_workflow_step, step_queue_for_block

    doc.status = _STATUS_FOR_BLOCK_TYPE.get(entry_blocks[0].block_type, "ANALYZING")
    await db.commit()
    await db.refresh(new_run)

    for block in entry_blocks:
        timeout_seconds = (timeout_overrides or {}).get(block.block_type) or (
            block.config or {}
        ).get("timeoutSeconds", 1800)
        run_workflow_step.apply_async(
            args=[str(new_run.id), str(block.id)], time_limit=timeout_seconds,
            queue=step_queue_for_block(block),
        )
    return new_run


# 시간초과로 SIGKILL된 셀러리 hard time limit은 애플리케이션 코드로 잡을 수 없어(billiard가
# 워커 fork 프로세스를 직접 죽임) run/step이 RUNNING 상태로 영구히 멈춰 있게 된다 — 별도
# 워커/beat 인프라 없이, 문서 조회(GET /documents/{id})마다 지연 감지해 FAILED로 확정한다.
# 30초 여유: task 타임아웃 발동과 DB에 반영되는 시점 사이의 clock skew 및 task
# 큐/워커 지연을 흡수하고, 사용자 문서 새로고침이 너무 빨리 timeout 판정을 내리지 않도록.
_TIMEOUT_GRACE_SECONDS = 30


def _seconds_since(moment: datetime) -> float:
    """`app/db/types.py::UTCDateTime`으로 감싼 컬럼(started_at 등)은 읽을 때
    tzinfo=UTC가 붙은 aware datetime을 반환하는데, `datetime.utcnow()`는
    naive라 그대로 빼면 TypeError(offset-naive/aware 혼합)가 난다(2026-07-30,
    beat 도입 직후 워커 로그에서 실제로 발생 확인). moment의 tzinfo 유무와
    무관하게 항상 UTC 기준 경과 초를 반환한다."""
    now = datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (now - moment).total_seconds()


async def reconcile_stuck_run(db: AsyncSession, doc: Document) -> bool:
    """doc의 active run이 자신의 timeout(+여유시간)을 넘겨 RUNNING에 멈춰 있으면
    run/step/문서를 FAILED로 확정하고 사유를 error_message에 남긴다. 반환값은
    "이번 호출에서 무언가를 확정했는가"이며, 호출부는 보통 반환값을 쓰지 않고
    호출 직후의 doc 상태를 그대로 읽는다(같은 세션 내에서 in-place로 갱신됨)."""
    if not doc.active_run_id:
        return False
    run = await db.get(WorkflowRun, doc.active_run_id)
    if run is None or run.status != "RUNNING":
        return False

    stuck_step = await db.scalar(
        select(WorkflowRunStep).where(
            WorkflowRunStep.run_id == run.id,
            WorkflowRunStep.status == "RUNNING",
            WorkflowRunStep.started_at.is_not(None),
        )
    )
    if stuck_step is None:
        return False

    block = await db.get(WorkflowBlockInstance, stuck_step.block_instance_id)
    block_type = block.block_type if block else None
    timeout_seconds = (run.timeout_overrides or {}).get(block_type) or (
        (block.config or {}).get("timeoutSeconds", 1800) if block else 1800
    )
    elapsed = _seconds_since(stuck_step.started_at)
    if elapsed <= timeout_seconds + _TIMEOUT_GRACE_SECONDS:
        return False

    message = (
        f"'{block_type or stuck_step.block_instance_id}' 처리 시간 제한({timeout_seconds}초)을 "
        "초과하여 작업이 중단되었습니다. 필요 시 시간 제한을 늘려 재처리할 수 있습니다."
    )
    stuck_step.status = "FAILED"
    stuck_step.error_code = "TIMEOUT_EXCEEDED"
    stuck_step.error_message = message
    stuck_step.completed_at = datetime.utcnow()
    run.status = "FAILED"
    run.error_message = message
    run.completed_at = datetime.utcnow()
    if str(doc.active_run_id) == str(run.id):
        doc.status = "FAILED"
        doc.error_message = message
    await db.commit()
    return True
