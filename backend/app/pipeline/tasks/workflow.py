"""DAG executor for user-defined workflows (app/db/models/workflow.py).

Unlike the fixed document pipeline (tasks/pipeline.py, a static Celery
chain()), a workflow graph can branch (조건분기) and merge (병합), so it is
walked one block at a time: each completed block resolves its own outgoing
WorkflowEdges and enqueues whatever comes next, rather than being composed
into one static chain up front.
"""
import hashlib
import json
import re
from datetime import datetime
from uuid import uuid4

from app.pipeline.blocks.base import BlockContext, BlockExecutionError
from app.pipeline.blocks.registry import BLOCK_REGISTRY
from app.pipeline.celery_app import celery_app

# 대용량 산출물은 인라인 대신 MinIO artifacts 버킷에 저장 (통합 설계서 §2.3).
_ARTIFACT_INLINE_THRESHOLD_BYTES = 16_000

# 실행 중 블록 -> Document.status 파생 매핑 (통합 설계서 §7.2). 현재 등록된 11개
# 블록 타입은 이 매핑에 없으므로 지금은 사실상 no-op — Phase 3+에서 신규 블록
# 타입이 추가되는 즉시 실행기 재수정 없이 자동으로 작동한다.
_STATUS_FOR_BLOCK_TYPE: dict[str, str] = {
    "file_validate": "VALIDATING",
    "format_detect": "VALIDATING",
    "text_extract": "PARSING",
    "ocr": "PARSING",
    "structure_analyze": "STRUCTURING",
    "text_clean": "REFINING",
    "stopword": "NORMALIZING",
    "synonym": "NORMALIZING",
    "user_dict": "NORMALIZING",
    "pii_detect": "MASKING",
    "chunk_split": "CHUNKING",
    "quality_check": "VALIDATING",
    "rag_store": "EMBEDDING",
}


def step_queue_for_block(block) -> str:
    """어느 블록이 GPU 임베딩 모델을 쓰는지에 따라 실행 큐를 나눈다 — rag_store는
    항상, chunk_split은 strategy=semantic일 때만 embed()를 호출한다. 이 블록들을
    별도의 'embed' 큐로 보내면 worker-embed 컨테이너(concurrency=1)가 순차 실행해,
    GPU 메모리 하나를 여러 워커 슬롯이 동시에 점유해 서로 밀어내는 경합을 막는다."""
    if block.block_type == "rag_store":
        return "embed"
    if block.block_type == "chunk_split" and (block.config or {}).get("strategy") == "semantic":
        return "embed"
    return "normal"


def _evaluate_condition(condition: dict | None, output: dict) -> bool:
    if condition is None:
        return True
    return output.get(condition.get("output_field")) == condition.get("equals")


def _serialize(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, default=str).encode()


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _store_step_output(run_id: str, step, output: dict) -> dict:
    """Inlines `output` on `step` when small, or offloads it to the MinIO
    artifacts bucket and stores a reference (통합 설계서 §2.3). Returns the
    fully-resolved output dict (never the reduced summary) so callers can use
    it for edge-condition evaluation without caring which path was taken."""
    from app.core.config import settings
    from app.services.storage import storage_service

    data = _serialize(output)
    step.output_hash = _hash_bytes(data)
    if len(data) <= _ARTIFACT_INLINE_THRESHOLD_BYTES:
        step.output = output
        step.artifact_key = None
    else:
        key = f"runs/{run_id}/{step.id}/output.json"
        storage_service.upload_file(settings.minio_bucket_artifacts, key, data, "application/json")
        step.artifact_key = key
        step.output = {"artifact": key, "output_hash": step.output_hash, "_artifact_only": True}
    return output


def _resolve_output(output: dict | None) -> dict:
    """Loads an `_artifact_only`-marked step output back from MinIO; passes
    through inline outputs unchanged. Blocks never see the reduced form."""
    from app.core.config import settings
    from app.services.storage import storage_service

    if not output:
        return {}
    if output.get("_artifact_only") and output.get("artifact"):
        return json.loads(storage_service.download_file(settings.minio_bucket_artifacts, output["artifact"]))
    return output


