"""GPU 모델(임베딩·로컬 LLM)을 쓰는 작업은 concurrency=1인 'embed' 큐로만 간다.

일반 worker(concurrency=4)도 GPU를 받기 때문에, LLM/임베딩 작업이 거기서 돌면 프로세스마다
모델 사본을 올려 12GB GPU 메모리를 두고 경합하다 `CUDA error: unspecified launch failure`로
문서가 FAILED가 된다(컬렉션 재처리 + 자동 분석 실측). "GPU는 한 건씩 차례로" 정책(2026-07-21)을
워크플로우 블록뿐 아니라 레거시 배치 태스크에도 적용한다.
"""
from types import SimpleNamespace

import pytest

from app.pipeline.tasks.workflow import step_queue_for_block


def _block(block_type: str, config: dict | None = None):
    return SimpleNamespace(block_type=block_type, config=config or {})


@pytest.mark.parametrize(
    "block_type",
    # output은 요약을 문서에 저장한 뒤 요약 인덱스용으로 BGE-M3 임베딩을 호출한다(GPU).
    ["rag_store", "summarize", "extract_keywords", "classify", "extract_entities", "output"],
)
def test_gpu_blocks_run_on_the_embed_queue(block_type):
    assert step_queue_for_block(_block(block_type)) == "embed"


def test_semantic_chunk_split_runs_on_the_embed_queue():
    assert step_queue_for_block(_block("chunk_split", {"strategy": "semantic"})) == "embed"


@pytest.mark.parametrize(
    "block_type", ["input", "text_extract", "text_clean", "chunk_split", "validate", "merge"]
)
def test_cpu_blocks_stay_on_the_normal_queue(block_type):
    assert step_queue_for_block(_block(block_type)) == "normal"


@pytest.mark.parametrize(
    "module, task_name",
    [
        ("app.pipeline.tasks.process", "continue_processing"),
        ("app.pipeline.tasks.summary", "generate_summary"),
        ("app.pipeline.tasks.metadata", "extract_metadata"),
        ("app.pipeline.tasks.reembed", "reembed_collection"),
    ],
)
def test_legacy_gpu_batch_tasks_default_to_the_embed_queue(module, task_name):
    import importlib

    task = getattr(importlib.import_module(module), task_name)
    assert task.queue == "embed"
