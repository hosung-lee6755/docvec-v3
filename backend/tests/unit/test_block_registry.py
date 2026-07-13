"""Unit coverage for the fixed block registry — every design-doc block type
is registered and its stub run() returns a well-formed BlockResult."""
from app.pipeline.blocks.base import BlockContext
from app.pipeline.blocks.registry import BLOCK_REGISTRY

EXPECTED_BLOCK_TYPES = {
    "input", "preprocess", "classify", "extract_entities", "extract_keywords",
    "summarize", "validate", "branch", "merge", "postprocess", "output",
}


def test_registry_contains_every_design_doc_block_type():
    assert set(BLOCK_REGISTRY.keys()) == EXPECTED_BLOCK_TYPES


def test_every_block_runs_and_returns_output_dict():
    context = BlockContext(run_id="run-1", block_instance_id="block-1", upstream_outputs={}, config={})
    for block_type, block_cls in BLOCK_REGISTRY.items():
        result = block_cls().run(context)
        assert isinstance(result.output, dict), f"{block_type} did not return a dict output"


def test_merge_block_addresses_output_by_upstream_block_id():
    from app.pipeline.blocks.registry import BLOCK_REGISTRY

    context = BlockContext(
        run_id="run-1",
        block_instance_id="merge-1",
        upstream_outputs={"branch-a": {"path": "a"}, "branch-b": {"path": "b"}},
        config={},
    )
    result = BLOCK_REGISTRY["merge"]().run(context)
    assert result.output["merged"] == {"branch-a": {"path": "a"}, "branch-b": {"path": "b"}}