# These 3 block types read dictionary_entries as of WorkflowRun.dictionary_version
# (통합 설계서 §5) — their cache key must fold that version in so an edited
# dictionary busts the cache for exactly these blocks, per §2.4's cache key
# formula ("... + 사전 버전(사전 블록만) + ..."). Every other block type ignores
# the dictionary entirely, so including it there would only cause needless
# cache misses whenever anyone edits an unrelated dictionary entry.
_DICTIONARY_BLOCK_TYPES = frozenset({"stopword", "synonym", "user_dict", "pii_detect"})
# skip_review only changes quality_check's requires_review decision (9항목
# 펀치리스트 #1) — scoped the same way dictionary_version is scoped to
# _DICTIONARY_BLOCK_TYPES below, so it doesn't perturb every other block's
# cache key.
_REVIEW_GATED_BLOCK_TYPES = frozenset({"quality_check"})

# BlockExecutionCache is a cross-run, content-addressed cache — safe ONLY for
# block types whose real DB side effect lives on the Document row itself
# (text_extract's parsed_text/elements/images/tables/etc.), since that row
# already holds the correct final state no matter which run last wrote it.
# Every other block type persists rows scoped by run_id (structure_analyze ->
# DocumentNode, text_clean/user_dict/synonym/stopword -> CleaningChange/
# DictionaryApplication, pii_detect -> PiiDetection, chunk_split ->
# DocumentChunk, quality_check -> QualityReport, ...) — a cache hit from an
# EARLIER run would silently skip creating rows under the CURRENT run_id,
# leaving every doc.active_run_id-scoped query (구조/정제 비교/사전 적용/
# 민감정보 tabs) empty even though the step shows COMPLETED. This bug occurs
# when text_extract through pii_detect are cache hits from an earlier run and
# write nothing under the current run_id, while later blocks like chunk_split
# execute normally. Deny-by-default so a newly added block type is safe
# until explicitly added here.
_CACHE_SAFE_BLOCK_TYPES = frozenset({"file_validate", "format_detect", "text_extract"})


def _compute_cache_key(
    document_id: str | None,
    input_hash: str,
    block_type: str,
    block_version: str,
    config: dict,
    dictionary_version: int | None = None,
    skip_review: bool = False,
) -> str:
    # document_id is required even though most blocks derive their output from
    # upstream_outputs: an entry block (e.g. file_validate) has NO upstream, so
    # its input_hash is identical ({} serialized) across every document — without
    # document_id, two unrelated documents' entry-block runs would collide on
    # the same cache key and each would replay the other's cached output.
    config_hash = _hash_bytes(_serialize(config or {}))
    dict_version_part = dictionary_version if block_type in _DICTIONARY_BLOCK_TYPES else None
    skip_review_part = skip_review if block_type in _REVIEW_GATED_BLOCK_TYPES else None
    return _hash_bytes(
        f"{document_id}:{input_hash}:{block_type}:{block_version}:{config_hash}:"
        f"{dict_version_part}:{skip_review_part}".encode()
    )


def _update_document_status(db, run, block_type: str) -> None:
    from app.db.models.document import Document

    new_status = _STATUS_FOR_BLOCK_TYPE.get(block_type)
    if new_status is None or not run.document_id:
        return
    doc = db.get(Document, run.document_id)
    if doc is not None:
        doc.status = new_status
        db.commit()


_HANGUL_RE = re.compile(r"[가-힣]")

# 알려진 라이브러리/드라이버 예외 문자열 패턴 -> 한글 안내 문구. 원문에 없으면
# _localize_error_message가 일반 안내 문구로 대체한다.
_KNOWN_ERROR_PATTERNS: list[tuple[str, str]] = [
    (
        "NUL (0x00)",
        "추출된 문서 텍스트에 데이터베이스가 저장할 수 없는 문자(NUL)가 포함되어 있어 처리에 실패했습니다.",
    ),
    ("TimeLimitExceeded", "처리 시간 제한을 초과하여 작업이 중단되었습니다."),
    ("SoftTimeLimitExceeded", "처리 시간 제한을 초과하여 작업이 중단되었습니다."),
]


