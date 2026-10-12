"""DAG executor for user-defined workflows (app/db/models/workflow.py).

Unlike the fixed document pipeline (tasks/pipeline.py, a static Celery
chain()), a workflow graph can branch (조건분기) and merge (병합), so it is
walked one block at a time: each completed block resolves its own outgoing
WorkflowEdges and enqueues whatever comes next, rather than being composed
into one static chain up front.
"""
import hashlib
import json
import logging
import re
from datetime import datetime
from uuid import uuid4

from app.pipeline.blocks.base import BlockContext, BlockExecutionError
from app.pipeline.blocks.registry import BLOCK_REGISTRY
from app.pipeline.celery_app import celery_app

logger = logging.getLogger(__name__)

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


# GPU 모델을 쓰는 블록: rag_store는 임베딩, 분석 블록 넷은 로컬 LLM(qwen2.5-3b)을 호출하고,
# output은 요약을 저장한 뒤 요약 인덱스용으로 BGE-M3 임베딩을 호출한다.
_GPU_BLOCK_TYPES = frozenset({
    "rag_store", "summarize", "extract_keywords", "classify", "extract_entities", "output",
})


def step_queue_for_block(block) -> str:
    """어느 블록이 GPU 모델(임베딩·로컬 LLM)을 쓰는지에 따라 실행 큐를 나눈다 —
    rag_store, 분석 블록(요약/키워드/분류/개체), output(요약 인덱스)은 항상, chunk_split은
    strategy=semantic일 때만 모델을 호출한다. 이 블록들을 별도의 'embed' 큐로 보내면 worker-embed
    컨테이너(concurrency=1)가 순차 실행해, 프로세스마다 모델 사본을 올려 GPU 메모리 하나를
    여러 워커 슬롯이 동시에 점유하며 서로 밀어내는 경합(CUDA launch failure)을 막는다."""
    if block.block_type in _GPU_BLOCK_TYPES:
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
    file_hash: str | None = None,
) -> str:
    # file_hash(원본 체크섬)는 같은 document_id의 원본이 교체돼도(재업로드/복원)
    # 이전 내용의 캐시 출력을 재사용하지 않도록 키에 섞는다 — 엔트리 블록은 상류
    # 출력이 없어 input_hash만으로는 원본 변경을 감지할 수 없다.
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
        f"{dict_version_part}:{skip_review_part}:{file_hash}".encode()
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


_LIVE_RUN_STATUSES = ("QUEUED", "RUNNING", "WAITING_REVIEW")


def _fail_document(db, run, error_message: str) -> None:
    """Mirrors the retired fixed pipeline's failure behavior (parse_document/
    continue_processing always set Document.status="FAILED" on error) so the
    document list/detail UI still surfaces workflow-driven failures.

    Defect 3: Guard active_run_id 갱신 — 늦게 도착한 이전 run이 최신 run을
    덮어쓰면 안 됨. _maybe_complete_run과 동일한 guard를 적용."""
    from app.db.models.document import Document

    from app.db.models.workflow_run import WorkflowRun

    if not run.document_id:
        return
    doc = db.get(Document, run.document_id)
    if doc is None:
        return
    # 문서가 다른 run을 아직 진행 중으로 가리키면(재처리 등) 늦게 실패한 옛 run이
    # 문서 상태/오류/active_run_id 어느 것도 건드리면 안 된다 (Defect 3).
    # 가리키는 run이 이미 끝났거나 사라졌다면 stale 포인터이므로 이 run으로 바로잡는다
    # (AUTO_ANALYSIS run 실패 시에도 active_run_id가 실패한 run을 가리켜야 한다).
    if doc.active_run_id is not None and str(doc.active_run_id) != str(run.id):
        other = db.get(WorkflowRun, doc.active_run_id)
        if other is not None and other.status in _LIVE_RUN_STATUSES:
            return
    doc.status = "FAILED"
    doc.error_message = error_message[:500]
    doc.active_run_id = run.id


