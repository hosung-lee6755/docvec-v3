import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from pydantic import BaseModel


@dataclass
class BlockContext:
    run_id: str
    block_instance_id: str
    # The WorkflowRunStep row's own id (distinct from block_instance_id, which
    # identifies the block *definition* in the graph, shared across every run).
    # Blocks that record per-run audit rows FK'd to workflow_run_steps.id
    # (CleaningChange, DictionaryApplication) must use this, not
    # block_instance_id.
    step_id: str | None = None
    # Keyed by upstream block_instance_id -> that block's output dict. A block
    # with multiple incoming edges (i.e. a 병합 block) sees every upstream
    # output here; a block with one incoming edge sees a single entry. Always
    # fully resolved by the executor — large outputs the executor offloaded to
    # an artifact are loaded back before being placed here (통합 설계서 §2.3),
    # so block code never needs to know or care whether an upstream output
    # came from an inline dict or an artifact.
    upstream_outputs: dict[str, dict] = field(default_factory=dict)
    # This block instance's saved config (validated against input_schema by
    # workflow_service.validate_graph before the run is ever started).
    config: dict = field(default_factory=dict)
    # What this run was started against (WorkflowRun.document_id /
    # .collection_id) — how the 입력 block knows which document to load.
    document_id: str | None = None
    collection_id: str | None = None
    # Mirrors WorkflowRun.skip_review — quality_check reads this to force
    # review_policy to auto_pass for this run only (9항목 펀치리스트 #1).
    skip_review: bool = False

    def load_artifact(self, ref: str) -> dict:
        """Fetches a large block output stored in MinIO (통합 설계서 §2.3,
        `runs/{run_id}/{step_id}/output.json`) by its artifact key. Exposed to
        blocks that need to explicitly reference another run's artifact (e.g.
        a future quality_check comparing before/after); the executor itself
        uses the same lookup to resolve `upstream_outputs` transparently."""
        from app.core.config import settings
        from app.services.storage import storage_service

        data = storage_service.download_file(settings.minio_bucket_artifacts, ref)
        return json.loads(data)


@dataclass
class BlockResult:
    output: dict
    # Non-fatal issues surfaced to quality_check/monitoring (설계서 §3.2) —
    # e.g. per-page OCR failures that don't fail the block itself (§18.3).
    warnings: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    # Set by a block (e.g. the future quality_check) to pause the run for
    # human review — the executor stops advancing the DAG and flips the run
    # to WAITING_REVIEW instead (설계서 §7.4).
    requires_review: bool = False


class BaseBlock(ABC):
    @property
    @abstractmethod
    def block_type(self) -> str:
        ...

    @property
    def block_version(self) -> str:
        """Bumped when a block's output shape/behavior changes in a way that
        should invalidate the execution cache (§2.4) for that block type."""
        return "1.0.0"

    @property
    def category(self) -> str:
        """Palette grouping for the workflow editor (설계서 §3.1) — every
        concrete block must set this explicitly, there is no sane default."""
        raise NotImplementedError(f"{type(self).__name__} must set `category`")

    @property
    def config_schema(self) -> type[BaseModel] | None:
        """Pydantic model describing `config`'s shape — drives save-time
        validation and UI form auto-generation (설계서 §3.2). None means the
        block takes no config."""
        return None

    @property
    def input_schema(self) -> dict:
        """JSON-schema-shaped dict describing required `config` keys. Empty
        dict means no required config. Used by workflow_service for
        save-time validation, not enforced at runtime by the block itself."""
        return {}

    @abstractmethod
    def run(self, context: BlockContext) -> BlockResult:
        ...


class BlockExecutionError(Exception):
    """Raised by a block to report a taxonomy-coded failure (설계서 §6/18장).
    `permanent=True` means retrying can never succeed (e.g. an unsupported or
    encrypted file) — the executor fails the step immediately instead of
    applying the block's configured retryCount."""

    def __init__(self, message: str, error_code: str, permanent: bool = False) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.permanent = permanent


ERROR_CODES = frozenset({
    "FILE_UNSUPPORTED", "FILE_CORRUPTED", "FILE_ENCRYPTED",
    "TEXT_EXTRACTION_FAILED", "OCR_FAILED", "STRUCTURE_ANALYSIS_FAILED",
    "CLEANING_RULE_ERROR", "DICTIONARY_CONFLICT", "CHUNK_SIZE_EXCEEDED",
    "QUALITY_THRESHOLD_FAILED", "STORAGE_FAILED", "WORKFLOW_TIMEOUT",
})

# 영구 오류 — 즉시 실패, 재시도 없음 (parse_document의 UnsupportedFileTypeError
# 즉시 실패 패턴의 일반화, 설계서 §6).
PERMANENT_ERROR_CODES = frozenset({"FILE_UNSUPPORTED", "FILE_ENCRYPTED"})
