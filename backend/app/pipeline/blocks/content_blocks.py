"""Content-processing block types: 입력/전처리/분류/개체추출/키워드추출/요약/검증.

Each `run()` is intentionally a thin, stubbed implementation — real parsing,
dictionary application, NER, and summarization logic already exist elsewhere
in the pipeline (app/pipeline/adapters, app/services) and should be wired in
per block once the DAG executor itself (app/pipeline/tasks/workflow.py) is
proven correct on stubs, per the workflow-editor plan's risk mitigation.
"""
from app.pipeline.blocks.base import BaseBlock, BlockContext, BlockResult


class InputBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "input"

    def run(self, context: BlockContext) -> BlockResult:
        return BlockResult(output={
            "document_id": context.config.get("document_id"),
            "collection_id": context.config.get("collection_id"),
        })


class PreprocessBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "preprocess"

    def run(self, context: BlockContext) -> BlockResult:
        text = next(iter(context.upstream_outputs.values()), {}).get("text", "")
        return BlockResult(output={"text": text})


class ClassifyBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "classify"

    def run(self, context: BlockContext) -> BlockResult:
        return BlockResult(output={"category": "unclassified"})


class ExtractEntitiesBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "extract_entities"

    def run(self, context: BlockContext) -> BlockResult:
        return BlockResult(output={"entities": []})


class ExtractKeywordsBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "extract_keywords"

    def run(self, context: BlockContext) -> BlockResult:
        return BlockResult(output={"keywords": []})


class SummarizeBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "summarize"

    def run(self, context: BlockContext) -> BlockResult:
        return BlockResult(output={"summary": ""})


class ValidateBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "validate"

    def run(self, context: BlockContext) -> BlockResult:
        return BlockResult(output={"is_valid": True})
