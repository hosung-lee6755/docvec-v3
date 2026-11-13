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


def test_text_extract_runs_on_the_single_process_extract_queue():
    # Docling 레이아웃·표 모델과 EasyOCR이 GPU를 쓴다. 메인 worker(4개 프로세스)에서 돌면
    # 프로세스마다 모델을 올려 GPU와 WSL 메모리를 바닥낸다(2026-11-13 Docker 정지)
    assert step_queue_for_block(_block("text_extract")) == "extract"


@pytest.mark.parametrize(
    "block_type", ["input", "text_clean", "chunk_split", "validate", "merge"]
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


@pytest.mark.parametrize(
    "module, task_name, queue",
    [
        # 답변 생성과 골든 평가는 로컬 LLM·임베딩·재순위 모델을 쓴다. worker-embed 한 프로세스가
        # llm 큐도 받아 모델 한 벌을 함께 쓴다
        ("app.pipeline.tasks.chat", "generate_answer", "llm"),
        ("app.pipeline.tasks.golden_eval", "run_golden_eval", "llm"),
        # 청크 직접 수정은 그 청크만 다시 임베딩한다
        ("app.pipeline.tasks.chunks", "update_chunk_text", "embed"),
    ],
)
def test_model_using_tasks_avoid_the_multi_process_worker(module, task_name, queue):
    import importlib

    task = getattr(importlib.import_module(module), task_name)
    assert task.queue == queue


def test_new_queues_are_declared():
    from app.pipeline.celery_app import celery_app

    names = {q.name for q in celery_app.conf.task_queues}
    assert {"llm", "extract", "embed"} <= names