def _localize_error_message(exc: Exception) -> str:
    """워커 내부에서 잡히는 예외(SQLAlchemy/DB 드라이버/셀러리 등 라이브러리 예외)의
    원문은 영어라, Document/WorkflowRun/WorkflowRunStep.error_message에 그대로
    노출하면 사용자가 읽을 수 없다. 우리 블록 코드가 이미 한글로
    직접 작성한 BlockExecutionError 메시지(대부분의 경우)는 한글이 포함돼 있으므로
    그대로 통과시키고, 그 외(알려진 패턴 또는 순수 영어 라이브러리 예외)만 번역한다.
    원본 예외는 이 함수 호출 후에도 그대로 raise되어 워커 로그에 남으므로, 여기서
    기술적 세부사항을 생략해도 진단 정보가 소실되지는 않는다."""
    text = str(exc)
    for marker, korean_message in _KNOWN_ERROR_PATTERNS:
        if marker in text:
            return korean_message
    if _HANGUL_RE.search(text):
        return text
    # 알려진 패턴에도 없고 한글도 없는 예외는 그동안 이 안내 문구 하나로 완전히
    # 뭉개버려, 워커가 재시작되어 로그가 사라지면 원인을 영영 알 수 없었다
    # (2026-07-29 classify 블록 실패 건에서 실측 확인 — 워커 재시작 이후 원본
    # 예외 정보가 로그에도, Document.error_message에도 남아있지 않았다).
    # 사용자 안내 문구는 유지하되 예외 타입 + 원문 일부를 덧붙여 DB 자체에
    # 최소한의 진단 단서를 남긴다.
    detail = f"{type(exc).__name__}: {text}"[:200]
    return f"처리 중 예기치 않은 오류가 발생했습니다. 문제가 반복되면 관리자에게 문의하세요. [{detail}]"


def _fail_document(db, run, error_message: str) -> None:
    """Mirrors the retired fixed pipeline's failure behavior (parse_document/
    continue_processing always set Document.status="FAILED" on error) so the
    document list/detail UI still surfaces workflow-driven failures."""
    from app.db.models.document import Document

    if not run.document_id:
        return
    doc = db.get(Document, run.document_id)
    if doc is not None:
        doc.status = "FAILED"
        doc.error_message = error_message[:500]
        # AUTO_ANALYSIS run이 실패했을 때도 active_run_id는 이 run을 가리켜야
        # 한다 — _maybe_trigger_analysis가 그 run을 만들 때 이미 그렇게
        # 해두지만(2026-08-03 수정), 그 이전에 생성된 run이거나 다른 경로로
        # active_run_id가 어긋난 경우까지 실패 확정 시점에 한 번 더 바로잡아
        # "이 문서의 최신 run"이라는 불변식을 지킨다.
        doc.active_run_id = run.id


def _find_paused_step(db, run_id: str):
    """Finds the step a WAITING_REVIEW run halted at — the run stops
    _advance() the instant a block requests review, so exactly one COMPLETED
    step exists whose taken outgoing edges point at blocks with no step row
    yet (every other completed step already had _advance() run for it,
    which always creates a step row for each taken edge's target)."""
    from app.db.models.workflow import WorkflowEdge
    from app.db.models.workflow_run import WorkflowRunStep

    all_steps = db.query(WorkflowRunStep).filter(WorkflowRunStep.run_id == run_id).all()
    existing_targets = {str(s.block_instance_id) for s in all_steps}
    for step in all_steps:
        if step.status != "COMPLETED":
            continue
        outgoing = db.query(WorkflowEdge).filter(
            WorkflowEdge.from_block_id == step.block_instance_id
        ).all()
        taken = [e for e in outgoing if _evaluate_condition(e.condition, _resolve_output(step.output))]
        if taken and all(str(e.to_block_id) not in existing_targets for e in taken):
            return step
    return None


