"""BGE-M3 임베딩은 배치 크기를 명시해 GPU 활성화 메모리를 제한한다.

FlagEmbedding.encode의 기본값은 batch_size=256, max_length=8192 라서 청크 1,000여 개짜리
문서를 한 번에 넘기면 fp32 활성화가 12GB GPU의 남은 VRAM을 넘긴다. 같은 프로세스에 로컬 LLM
(Qwen2.5-3B, fp16 약 6GB)이 상주하면 VRAM이 넘쳐 같은 작업이 8분 넘게 100% 사용률로 멈춰 있었다
(UIUX가이드라인 PDF, 청크 1,062개).
"""
import sys
from types import ModuleType

import numpy as np

from app.services.embedding import BgeM3EmbeddingProvider


class _FakeBgeM3:
    def __init__(self, repo_id: str, use_fp16: bool) -> None:
        self.encode_kwargs: dict = {}

    def encode(self, texts, **kwargs):
        self.encode_kwargs = kwargs
        return {"dense_vecs": np.zeros((len(texts), 1024), dtype="float32")}


def _provider_with_fake_model(monkeypatch) -> tuple[BgeM3EmbeddingProvider, _FakeBgeM3]:
    fake_module = ModuleType("FlagEmbedding")
    fake_module.BGEM3FlagModel = _FakeBgeM3
    monkeypatch.setitem(sys.modules, "FlagEmbedding", fake_module)
    provider = BgeM3EmbeddingProvider("BAAI/bge-m3")
    return provider, provider._model


def test_embed_limits_the_gpu_batch_size(monkeypatch):
    provider, model = _provider_with_fake_model(monkeypatch)

    vectors = provider.embed(["가", "나", "다"])

    assert len(vectors) == 3
    assert model.encode_kwargs["batch_size"] <= 32


def test_embed_still_returns_dense_vectors_only(monkeypatch):
    provider, model = _provider_with_fake_model(monkeypatch)

    provider.embed(["가"])

    assert model.encode_kwargs["return_dense"] is True
    assert model.encode_kwargs["return_sparse"] is False
    assert model.encode_kwargs["return_colbert_vecs"] is False
