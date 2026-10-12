from datetime import datetime
from uuid import UUID

from app.api.v1.deps import get_current_user
from app.api.v1.permissions import (
    check_document_access,
)
from app.db.models.document import Document
from app.db.models.document_revision import DocumentTextRevision
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.document import (
    DocumentElementItem,
    DocumentElementsResponse,
    DocumentNodeItem,
    DocumentNodesResponse,
    DocumentProceedRequest,
    DocumentReprocessRequest,
    DocumentRunsResponse,
    ElementCorrectionRequest,
    NodeCorrectionRequest,
    QualityReportResponse,
    ReprocessImpactResponse,
)
from app.services.document_state import claim_document_status as _claim_document_status
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()
_MAX_RUN_HISTORY = 100

@router.get("/{document_id}/status")
async def get_document_status(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")
    return {"status": doc.status, "error_message": doc.error_message}


@router.post("/{document_id}/proceed")
async def proceed_document(
    document_id: UUID,
    body: DocumentProceedRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.pipeline.tasks.process import continue_processing

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    # 상태 확인과 선점을 한 UPDATE로 묶는다 — 두 번 클릭/동시 요청이 와도 하나만 통과해
    # continue_processing이 중복 디스패치되지 않는다.
    extra = {"parsed_text": body.edited_text} if body.edited_text is not None else {}
    seen_status = doc.status  # rollback이 doc을 만료시키므로 먼저 읽어 둔다
    if not await _claim_document_status(db, document_id, "REVIEW_PENDING", "CHUNKING", **extra):
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Document is not awaiting review (status={seen_status})",
        )
    if body.edited_text is not None:
        db.add(
            DocumentTextRevision(
                document_id=document_id,
                source="REVIEW_EDIT",
                parsed_text=body.edited_text,
                created_by=str(current_user.id),
            )
        )
    await db.commit()

    continue_processing.delay(str(document_id))
    return {"message": "Processing resumed", "status": "CHUNKING"}


@router.post("/{document_id}/reprocess")
async def reprocess_document(
    document_id: UUID,
    body: DocumentReprocessRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    if body.start_block_type is not None or body.start_block_instance_id is not None:
        from app.db.models.workflow_run import WorkflowRun as _WorkflowRun
        from app.services.reprocess_service import (
            ReprocessError,
            reconcile_stuck_run,
            resolve_start_block,
            start_partial_reprocess,
        )

        # 셀러리 hard time limit에 걸려 RUNNING으로 멈춰 있던 run/문서를, 재처리를
        # 시도하는 이 순간에도 한 번 더 확정해 둔다 — 문서 상세 화면을 거치지 않고
        # 곧바로 재처리 API를 호출하는 경우까지 커버(§ "멈췄으면 설정을 바꿔서라도
        # 다시 처리하게 할 수 있는 기능").
        await reconcile_stuck_run(db, doc)

        parent_run = await db.get(_WorkflowRun, doc.active_run_id) if doc.active_run_id else None
        if parent_run is None:
            raise HTTPException(
                status_code=409,
                detail="이 문서는 아직 워크플로우로 처리된 적이 없어 이 기능을 사용할 수 없습니다.",
            )

        try:
            start_block = await resolve_start_block(
                db, parent_run.version_id, body.start_block_type, body.start_block_instance_id,
            )
            new_run = await start_partial_reprocess(
                db, doc, start_block, body.reason, timeout_overrides=body.timeout_overrides,
            )
        except ReprocessError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return {
            "message": "부분 재처리가 시작되었습니다",
            "run_id": str(new_run.id),
            "status": "QUEUED",
            "impact": new_run.impact,
        }

    from app.pipeline.tasks.process import continue_processing

    extra = {"parsed_text": body.edited_text} if body.edited_text is not None else {}
    seen_status = doc.status  # rollback이 doc을 만료시키므로 먼저 읽어 둔다
    if not await _claim_document_status(db, document_id, "INDEXED", "CHUNKING", **extra):
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Document is not indexed yet (status={seen_status})",
        )
    db.add(
        DocumentTextRevision(
            document_id=document_id,
            source="RAG_EDIT",
            parsed_text=body.edited_text,
            created_by=str(current_user.id),
        )
    )
    await db.commit()

    continue_processing.delay(str(document_id), edited_text=body.edited_text)
    return {"message": "Reprocessing started", "status": "CHUNKING"}


@router.get("/{document_id}/runs", response_model=DocumentRunsResponse)
async def list_document_runs(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.db.models.workflow_run import WorkflowRun

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")

    runs = (
        await db.scalars(
            select(WorkflowRun)
            .where(WorkflowRun.document_id == document_id)
            .order_by(desc(WorkflowRun.created_at))
            .limit(_MAX_RUN_HISTORY)  # 재처리마다 쌓이므로 최신 N건만 돌려준다
        )
    ).all()
    return {"document_id": str(document_id), "runs": runs}


@router.get("/{document_id}/quality", response_model=QualityReportResponse | None)
async def get_document_quality(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.db.models.quality_report import QualityReport

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")

    report = None
    if doc.active_run_id:
        report = await db.scalar(
            select(QualityReport).where(QualityReport.run_id == doc.active_run_id)
        )
    if report is None:
        # 구버전 문서 마이그레이션(설계서 §14)이나 active_run_id가 비어 있는 경우 —
        # 이 문서에 대해 가장 최근에 계산된 리포트라도 보여준다.
        report = await db.scalar(
            select(QualityReport)
            .where(QualityReport.document_id == document_id)
            .order_by(desc(QualityReport.created_at))
            .limit(1)
        )
    return report


@router.get("/{document_id}/reprocess/impact", response_model=ReprocessImpactResponse)
async def get_document_reprocess_impact(
    document_id: UUID,
    start_block_type: str | None = None,
    start_block_instance_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """부분 재처리 시작 전 영향 범위 미리보기 — WorkflowRun을 생성하지 않는다
    (재처리 모달, 통합 설계서 §9.1 처리 이력 탭/§7 재처리 모달)."""
    from app.db.models.workflow_run import WorkflowRun as _WorkflowRun
    from app.services.reprocess_service import (
        ReprocessError,
        compute_reprocess_impact,
        resolve_start_block,
    )

    if start_block_type is None and start_block_instance_id is None:
        raise HTTPException(
            status_code=422, detail="start_block_type 또는 start_block_instance_id 중 하나가 필요합니다.",
        )

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")

    parent_run = await db.get(_WorkflowRun, doc.active_run_id) if doc.active_run_id else None
    if parent_run is None:
        raise HTTPException(
            status_code=409,
            detail="이 문서는 아직 워크플로우로 처리된 적이 없어 이 기능을 사용할 수 없습니다.",
        )

    try:
        start_block = await resolve_start_block(
            db, parent_run.version_id, start_block_type, start_block_instance_id,
        )
        computed = await compute_reprocess_impact(db, doc, start_block)
    except ReprocessError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return computed.impact


async def _resolve_display_run_id(db: AsyncSession, doc: Document) -> str | None:
    """활성 run 우선, 없으면 최신 run — get_document_quality가 쓰는 폴백과 동일 기준으로
    구조/정제/사전적용/PII 탭이 "어느 run의 데이터를 보여줄지"를 통일한다. 각 테이블이
    run_id로 여러 실행 결과를 구분해 쌓기 때문에(재처리마다 새 결과가 추가됨) 하나로
    고정하지 않으면 여러 run의 데이터가 뒤섞여 보인다.

    이 탭들이 보여주는 노드/청크/정제/PII는 전처리 산출물이다. 컬렉션에 기본 분석
    워크플로우가 있으면 active_run_id는 전처리 직후 분석 run으로 옮겨가는데(진행 중인 run을
    추적하는 불변식), 분석 run에는 이 데이터가 없어 그대로 쓰면 분석이 끝나자마자 탭이 전부
    비어 보인다. 그래서 전처리(PREPROCESS) run 중에서 고른다 — 활성 run이 전처리 run이면
    그것, 아니면 가장 최근 전처리 run. 전처리 run이 하나도 없는 문서만 이전 기준을 따른다."""
    from app.db.models.workflow import WorkflowDefinition, WorkflowVersion
    from app.db.models.workflow_run import WorkflowRun as _WorkflowRun

    preprocess_runs = (
        select(_WorkflowRun.id)
        .join(WorkflowVersion, WorkflowVersion.id == _WorkflowRun.version_id)
        .join(WorkflowDefinition, WorkflowDefinition.id == WorkflowVersion.workflow_id)
        .where(_WorkflowRun.document_id == doc.id, WorkflowDefinition.kind == "PREPROCESS")
    )
    if doc.active_run_id:
        active_preprocess = await db.scalar(preprocess_runs.where(_WorkflowRun.id == doc.active_run_id))
        if active_preprocess:
            return str(active_preprocess)
    latest_preprocess = await db.scalar(preprocess_runs.order_by(desc(_WorkflowRun.created_at)).limit(1))
    if latest_preprocess:
        return str(latest_preprocess)

    if doc.active_run_id:
        return str(doc.active_run_id)
    run_id = await db.scalar(
        select(_WorkflowRun.id)
        .where(_WorkflowRun.document_id == doc.id)
        .order_by(desc(_WorkflowRun.created_at))
        .limit(1)
    )
    return str(run_id) if run_id else None


@router.get("/{document_id}/nodes", response_model=DocumentNodesResponse)
async def list_document_nodes(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.db.models.document_node import DocumentNode

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")

    run_id = await _resolve_display_run_id(db, doc)
    nodes = []
    if run_id:
        nodes = (
            await db.scalars(
                select(DocumentNode)
                .where(DocumentNode.run_id == run_id)
                .order_by(DocumentNode.sort_order.asc())
            )
        ).all()
    return {"document_id": str(document_id), "run_id": run_id, "nodes": nodes}


@router.patch("/{document_id}/nodes/{node_id}", response_model=DocumentNodeItem)
async def correct_document_node(
    document_id: UUID,
    node_id: UUID,
    body: NodeCorrectionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.db.models.document_node import DocumentNode

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    node = await db.scalar(
        select(DocumentNode).where(DocumentNode.id == node_id, DocumentNode.document_id == document_id)
    )
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    changed_fields = []
    if body.node_type is not None:
        allowed_types = DocumentNode.__table__.c.node_type.type.enums
        if body.node_type not in allowed_types:
            raise HTTPException(status_code=422, detail=f"허용되지 않는 node_type: {body.node_type}")
        node.node_type = body.node_type
        changed_fields.append("node_type")
    if body.level is not None:
        node.level = body.level
        changed_fields.append("level")
    # 메타 정보 생성.txt 2절 — HWP/HWPX/Docling 경로처럼 style_name/font_size/
    # font_name이 자동 생성되지 않는 노드의 수동 보정. 부분 병합(node.style의
    # 기존 키는 유지하고 전달된 키만 덮어씀).
    style_updates = {
        k: v for k, v in {
            "style_name": body.style_name, "font_size": body.font_size, "font_name": body.font_name,
        }.items() if v is not None
    }
    if style_updates:
        node.style = {**(node.style or {}), **style_updates}
        changed_fields.append("style")
    node.user_corrected = True
    node.correction_type = ",".join(changed_fields)
    node.correction_notes = body.correction_notes
    await db.commit()
    await db.refresh(node)
    return node


@router.get("/{document_id}/elements", response_model=DocumentElementsResponse)
async def list_document_elements(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Document.elements(Docling 도입 설계서, 2026-07-23 Phase 4) — Docling
    엔진으로 처리된 PDF만 채워짐. HWP/HWPX나 legacy 엔진 문서는 항상 빈
    리스트(프런트가 이 탭을 숨기는 신호로 사용, 표 탭과 동일한 원칙)."""
    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")

    return {"document_id": str(document_id), "elements": doc.elements or []}


@router.patch("/{document_id}/elements/{element_id}", response_model=DocumentElementItem)
async def correct_document_element(
    document_id: UUID,
    element_id: str,
    body: ElementCorrectionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    elements = doc.elements or []
    updated_element = None
    new_elements = []
    for el in elements:
        if el.get("id") == element_id:
            el = dict(el)
            el["content"] = {**(el.get("content") or {}), "markdown": body.markdown, "text": body.markdown}
            el["user_corrected"] = True
            el["correction_notes"] = body.correction_notes
            # 메타 정보 생성.txt 2절 — style/font_size/font_name은 Docling
            # 경로에서 자동 생성이 불가능해 전달된 값만 metadata에 병합한다
            # (미전달 필드는 기존 값 유지).
            metadata_updates = {
                k: v for k, v in {
                    "style": body.style, "font_size": body.font_size, "font_name": body.font_name,
                }.items() if v is not None
            }
            if metadata_updates:
                el["metadata"] = {**(el.get("metadata") or {}), **metadata_updates}
            updated_element = el
        new_elements.append(el)
    if updated_element is None:
        raise HTTPException(status_code=404, detail="Element not found")

    # Document.elements는 JSON 컬럼이라 리스트 원소를 in-place로 바꿔도
    # SQLAlchemy가 변경을 추적하지 못한다 — 컬럼 전체를 새 리스트로 재할당해야
    # UPDATE가 나간다(문서 파싱 고도화 Phase 4).
    doc.elements = new_elements
    doc.updated_at = datetime.utcnow()
    await db.commit()
    return updated_element


