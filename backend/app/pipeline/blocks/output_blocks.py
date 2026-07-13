"""Terminal block types: 후처리/출력.

OutputBlock is currently a no-op sink (returns its input as the run's final
output). Wiring it to a real destination (storage write, export file,
outbound API call, per the design doc's "저장, 내보내기, API 전달") is
follow-up work once the executor is proven — same rationale as the stubbed
content blocks in content_blocks.py.
"""
from app.pipeline.blocks.base import BaseBlock, BlockContext, BlockResult


class PostprocessBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "postprocess"

    def run(self, context: BlockContext) -> BlockResult:
        return BlockResult(output=next(iter(context.upstream_outputs.values()), {}))


class OutputBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "output"

    def run(self, context: BlockContext) -> BlockResult:
        return BlockResult(output=next(iter(context.upstream_outputs.values()), {}))
