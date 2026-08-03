"""Unit coverage for the block registry (app/pipeline/blocks/registry.py) —
the single source of truth for valid block_type values used by
workflow_service (save-time validation), the executor (dispatch), and the
GET /workflows/block-types endpoint.

A generic "run every block with an empty context" test used to live here,
from when every block was a stateless design-doc stub (input/preprocess/
classify/.../output). Real blocks now have block-specific preconditions
(InputBlock needs document_id + DB, PreprocessBlock/ClassifyBlock/etc. need
upstream text, FileValidateBlock/TextExtractBlock/RagStoreBlock need a real
document/DB/Qdrant/MinIO) — each is already covered by its own test module
under tests/unit/blocks/ and tests/unit/adapters/, so that generic pass was
removed rather than papered over with block-specific mocking here."""
from app.pipeline.blocks.registry import BLOCK_REGISTRY

EXPECTED_BLOCK_TYPES = {
    "input", "preprocess", "classify", "extract_entities", "extract_keywords",
    "summarize", "validate", "branch", "merge", "postprocess", "output",
    "file_validate", "format_detect", "text_extract", "ocr", "chunk_split",
    "rag_store", "text_clean", "stopword", "synonym", "user_dict",
    "structure_analyze", "pii_detect", "quality_check",
}


def test_registry_contains_every_design_doc_block_type():
    assert set(BLOCK_REGISTRY.keys()) == EXPECTED_BLOCK_TYPES


def test_merge_block_flattens_upstream_outputs_first_branch_wins():
    from app.pipeline.blocks.base import BlockContext

    # MergeBlock flattens branch outputs into one top-level dict so downstream
    # blocks find text/summary/keywords directly (control_blocks.py) — no
    # "merged" wrapper key. Scalars keep the first branch's value; lists union.
    context = BlockContext(
        run_id="run-1",
        block_instance_id="merge-1",
        upstream_outputs={
            "branch-a": {"path": "a", "tags": ["x"]},
            "branch-b": {"path": "b", "tags": ["y"]},
        },
        config={},
    )
    result = BLOCK_REGISTRY["merge"]().run(context)
    assert result.output["path"] == "a"
    assert result.output["tags"] == ["x", "y"]