@celery_app.task(name="tasks.run_workflow_step", queue="normal", bind=True, max_retries=3)
def run_workflow_step(self, run_id: str, block_instance_id: str) -> dict:
    from app.db.models.block_execution_cache import BlockExecutionCache
    from app.db.models.document import Document
    from app.db.models.workflow import WorkflowBlockInstance, WorkflowEdge
    from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep
    from app.db.session import get_sync_db

    db = get_sync_db()
    block = None
    try:
        run = db.get(WorkflowRun, run_id)
        block = db.get(WorkflowBlockInstance, block_instance_id)
        if run is None or block is None:
            return {"status": "NOT_FOUND"}

        if run.status == "QUEUED":
            run.status = "RUNNING"
            run.started_at = datetime.utcnow()
            db.commit()

        step = db.query(WorkflowRunStep).filter(
            WorkflowRunStep.run_id == run_id,
            WorkflowRunStep.block_instance_id == block_instance_id,
        ).first()
        if step is None:
            step = WorkflowRunStep(run_id=run_id, block_instance_id=block_instance_id, status="PENDING")
            db.add(step)
            db.commit()
            db.refresh(step)
        elif step.status in ("COMPLETED", "FAILED"):
            # 브로커 재전송(예: 워커 재시작 중 visibility-timeout 재전달)으로
            # 이미 끝난 step에 중복 실행이 들어오면, 아래 step.started_at 갱신이
            # 이미 커밋된 completed_at보다 뒤로 밀려 음수 처리시간을 만든다
            # (처리현황 블록별 평균시간에서 확인, 2026-07-30). 이미 종결된
            # step은 재실행하지 않고 그대로 반환한다.
            #
            # 이 경로는 non-merge fan-in 중복 디스패치의 "늦게 도착한 쪽"이
            # 도달하는 지점이기도 하다 — 그 늦은 쪽이 run 전체를 완료로 확정
            # 짓는 마지막 기회일 수 있으므로(다른 모든 step은 이미 COMPLETED),
            # 여기서도 완료 여부를 재확인한다(2026-08-03 실측 회귀).
            if run is not None:
                _maybe_complete_run(db, run_id)
            return {"status": step.status, "output": _resolve_output(step.output)}

        _update_document_status(db, run, block.block_type)

        incoming_edges = db.query(WorkflowEdge).filter(
            WorkflowEdge.to_block_id == block_instance_id
        ).all()
        upstream_steps = db.query(WorkflowRunStep).filter(
            WorkflowRunStep.run_id == run_id,
            WorkflowRunStep.block_instance_id.in_([e.from_block_id for e in incoming_edges]),
        ).all()
        upstream_outputs = {
            str(s.block_instance_id): _resolve_output(s.output) for s in upstream_steps
        }

        step.status = "RUNNING"
        step.started_at = datetime.utcnow()
        step.input_hash = _hash_bytes(_serialize(upstream_outputs))
        db.commit()

        block_cls = BLOCK_REGISTRY[block.block_type]
        block_instance = block_cls()
        cache_key = _compute_cache_key(
            str(run.document_id) if run.document_id else None,
            step.input_hash, block.block_type, block_instance.block_version, block.config or {},
            dictionary_version=run.dictionary_version,
            skip_review=bool(run.skip_review),
        )
        cache_entry = (
            db.get(BlockExecutionCache, cache_key)
            if block.block_type in _CACHE_SAFE_BLOCK_TYPES else None
        )

        if cache_entry is not None:
            resolved_output = _resolve_output(cache_entry.output_summary)
            step.output = cache_entry.output_summary
            step.output_hash = _hash_bytes(_serialize(resolved_output))
            step.artifact_key = (cache_entry.output_summary or {}).get("artifact")
            step.cached = True
            step.status = "COMPLETED"
            step.completed_at = datetime.utcnow()
            cache_entry.hit_count = (cache_entry.hit_count or 0) + 1
            cache_entry.last_hit_at = datetime.utcnow()
            db.commit()
            requires_review = cache_entry.requires_review
        else:
            result = block_instance.run(BlockContext(
                run_id=run_id,
                block_instance_id=block_instance_id,
                step_id=str(step.id),
                upstream_outputs=upstream_outputs,
                config=block.config or {},
                skip_review=bool(run.skip_review),
                document_id=str(run.document_id) if run.document_id else None,
                collection_id=str(run.collection_id) if run.collection_id else None,
            ))

            resolved_output = result.output
            step.status = "COMPLETED"
            step.warnings = result.warnings or None
            step.metrics = result.metrics or None
            step.completed_at = datetime.utcnow()
            _store_step_output(run_id, step, result.output)
            db.commit()

            if block.block_type in _CACHE_SAFE_BLOCK_TYPES:
                db.add(BlockExecutionCache(
                    cache_key=cache_key,
                    artifact_key=step.artifact_key or "",
                    output_summary=step.output,
                    created_at=datetime.utcnow(),
                    hit_count=0,
                    requires_review=result.requires_review,
                ))
                db.commit()
            requires_review = result.requires_review

        # cache_entry 경로에서도 반드시 확인해야 한다 — 이전에는 cache-hit일 때
        # requires_review를 전혀 확인하지 않고 무조건 _advance()로 넘어가 검토
        # 게이트를 우회하는 버그가 있었다. 재실행했을 때 rag_store까지 진행되어
        # 미승인 상태로 임베딩될 수 있다.
        if requires_review:
            run.status = "WAITING_REVIEW"
            if run.document_id:
                doc = db.get(Document, run.document_id)
                if doc is not None:
                    doc.status = "WAITING_REVIEW"
            db.commit()
            return {"status": "WAITING_REVIEW", "output": resolved_output}

        _advance(db, run_id, block, resolved_output)
        return {"status": "COMPLETED", "output": resolved_output}

    except BlockExecutionError as exc:
        step = db.query(WorkflowRunStep).filter(
            WorkflowRunStep.run_id == run_id,
            WorkflowRunStep.block_instance_id == block_instance_id,
        ).first()
        retry_count = int((block.config or {}).get("retryCount", 2)) if block is not None else 2
        if step is not None:
            step.error_code = exc.error_code
            step.completed_at = datetime.utcnow()
        if not exc.permanent and self.request.retries < retry_count:
            db.commit()
            raise self.retry(exc=exc, max_retries=retry_count)
        if step is not None:
            step.status = "FAILED"
            step.error_message = _localize_error_message(exc)[:500]
        run = db.get(WorkflowRun, run_id)
        if run is not None:
            run.status = "FAILED"
            run.error_message = _localize_error_message(exc)[:500]
            run.completed_at = datetime.utcnow()
            _fail_document(db, run, _localize_error_message(exc))
        db.commit()
        raise

    except Exception as exc:
        step = db.query(WorkflowRunStep).filter(
            WorkflowRunStep.run_id == run_id,
            WorkflowRunStep.block_instance_id == block_instance_id,
        ).first()
        if step is not None:
            step.status = "FAILED"
            step.error_message = _localize_error_message(exc)[:500]
            step.completed_at = datetime.utcnow()
        run = db.get(WorkflowRun, run_id)
        if run is not None:
            run.status = "FAILED"
            run.error_message = _localize_error_message(exc)[:500]
            run.completed_at = datetime.utcnow()
            _fail_document(db, run, _localize_error_message(exc))
        db.commit()
        raise


