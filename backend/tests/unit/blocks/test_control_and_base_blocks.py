"""control_blocks(branch/merge) 및 base.py 계약 테스트."""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.blocks.base import (
    ERROR_CODES,
    PERMANENT_ERROR_CODES,
    BaseBlock,
    BlockContext,
    BlockExecutionError,
    BlockResult,
)
from app.pipeline.blocks.control_blocks import BranchBlock, MergeBlock


def _ctx(upstream):
    return BlockContext(run_id="r", block_instance_id="b", upstream_outputs=upstream)


# ---- BranchBlock ----
def test_branch_passes_first_upstream_through():
    result = BranchBlock().run(_ctx({"a": {"text": "t"}, "b": {"text": "other"}}))
    assert result.output == {"text": "t"}


def test_branch_without_upstream_is_empty():
    assert BranchBlock().run(_ctx({})).output == {}


# ---- MergeBlock ----
def test_merge_first_branch_wins_for_scalars():
    ups = {"a": {"text": "A", "n": 1}, "b": {"text": "B", "extra": 2}}
    assert MergeBlock().run(_ctx(ups)).output == {"text": "A", "n": 1, "extra": 2}


def test_merge_unions_lists_in_branch_order_without_duplicates():
    ups = {"a": {"keywords": ["x", "y"]}, "b": {"keywords": ["y", "z"]}, "c": {"keywords": ["z", "w"]}}
    assert MergeBlock().run(_ctx(ups)).output["keywords"] == ["x", "y", "z", "w"]


def test_merge_mixed_types_keep_first_value():
    ups = {"a": {"k": ["x"]}, "b": {"k": "scalar"}}
    assert MergeBlock().run(_ctx(ups)).output["k"] == ["x"]


def test_merge_does_not_mutate_inputs():
    first = {"keywords": ["x"]}
    MergeBlock().run(_ctx({"a": first, "b": {"keywords": ["y"]}}))
    assert first["keywords"] == ["x"]


def test_merge_empty():
    assert MergeBlock().run(_ctx({})).output == {}


@pytest.mark.parametrize("block,btype", [(BranchBlock, "branch"), (MergeBlock, "merge")])
def test_control_metadata(block, btype):
    instance = block()
    assert (instance.block_type, instance.category) == (btype, "품질·제어")
    assert instance.config_schema is None
    assert instance.input_schema == {}
    assert instance.block_version == "1.0.0"


# ---- base ----
class _Bare(BaseBlock):
    @property
    def block_type(self) -> str:
        return "bare"

    def run(self, context):
        return BlockResult(output={})


def test_base_block_requires_explicit_category():
    with pytest.raises(NotImplementedError, match="_Bare"):
        _Bare().category


def test_base_block_cannot_be_instantiated_without_abstract_members():
    with pytest.raises(TypeError):
        BaseBlock()


def test_block_result_defaults_are_independent():
    a, b = BlockResult(output={}), BlockResult(output={})
    a.warnings.append("w")
    a.metrics["k"] = 1
    assert b.warnings == [] and b.metrics == {} and b.requires_review is False


def test_block_context_defaults_are_independent():
    a, b = BlockContext(run_id="1", block_instance_id="x"), BlockContext(run_id="2", block_instance_id="y")
    a.upstream_outputs["k"] = {}
    assert b.upstream_outputs == {} and b.config == {} and b.skip_review is False
    assert b.step_id is None and b.document_id is None


def test_block_context_load_artifact_downloads_and_parses_json():
    storage = MagicMock()
    storage.download_file.return_value = json.dumps({"text": "한글"}, ensure_ascii=False).encode()
    with patch("app.services.storage.storage_service", storage):
        data = BlockContext(run_id="r", block_instance_id="b").load_artifact("runs/r/s/output.json")
    assert data == {"text": "한글"}
    assert storage.download_file.call_args.args[1] == "runs/r/s/output.json"


def test_block_execution_error_carries_code_and_permanence():
    err = BlockExecutionError("실패", error_code="OCR_FAILED")
    assert str(err) == "실패" and err.error_code == "OCR_FAILED" and err.permanent is False
    assert BlockExecutionError("x", "FILE_ENCRYPTED", permanent=True).permanent is True


def test_permanent_codes_are_subset_of_known_codes():
    assert PERMANENT_ERROR_CODES <= ERROR_CODES
    assert "STORAGE_FAILED" in ERROR_CODES and "STORAGE_FAILED" not in PERMANENT_ERROR_CODES
