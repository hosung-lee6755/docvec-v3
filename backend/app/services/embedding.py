import hashlib
import math
import struct
import threading
from abc import ABC, abstractmethod
from typing import TypedDict

from app.core.config import settings


class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def dimension(self) -> int: ...

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class MockEmbeddingProvider(EmbeddingProvider):
    _DIM = 1024

    @property
    def dimension(self) -> int:
        return self._DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._text_to_vector(t) for t in texts]

    def _text_to_vector(self, text: str) -> list[float]:
        raw = bytearray()
        seed = text.encode("utf-8")
        while len(raw) < self._DIM * 4:
            seed = hashlib.sha256(seed).digest()
            raw.extend(seed)
        floats = [
            struct.unpack_from(">I", raw, i * 4)[0] / 0xFFFFFFFF - 0.5
            for i in range(self._DIM)
        ]
        mag = math.sqrt(sum(x * x for x in floats)) or 1.0
        return [x / mag for x in floats]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    _MODEL = "text-embedding-3-small"
    _DIM = 1536

    def __init__(self) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=settings.openai_api_key)

    @property
    def dimension(self) -> int:
        return self._DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(input=texts, model=self._MODEL)
        return [item.embedding for item in response.data]


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    def __init__(self, repo_id: str, dimension: int) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(repo_id)
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return vectors.tolist()


class BgeM3EmbeddingProvider(EmbeddingProvider):
    _DIM = 1024

    def __init__(self, repo_id: str) -> None:
        from FlagEmbedding import BGEM3FlagModel

        self._model = BGEM3FlagModel(repo_id, use_fp16=False)

    @property
    def dimension(self) -> int:
        return self._DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        output = self._model.encode(
            texts, return_dense=True, return_sparse=False, return_colbert_vecs=False
        )
        return [vec.tolist() for vec in output["dense_vecs"]]


class EmbeddingModelSpec(TypedDict):
    repo_id: str | None
    dimension: int
    backend: str
    label: str


# Curated, pre-installed embedding models. Adding a model requires downloading
# it into the shared model cache (see app/pipeline/download_models.py) before
# it can be selected safely — there is no user-supplied model upload path.
EMBEDDING_MODEL_REGISTRY: dict[str, EmbeddingModelSpec] = {
    "bge-m3": {
        "repo_id": "BAAI/bge-m3",
        "dimension": 1024,
        "backend": "flag_embedding",
        "label": "BGE-M3 (다국어, 1024차원)",
    },
    "multilingual-e5-large": {
        "repo_id": "intfloat/multilingual-e5-large",
        "dimension": 1024,
        "backend": "sentence_transformers",
        "label": "Multilingual E5 Large (다국어, 1024차원)",
    },
    "ko-sroberta-multitask": {
        "repo_id": "jhgan/ko-sroberta-multitask",
        "dimension": 768,
        "backend": "sentence_transformers",
        "label": "Ko-SRoBERTa Multitask (한국어 특화, 768차원)",
    },
    "kr-sbert": {
        "repo_id": "snunlp/KR-SBERT-V40K-klueNLI-augSTS",
        "dimension": 768,
        "backend": "sentence_transformers",
        "label": "KR-SBERT (한국어 특화, 768차원)",
    },
    "openai": {
        "repo_id": "text-embedding-3-small",
        "dimension": 1536,
        "backend": "openai",
        "label": "OpenAI text-embedding-3-small",
    },
    "mock": {
        "repo_id": None,
        "dimension": 1024,
        "backend": "mock",
        "label": "Mock (테스트용)",
    },
}

_provider_cache: dict[str, EmbeddingProvider] = {}
_provider_cache_lock = threading.Lock()


def _build_provider(key: str, spec: EmbeddingModelSpec) -> EmbeddingProvider:
    try:
        if spec["backend"] == "mock":
            provider: EmbeddingProvider = MockEmbeddingProvider()
        elif spec["backend"] == "openai":
            if not settings.openai_api_key:
                raise ValueError("openai_api_key is not configured")
            provider = OpenAIEmbeddingProvider()
        elif spec["backend"] == "flag_embedding":
            provider = BgeM3EmbeddingProvider(spec["repo_id"])
        elif spec["backend"] == "sentence_transformers":
            provider = SentenceTransformerEmbeddingProvider(spec["repo_id"], spec["dimension"])
        else:
            raise ValueError(f"Unsupported embedding backend: {spec['backend']}")
    except Exception as exc:
        raise RuntimeError(f"Failed to load embedding model '{key}' ({spec['repo_id']}): {exc}") from exc

    if spec["backend"] != "mock":
        actual_dim = len(provider.embed(["healthcheck"])[0])
        if actual_dim != spec["dimension"]:
            raise RuntimeError(
                f"Embedding model '{key}' produced dimension {actual_dim}, "
                f"expected {spec['dimension']} per EMBEDDING_MODEL_REGISTRY"
            )
    return provider


def get_embedding_provider(model_key: str | None = None) -> EmbeddingProvider:
    key = model_key or settings.default_embedding_model
    if key in _provider_cache:
        return _provider_cache[key]

    spec = EMBEDDING_MODEL_REGISTRY.get(key)
    if spec is None:
        raise ValueError(f"Unknown embedding model: {key}")

    with _provider_cache_lock:
        if key in _provider_cache:
            return _provider_cache[key]
        provider = _build_provider(key, spec)
        _provider_cache[key] = provider
        return provider