def _maybe_trigger_analysis(db, run) -> None:
    """A PREPROCESS run that just completed on a document in a collection with
    Collection.default_analysis_workflow_id set kicks off that ANALYSIS workflow
    automatically against the same document (컬렉션 생성/수정 시 지정한 기본
    분석 워크플로우). Guarded to only fire off a
    PREPROCESS run's completion so an ANALYSIS run's own completion can never
    recursively trigger another analysis run."""
    from app.db.models.collection import Collection
    from app.db.models.document import Document
    from app.db.models.workflow import WorkflowBlockInstance, WorkflowDefinition, WorkflowEdge, WorkflowVersion
    from app.db.models.workflow_run import WorkflowRun

    if not run.document_id:
        return
    version = db.get(WorkflowVersion, run.version_id)
    workflow = db.get(WorkflowDefinition, version.workflow_id) if version else None
    if workflow is None or workflow.kind != "PREPROCESS":
        return

    document = db.get(Document, run.document_id)
    if document is None or not document.collection_id:
        return
    collection = db.get(Collection, document.collection_id)
    if collection is None or not collection.default_analysis_workflow_id:
        return

    analysis_version_query = db.query(WorkflowVersion).filter(
        WorkflowVersion.workflow_id == collection.default_analysis_workflow_id
    )
    if collection.default_analysis_workflow_version is not None:
        analysis_version = analysis_version_query.filter(
            WorkflowVersion.version_number == collection.default_analysis_workflow_version
        ).first()
    else:
        analysis_version = analysis_version_query.filter(
            WorkflowVersion.published_at.isnot(None)
        ).order_by(WorkflowVersion.version_number.desc()).first()
    if analysis_version is None:
        return

    analysis_run = WorkflowRun(
        id=uuid4(),
        version_id=analysis_version.id, document_id=document.id, collection_id=collection.id,
        status="QUEUED", trigger="AUTO_ANALYSIS", dictionary_version=run.dictionary_version,
    )
    db.add(analysis_run)
    # Analysis block types (classify/extract_entities/.../summarize) aren't in
    # _STATUS_FOR_BLOCK_TYPE, so nothing else would move the document off its
    # stale "INDEXED" label for the run's whole duration. The run's
    # own completion path (_advance's terminal-block branch, above) already
    # sets doc.status back to "INDEXED" unconditionally when it finishes.
    document.status = "ANALYZING"
    # doc.active_run_id는 항상 "이 문서의 최신 run"을 가리켜야 한다
    # (reprocess_service.start_partial_reprocess도 동일 불변식을 명시적으로
    # 유지함). 이걸 빼먹으면 active_run_id가 이미 COMPLETED된 이전 PREPROCESS
    # run을 계속 가리켜, 이 analysis run이 멈추거나 실패해도 재처리/정체감지가
    # 전부 엉뚱한(이미 끝난) run을 보게 된다(2026-08-03 실측 — 문서
    # 17c08458.../92f34f36.../3bf3c8d4... 전부 이 경로로 확인).
    document.active_run_id = analysis_run.id
    db.commit()
    db.refresh(analysis_run)

    blocks = db.query(WorkflowBlockInstance).filter(
        WorkflowBlockInstance.version_id == analysis_version.id
    ).all()
    edges = db.query(WorkflowEdge).filter(WorkflowEdge.version_id == analysis_version.id).all()
    has_incoming = {e.to_block_id for e in edges}
    entry_blocks = [b for b in blocks if b.id not in has_incoming]
    for block in entry_blocks:
        # 300s 기본값은 Docling+cloud-VLM-OCR 에스컬레이션(2026-07-29 도입) 이후
        # 표/이미지 밀도가 높은 PDF의 text_extract에서 반복적으로 초과됐다.
        # celery의 hard time_limit 초과는 SIGKILL이라 step.status="RUNNING"
        # 커밋 이후 어떤 예외 핸들러도 못 돌고 그대로 영구 정지한다(2026-07-29
        # 배치 24건 중 24건이 이 경로로 멈춘 것을 로그로 확인).
        timeout_seconds = (block.config or {}).get("timeoutSeconds", 1800)
        run_workflow_step.apply_async(
            args=[str(analysis_run.id), str(block.id)], time_limit=timeout_seconds,
            queue=step_queue_for_block(block),
        )


