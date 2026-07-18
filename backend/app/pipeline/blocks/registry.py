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
from app.pipeline.blocks.extraction_blocks import (
    FileValidateBlock,
    FormatDetectBlock,
    OcrBlock,
    TextExtractBlock,
)
from app.pipeline.blocks.normalization_blocks import (
    StopwordBlock,
    SynonymBlock,
    TextCleanBlock,
    UserDictBlock,
)
from app.pipeline.blocks.output_blocks import OutputBlock, PostprocessBlock
from app.pipeline.blocks.pii_blocks import PiiDetectBlock
from app.pipeline.blocks.quality_blocks import QualityCheckBlock
from app.pipeline.blocks.storage_blocks import ChunkSplitBlock, RagStoreBlock
from app.pipeline.blocks.structure_blocks import StructureAnalyzeBlock

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
    "file_validate": FileValidateBlock,
    "format_detect": FormatDetectBlock,
    "text_extract": TextExtractBlock,
    "ocr": OcrBlock,
    "chunk_split": ChunkSplitBlock,
    "rag_store": RagStoreBlock,
    "text_clean": TextCleanBlock,
    "stopword": StopwordBlock,
    "synonym": SynonymBlock,
    "user_dict": UserDictBlock,
    "structure_analyze": StructureAnalyzeBlock,
    "pii_detect": PiiDetectBlock,
    "quality_check": QualityCheckBlock,
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
    "file_validate": "파일 검증",
    "format_detect": "형식 판별",
    "text_extract": "텍스트 추출",
    "ocr": "OCR",
    "chunk_split": "문서 분할",
    "rag_store": "RAG 저장",
    "text_clean": "텍스트 정제",
    "stopword": "불용어 처리",
    "synonym": "동의어 정규화",
    "user_dict": "사용자 사전 적용",
    "structure_analyze": "구조 분석",
    "pii_detect": "민감정보 탐지",
    "quality_check": "품질 검증",
}
