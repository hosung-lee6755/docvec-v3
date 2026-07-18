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

    @property
    def category(self) -> str:
        return "품질·제어"

    def run(self, context: BlockContext) -> BlockResult:
        return BlockResult(output=next(iter(context.upstream_outputs.values()), {}))


class MergeBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "merge"

    @property
    def category(self) -> str:
        return "품질·제어"

    def run(self, context: BlockContext) -> BlockResult:
        # Flatten the branches into one result downstream blocks can consume
        # directly (they look for top-level text/summary/keywords/...):
        # first branch wins for scalars (including text), lists are unioned
        # in branch order.
        merged: dict = {}
        for output in context.upstream_outputs.values():
            for key, value in output.items():
                if key not in merged:
                    merged[key] = value
                elif isinstance(merged[key], list) and isinstance(value, list):
                    merged[key] = merged[key] + [v for v in value if v not in merged[key]]
        return BlockResult(output=merged)
