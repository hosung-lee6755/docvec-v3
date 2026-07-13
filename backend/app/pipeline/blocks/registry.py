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

# Korean display names for user-facing messages (validation errors etc.).
# Must stay in sync with the frontend palette labels in
# frontend/src/lib/workflowBlocks.ts.
BLOCK_TYPE_LABELS: dict[str, str] = {
    "input": "입력",
    "preprocess": "전처리",
    "classify": "분류",
    "extract_entities": "개체 추출",
    "extract_keywords": "키워드 추출",
    "summarize": "요약",
    "validate": "검증",
    "branch": "조건 분기",
    "merge": "병합",
    "postprocess": "후처리",
    "output": "출력",
}
