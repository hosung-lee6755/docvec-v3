from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class BlockContext:
    run_id: str
    block_instance_id: str
    # Keyed by upstream block_instance_id -> that block's output dict. A block
    # with multiple incoming edges (i.e. a 병합 block) sees every upstream
    # output here; a block with one incoming edge sees a single entry.
    upstream_outputs: dict[str, dict] = field(default_factory=dict)
    # This block instance's saved config (validated against input_schema by
    # workflow_service.validate_graph before the run is ever started).
    config: dict = field(default_factory=dict)
    # What this run was started against (WorkflowRun.document_id /
    # .collection_id) — how the 입력 block knows which document to load.
    document_id: str | None = None
    collection_id: str | None = None


@dataclass
class BlockResult:
    output: dict


class BaseBlock(ABC):
    @property
    @abstractmethod
    def block_type(self) -> str:
        ...

    @property
    def input_schema(self) -> dict:
        """JSON-schema-shaped dict describing required `config` keys. Empty
        dict means no required config. Used by workflow_service for
        save-time validation, not enforced at runtime by the block itself."""
        return {}

    @abstractmethod
    def run(self, context: BlockContext) -> BlockResult:
        ...