def _advance(db, run_id: str, block, output: dict) -> None:
    """Resolve `block`'s outgoing edges and enqueue whatever should run next,
    or complete the run if `block` was terminal."""
    from app.db.models.workflow import WorkflowBlockInstance, WorkflowEdge
    from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep

    run = db.get(WorkflowRun, run_id)
    timeout_overrides = (run.timeout_overrides or {}) if run else {}

    outgoing = db.query(WorkflowEdge).filter(WorkflowEdge.from_block_id == block.id).all()
    taken_edges = [e for e in outgoing if _evaluate_condition(e.condition, output)]

    for edge in taken_edges:
        target = db.get(WorkflowBlockInstance, edge.to_block_id)
        timeout_seconds = timeout_overrides.get(target.block_type) or (target.config or {}).get("timeoutSeconds", 1800)
        if target.block_type == "merge":
            incoming_to_target = db.query(WorkflowEdge).filter(
                WorkflowEdge.to_block_id == target.id
            ).count()
            target_step = db.query(WorkflowRunStep).filter(
                WorkflowRunStep.run_id == run_id,
                WorkflowRunStep.block_instance_id == target.id,
            ).first()
            if target_step is None:
                target_step = WorkflowRunStep(
                    run_id=run_id, block_instance_id=target.id, status="PENDING"
                )
                db.add(target_step)
            # `or 0`: the column default only lands on flush, so a freshly
            # constructed step still has None here.
            target_step.completed_incoming_edges = (target_step.completed_incoming_edges or 0) + 1
            db.commit()
            if target_step.completed_incoming_edges >= incoming_to_target:
                run_workflow_step.apply_async(
                    args=[run_id, str(target.id)], time_limit=timeout_seconds,
                    queue=step_queue_for_block(target),
                )
        else:
            run_workflow_step.apply_async(
                args=[run_id, str(target.id)], time_limit=timeout_seconds,
                queue=step_queue_for_block(target),
            )

    if not taken_edges:
        # Terminal block for this branch — check whether the whole run is done.
        _maybe_complete_run(db, run_id)


