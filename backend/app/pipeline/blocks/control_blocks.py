"""Control-flow block types: 조건분기/병합.

Neither block evaluates conditions itself — WorkflowEdge.condition (evaluated
by the executor in app/pipeline/tasks/workflow.py) decides which outgoing
edge(s) of a 조건분기 block fire. These blocks just pass upstream output
through so the executor has something to evaluate/merge.
"""
from app.pipeline.blocks.base import BaseBlock, BlockContext, BlockResult


class BranchBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "branch"

    def run(self, context: BlockContext) -> BlockResult:
        return BlockResult(output=next(iter(context.upstream_outputs.values()), {}))


class MergeBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "merge"

    def run(self, context: BlockContext) -> BlockResult:
        # Keep each upstream branch's output addressable by source block id
        # rather than silently overwriting on key collision.
        return BlockResult(output={"merged": dict(context.upstream_outputs)})
