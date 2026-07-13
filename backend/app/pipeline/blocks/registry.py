from app.pipeline.blocks.base import BaseBlock
from app.pipeline.blocks.content_blocks import (
    ClassifyBlock,
    ExtractEntitiesBlock,
    ExtractKeywordsBlock,
    InputBlock,
    PreprocessBlock,
    SummarizeBlock,
    ValidateBlock,
)
from app.pipeline.blocks.control_blocks import BranchBlock, MergeBlock
from app.pipeline.blocks.output_blocks import OutputBlock, PostprocessBlock

# Single source of truth for valid block_type values — used by
# workflow_service (save-time validation), the executor (dispatch), and the
# GET /workflows/block-types endpoint (drives the frontend palette).
BLOCK_REGISTRY: dict[str, type[BaseBlock]] = {
    "input": InputBlock,
    "preprocess": PreprocessBlock,
    "classify": ClassifyBlock,
    "extract_entities": ExtractEntitiesBlock,
    "extract_keywords": ExtractKeywordsBlock,
    "summarize": SummarizeBlock,
    "validate": ValidateBlock,
    "branch": BranchBlock,
    "merge": MergeBlock,
    "postprocess": PostprocessBlock,
    "output": OutputBlock,
}