def _maybe_complete_run(db, run_id: str) -> None:
    """If no step in the run is still PENDING/RUNNING, marks the run COMPLETED.

    A block with multiple incoming edges that isn't a "merge" block type gets
    dispatched once per completed upstream edge (no fan-in dedup), so it can
    run twice concurrently. Both duplicate runs call _advance() on
    completion; whichever finishes LAST is the only one guaranteed to see
    every other step as done. But that last one may itself resolve to an
    already-COMPLETED downstream step (run_workflow_step's dedup early
    return, above) and never reach this check at all — leaving every step
    COMPLETED yet the run stuck in RUNNING forever (실측: 2026-08-03,
    documents 17c08458.../92f34f36..., AUTO_ANALYSIS runs whose summarize
    block fan-in duplicated). So this check must also run from that dedup
    early-return path, not just from a fresh _advance() call — see its call
    site in run_workflow_step."""
    from app.db.models.document import Document
    from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep

    unfinished = db.query(WorkflowRunStep).filter(
        WorkflowRunStep.run_id == run_id,
        WorkflowRunStep.status.in_(["PENDING", "RUNNING"]),
    ).count()
    if unfinished != 0:
        return

    run = db.get(WorkflowRun, run_id)
    if run is None or run.status != "RUNNING":
        return

    run.status = "COMPLETED"
    run.completed_at = datetime.utcnow()
    if run.document_id:
        # rag_store normally sets Document.status="INDEXED" itself, but that
        # side effect is skipped whenever rag_store is served from
        # block_execution_cache instead of actually running (e.g. reprocessing
        # a document whose input is unchanged) — mirrors _fail_document's
        # unconditional terminal-status write on the failure side, so a run
        # that genuinely finishes always leaves the document in a consistent
        # terminal state regardless of which blocks were cache hits.
        doc = db.get(Document, run.document_id)
        if doc is not None and doc.status != "FAILED":
            doc.status = "INDEXED"
            doc.updated_at = datetime.utcnow()
    db.commit()
    _maybe_trigger_analysis(db, run)