def _find_paused_step(db, run_id: str) -> "WorkflowRunStep | None":
    """Finds the step a WAITING_REVIEW run halted at — the run stops
    _advance() the instant a block requests review, so exactly one COMPLETED
    step exists whose taken outgoing edges point at blocks with no step row
    yet (every other completed step already had _advance() run for it,
    which always creates a step row for each taken edge's target).

    Defect 14: 타입 힌트 추가."""
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

        # 이미 FAILED/CANCELLED인 run은 더 이상 step을 실행하지 않는다
        # (Defect 4: 단말 상태 확인).
        if run.status in ("FAILED", "CANCELLED"):
            return {"status": "SKIPPED"}

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
        cache_document = db.get(Document, run.document_id) if run.document_id else None
        cache_key = _compute_cache_key(
            str(run.document_id) if run.document_id else None,
            step.input_hash, block.block_type, block_instance.block_version, block.config or {},
            dictionary_version=run.dictionary_version,
            skip_review=bool(run.skip_review),
            file_hash=cache_document.file_hash if cache_document is not None else None,
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
        # Defect 2: PendingRollbackError 방지를 위해 먼저 rollback 수행
        db.rollback()
        step = db.query(WorkflowRunStep).filter(
            WorkflowRunStep.run_id == run_id,
            WorkflowRunStep.block_instance_id == block_instance_id,
        ).first()
        retry_count = int((block.config or {}).get("retryCount", 2)) if block is not None else 2
        if step is not None:
            step.error_code = exc.error_code
            # Defect 7: retry 중에는 completed_at을 설정하지 않음 — status가 여전히 RUNNING이어야 함
            if exc.permanent or self.request.retries >= retry_count:
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
        # Defect 2: PendingRollbackError 방지를 위해 먼저 rollback 수행
        db.rollback()
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

    finally:
        # Defect 1: 연결 풀 누수 방지 — 모든 경로에서 db 세션 반환
        db.close()


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
    # documents.active_run_id ↔ workflow_runs.document_id 는 외래키가 순환이라, run을
    # 먼저 DB에 내보내지 않으면 작업 단위가 documents UPDATE를 workflow_runs INSERT보다
    # 앞세워 fk_documents_active_run_id 위반이 난다(컬렉션에 기본 분석 워크플로우를
    # 지정한 업로드 15건 중 12건이 이 경로로 FAILED). reprocess_service와 같은 순서.
    db.flush()
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


def _advance(
    db, run_id: str, block: "WorkflowBlockInstance | None", output: dict,
    only_targets: "set | None" = None,
) -> None:
    """Resolve `block`'s outgoing edges and enqueue whatever should run next,
    or complete the run if `block` was terminal.

    `only_targets`: 주어지면 그 대상 블록으로 가는 엣지만 처리한다. sweeper 의 재디스패치가
    유실된 가지만 다시 낼 때 쓴다 — 이미 처리된 엣지까지 다시 훑으면 merge 카운터가 중복
    증가해 merge 가 업스트림이 끝나기 전에 실행된다.

    Defect 14: 타입 힌트 추가."""
    from app.db.models.workflow import WorkflowBlockInstance, WorkflowEdge
    from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep

    if block is None:
        return

    run = db.get(WorkflowRun, run_id)

    # Defect 4: 단말 상태인 run은 더 진행하지 않음
    if run is not None and run.status in ("FAILED", "CANCELLED"):
        return

    timeout_overrides = (run.timeout_overrides or {}) if run else {}

    outgoing = db.query(WorkflowEdge).filter(WorkflowEdge.from_block_id == block.id).all()
    taken_edges = [
        e for e in outgoing
        if _evaluate_condition(e.condition, output)
        and (only_targets is None or e.to_block_id in only_targets)
    ]

    for edge in taken_edges:
        target = db.get(WorkflowBlockInstance, edge.to_block_id)
        # Defect 4: target이 None이 아닌지 확인 (타입 힌트로도 보강 필요)
        if target is None:
            continue
        timeout_seconds = timeout_overrides.get(target.block_type) or (target.config or {}).get("timeoutSeconds", 1800)
        if target.block_type == "merge":
            incoming_to_target = db.query(WorkflowEdge).filter(
                WorkflowEdge.to_block_id == target.id
            ).count()
            # Defect 5: 두 업스트림이 동시에 도착해도 step 행은 (run_id,
            # block_instance_id) 유니크 제약 + ON CONFLICT DO NOTHING으로 한 번만
            # 만들어지고, 카운터는 원자적 UPDATE ... RETURNING으로 정확히 한 번씩
            # 증가한다. 마지막 업스트림만 incoming_to_target에 도달해 dispatch한다.
            from sqlalchemy import update
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            db.execute(
                pg_insert(WorkflowRunStep)
                .values(
                    id=uuid4(), run_id=run_id, block_instance_id=target.id,
                    status="PENDING", completed_incoming_edges=0,
                    created_at=datetime.utcnow(),
                )
                .on_conflict_do_nothing(
                    constraint="uq_workflow_run_steps_run_id_block_instance_id"
                )
            )
            updated_count = db.execute(
                update(WorkflowRunStep)
                .where(
                    WorkflowRunStep.run_id == run_id,
                    WorkflowRunStep.block_instance_id == target.id,
                )
                .values(completed_incoming_edges=WorkflowRunStep.completed_incoming_edges + 1)
                .returning(WorkflowRunStep.completed_incoming_edges)
            ).scalar()
            db.commit()

            # 업데이트된 값을 확인해서 dispatch 결정
            if updated_count is not None and updated_count >= incoming_to_target:
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

    # 조건부 UPDATE: 중복 디스패치된 스텝을 처리한 두 워커가 모두 RUNNING 으로 읽어도 상태 전이는
    # 한 번만 성공한다. 단순 대입이면 둘 다 _maybe_trigger_analysis 를 불러 AUTO_ANALYSIS run 이
    # 둘 생기고 나중 것이 active_run_id 를 덮어쓴다.
    from sqlalchemy import update

    completed_at = datetime.utcnow()
    claimed = db.execute(
        update(WorkflowRun)
        .where(WorkflowRun.id == run_id, WorkflowRun.status == "RUNNING")
        .values(status="COMPLETED", completed_at=completed_at)
    )
    if claimed.rowcount == 0:
        db.rollback()
        return
    # 선점한 행과 메모리 객체를 같은 값으로 맞춘다(아래 문서 갱신·분석 트리거가 이 객체를 쓴다).
    run.status = "COMPLETED"
    run.completed_at = completed_at
    if run.document_id:
        # rag_store normally sets Document.status="INDEXED" itself, but that
        # side effect is skipped whenever rag_store is served from
        # block_execution_cache instead of actually running (e.g. reprocessing
        # a document whose input is unchanged) — mirrors _fail_document's
        # unconditional terminal-status write on the failure side, so a run
        # that genuinely finishes always leaves the document in a consistent
        # terminal state regardless of which blocks were cache hits.
        #
        # The guard here must be "is this still the document's active run",
        # NOT "doc.status != FAILED" — a reprocess kicked off on a FAILED
        # document (batch-reprocess, partial reprocess) leaves doc.status
        # literally "FAILED" for the whole run if nothing else updates it in
        # the meantime (e.g. an analysis-tier start block with no
        # _STATUS_FOR_BLOCK_TYPE mapping). The old check treated that as "some
        # other path already marked this FAILED, don't overwrite it" and
        # refused to flip a genuinely successful reprocess back to INDEXED —
        # the document stayed stuck showing FAILED forever despite every step
        # completing (실측: 2026-08-03, documents 3bf3c8d4.../16e00066...).
        # Checking active_run_id instead only skips the flip for a truly
        # stale/superseded run finishing late after a newer one took over.
        doc = db.get(Document, run.document_id)
        if doc is not None and str(doc.active_run_id) == str(run.id):
            doc.status = "INDEXED"
            # 실패 후 재처리가 성공한 경우 이전 실패 사유가 INDEXED 문서에 남지 않게 지운다.
            doc.error_message = None
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


# 마지막 스텝 활동 이후 이 시간이 지나도 진행 중인 스텝이 없으면 다음 스텝 메시지가
# 유실된 것으로 본다. embed 큐는 concurrency=1이라 대기열이 수 분 쌓일 수 있어, 정상적인
# 대기를 유실로 오판하지 않도록 넉넉히 잡는다.
_ORPHAN_RUN_GRACE_SECONDS = 600


def _redispatch_orphaned_run(db, run) -> bool:
    """워커가 재시작/크래시하면 방금 끝난 스텝의 다음 스텝 메시지가 브로커에서 유실될 수
    있다(실측: worker-embed 재시작 후 요약만 끝난 분석 run 4건과 임베딩 중이던 문서가
    RUNNING에 영구히 멈춤). 이 경우 RUNNING 스텝이 없어 타임아웃 판정에 걸리지 않으므로,
    진행 중인 스텝이 없고 마지막 활동이 오래된 run은 완료된 스텝에서 다음 스텝을 다시 낸다.

    다음 스텝의 PENDING 행을 먼저 만들어 두므로(생성 시각이 곧 마지막 디스패치 시각이다) 같은
    run이 매 sweep마다 다시 디스패치되지 않는다. 재디스패치한 메시지까지 유실돼 PENDING만
    남은 경우(merge가 아닌 스텝)에도 그 시각이 유예시간을 넘기면 같은 스텝을 다시 낸다.
    RUNNING 스텝이 있으면 타임아웃 판정이 맡으므로 이 함수는 건너뛴다."""
    from app.db.models.workflow import WorkflowBlockInstance, WorkflowEdge
    from app.db.models.workflow_run import WorkflowRunStep
    from app.services.reprocess_service import _seconds_since
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    steps = db.query(WorkflowRunStep).filter(WorkflowRunStep.run_id == run.id).all()
    if not steps or any(s.status == "RUNNING" for s in steps):
        return False
    idle_seconds = min(
        _seconds_since(moment)
        for s in steps
        for moment in (s.completed_at, s.started_at, s.created_at)
        if moment is not None
    )
    if idle_seconds <= _ORPHAN_RUN_GRACE_SECONDS:
        return False

    stale_pending = []
    for step in steps:
        if step.status != "PENDING":
            continue
        block = db.get(WorkflowBlockInstance, step.block_instance_id)
        # merge의 PENDING은 다른 업스트림을 기다리는 정상 상태라 단독으로 다시 내지 않는다.
        if block is not None and block.block_type != "merge":
            stale_pending.append((step, block))

    existing_block_ids = {s.block_instance_id for s in steps}
    to_advance = []
    for step in steps:
        if step.status != "COMPLETED":
            continue
        block = db.get(WorkflowBlockInstance, step.block_instance_id)
        if block is None:
            continue
        output = _resolve_output(step.output)
        edges = db.query(WorkflowEdge).filter(WorkflowEdge.from_block_id == block.id).all()
        missing_targets = [
            e.to_block_id for e in edges
            if _evaluate_condition(e.condition, output) and e.to_block_id not in existing_block_ids
        ]
        if missing_targets:
            to_advance.append((block, output, missing_targets))
    if not to_advance and not stale_pending:
        # 이을 다음 스텝도, 다시 낼 스텝도 없다. 모든 스텝이 끝났는데 마지막 스텝 직후 워커가 죽어
        # 완료 처리(_maybe_complete_run)만 유실된 경우라면 run 을 완료로 닫는다. 진행 중인 스텝이
        # 남아 있으면 _maybe_complete_run 이 아무것도 하지 않는다.
        _maybe_complete_run(db, str(run.id))
        db.refresh(run)
        return run.status == "COMPLETED"

    for _block, _output, missing_targets in to_advance:
        for target_id in missing_targets:
            db.execute(
                pg_insert(WorkflowRunStep)
                .values(
                    id=uuid4(), run_id=run.id, block_instance_id=target_id,
                    status="PENDING", completed_incoming_edges=0, created_at=datetime.utcnow(),
                )
                .on_conflict_do_nothing(constraint="uq_workflow_run_steps_run_id_block_instance_id")
            )
    # PENDING 행의 created_at이 곧 마지막 디스패치 시각이다 — 다시 내기 전에 갱신해 두어야
    # 다음 sweep이 같은 스텝을 또 내지 않는다.
    for step, _block in stale_pending:
        step.created_at = datetime.utcnow()
    db.commit()

    for block, output, missing_targets in to_advance:
        _advance(db, str(run.id), block, output, only_targets=set(missing_targets))
    timeout_overrides = run.timeout_overrides or {}
    for _step, block in stale_pending:
        timeout_seconds = timeout_overrides.get(block.block_type) or (block.config or {}).get("timeoutSeconds", 1800)
        run_workflow_step.apply_async(
            args=[str(run.id), str(block.id)], time_limit=timeout_seconds,
            queue=step_queue_for_block(block),
        )
    return True


def _try_redispatch(db, run) -> bool:
    """run 하나의 재디스패치 실패(artifact 읽기 실패, 브로커 장애 등)가 같은 sweep 의 나머지 run
    정리를 막지 않도록 격리한다. 실패한 run 은 롤백하고 기록만 남겨, 다음 sweep 에서 다시 시도한다."""
    try:
        return _redispatch_orphaned_run(db, run)
    except Exception:  # noqa: BLE001 — 한 run 의 실패가 전체 sweep 을 중단시키면 안 된다
        db.rollback()
        logger.exception("고아 run 재디스패치 실패: run_id=%s", run.id)
        return False


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
    from sqlalchemy import update

    db = get_sync_db()
    swept_run_ids = []
    redispatched_run_ids = []
    try:
        running_runs = db.query(WorkflowRun).filter(WorkflowRun.status == "RUNNING").all()
        for run in running_runs:
            stuck_step = db.query(WorkflowRunStep).filter(
                WorkflowRunStep.run_id == run.id,
                WorkflowRunStep.status == "RUNNING",
                WorkflowRunStep.started_at.isnot(None),
            ).first()
            if stuck_step is None:
                if _try_redispatch(db, run):
                    redispatched_run_ids.append(str(run.id))
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

            # Defect 6: 조건부 UPDATE 사용 — 동시에 진행 중인 step을 덮어쓰지 않음.
            # 스텝이 이미 완료되거나 RUNNING을 벗어났다면 sweeper가 상태를 변경하지 않음.
            result = db.execute(
                update(WorkflowRunStep)
                .where(
                    WorkflowRunStep.id == stuck_step.id,
                    WorkflowRunStep.status == "RUNNING",  # Only update if still RUNNING
                )
                .values(
                    status="FAILED",
                    error_code="TIMEOUT_EXCEEDED",
                    error_message=message,
                    completed_at=datetime.utcnow(),
                )
            )

            # Step 업데이트가 실제로 일어났는지 확인
            if result.rowcount > 0:
                # Run도 조건부로 업데이트
                db.execute(
                    update(WorkflowRun)
                    .where(WorkflowRun.id == run.id, WorkflowRun.status == "RUNNING")
                    .values(
                        status="FAILED",
                        error_message=message,
                        completed_at=datetime.utcnow(),
                    )
                )
                # Document 상태 갱신
                _fail_document(db, run, message)
                db.commit()
                swept_run_ids.append(str(run.id))
        return {"swept_run_ids": swept_run_ids, "redispatched_run_ids": redispatched_run_ids}
    finally:
        db.close()