@celery_app.task(name="tasks.resume_workflow_run", queue="normal", bind=True)
def resume_workflow_run(self, run_id: str) -> dict:
    """Resumes a WAITING_REVIEW run from the block it paused at (통합 설계서
    §7.4, case a/b — 승인/수정 후 승인). The API endpoint only validates
    permissions/state and enqueues this task; all DAG-walking happens here,
    in the same sync-session context `_advance`/`run_workflow_step` use."""
    from app.db.models.workflow import WorkflowBlockInstance
    from app.db.models.workflow_run import WorkflowRun
    from app.db.session import get_sync_db

    db = get_sync_db()
    try:
        run = db.get(WorkflowRun, run_id)
        if run is None or run.status != "WAITING_REVIEW":
            return {"status": "SKIPPED"}
        step = _find_paused_step(db, run_id)
        if step is None:
            return {"status": "NOT_FOUND"}
        block = db.get(WorkflowBlockInstance, step.block_instance_id)
        run.status = "RUNNING"
        db.commit()
        _advance(db, run_id, block, _resolve_output(step.output))
        return {"status": "RESUMED"}
    finally:
        db.close()


@celery_app.task(name="tasks.sweep_stuck_workflow_runs", queue="normal")
def sweep_stuck_workflow_runs() -> dict:
    """Celery beat이 주기적으로 호출해, 아무도 문서 상세 페이지를 열어보지
    않아도 RUNNING에 멈춘 run을 스스로 정리한다.

    Celery hard time_limit 초과는 billiard가 워커 fork 프로세스를 SIGKILL로
    직접 죽여서 애플리케이션 코드가 절대 잡을 수 없다 — run/step이 RUNNING으로
    영구히 남는다. 이전에는 `reprocess_service.reconcile_stuck_run()`이
    GET /documents/{id} 호출 시점에만 지연을 감지했는데, 그 문서를 아무도
    열어보지 않으면 정리가 영영 일어나지 않는 문제가 있었다. 판정 로직은
    reconcile_stuck_run과 동일 — 그쪽은 API 요청 컨텍스트의 AsyncSession을
    쓰고 이쪽은 셀러리 워커의 동기 세션을 쓰기 때문에 별도 구현이지만,
    `_TIMEOUT_GRACE_SECONDS`(유예시간)는 reprocess_service에서 그대로
    가져와 두 경로의 판정 기준이 어긋나지 않게 한다."""
    from app.db.models.workflow import WorkflowBlockInstance
    from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep
    from app.db.session import get_sync_db
    from app.services.reprocess_service import _TIMEOUT_GRACE_SECONDS, _seconds_since

    db = get_sync_db()
    swept_run_ids = []
    try:
        running_runs = db.query(WorkflowRun).filter(WorkflowRun.status == "RUNNING").all()
        for run in running_runs:
            stuck_step = db.query(WorkflowRunStep).filter(
                WorkflowRunStep.run_id == run.id,
                WorkflowRunStep.status == "RUNNING",
                WorkflowRunStep.started_at.isnot(None),
            ).first()
            if stuck_step is None:
                continue

            block = db.get(WorkflowBlockInstance, stuck_step.block_instance_id)
            block_type = block.block_type if block else None
            timeout_seconds = (run.timeout_overrides or {}).get(block_type) or (
                (block.config or {}).get("timeoutSeconds", 1800) if block else 1800
            )
            elapsed = _seconds_since(stuck_step.started_at)
            if elapsed <= timeout_seconds + _TIMEOUT_GRACE_SECONDS:
                continue

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
            _fail_document(db, run, message)
            db.commit()
            swept_run_ids.append(str(run.id))
        return {"swept_run_ids": swept_run_ids}
    finally:
        db.close()
