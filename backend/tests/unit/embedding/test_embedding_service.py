import math
from unittest.mock import MagicMock, patch

import pytest

from app.services import embedding
from app.services.embedding import (
    EMBEDDING_MODEL_REGISTRY,
    MockEmbeddingProvider,
    _build_provider,
    get_embedding_provider,
)


@pytest.fixture(autouse=True)
def _clear_provider_cache():
    embedding._provider_cache.clear()
    yield
    embedding._provider_cache.clear()


class TestMockEmbeddingProvider:
    def test_dimension_is_1024(self):
        assert MockEmbeddingProvider().dimension == 1024

    def test_embed_returns_one_vector_per_text(self):
        vectors = MockEmbeddingProvider().embed(["hello", "world"])
        assert len(vectors) == 2
        assert all(len(v) == 1024 for v in vectors)

    def test_embed_is_deterministic_for_same_text(self):
        provider = MockEmbeddingProvider()
        assert provider.embed(["repeatable text"]) == provider.embed(["repeatable text"])

    def test_embed_differs_for_different_text(self):
        provider = MockEmbeddingProvider()
        v1, v2 = provider.embed(["text a", "text b"])
        assert v1 != v2

    def test_embed_vectors_are_unit_normalized(self):
        vectors = MockEmbeddingProvider().embed(["some arbitrary sentence"])
        magnitude = math.sqrt(sum(x * x for x in vectors[0]))
        assert magnitude == pytest.approx(1.0, abs=1e-6)


class TestEmbeddingModelRegistry:
    def test_mock_entry_has_no_repo_id(self):
        assert EMBEDDING_MODEL_REGISTRY["mock"]["repo_id"] is None

    def test_all_non_mock_entries_have_repo_id(self):
        for key, spec in EMBEDDING_MODEL_REGISTRY.items():
            if key != "mock":
                assert spec["repo_id"], f"{key} is missing repo_id"

    def test_all_entries_have_positive_dimension(self):
        for spec in EMBEDDING_MODEL_REGISTRY.values():
            assert spec["dimension"] > 0


class TestBuildProvider:
    def test_unsupported_backend_raises_runtime_error(self):
        spec = {"repo_id": None, "dimension": 8, "backend": "unknown", "label": "x"}
        with pytest.raises(RuntimeError, match="Unsupported embedding backend"):
            _build_provider("bad-model", spec)

    def test_openai_backend_without_api_key_raises_runtime_error(self):
        spec = EMBEDDING_MODEL_REGISTRY["openai"]
        with patch.object(embedding.settings, "openai_api_key", ""):
            with pytest.raises(RuntimeError, match="openai_api_key is not configured"):
                _build_provider("openai", spec)

    def test_dimension_mismatch_raises_runtime_error(self):
        spec = {
            "repo_id": "some/repo",
            "dimension": 999,
            "backend": "sentence_transformers",
            "label": "x",
        }
        wrong_dim_provider = MagicMock()
        wrong_dim_provider.embed.return_value = [[0.0] * 8]

        with patch.object(
            embedding,
            "SentenceTransformerEmbeddingProvider",
            return_value=wrong_dim_provider,
        ):
            with pytest.raises(RuntimeError, match="produced dimension 8"):
                _build_provider("mismatched-model", spec)

    def test_mock_backend_returns_mock_provider(self):
        provider = _build_provider("mock", EMBEDDING_MODEL_REGISTRY["mock"])
        assert isinstance(provider, MockEmbeddingProvider)


class TestGetEmbeddingProvider:
    def test_unknown_model_key_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown embedding model"):
            get_embedding_provider("does-not-exist")

    def test_returns_mock_provider_for_mock_key(self):
        assert isinstance(get_embedding_provider("mock"), MockEmbeddingProvider)

    def test_caches_provider_instance_across_calls(self):
        first = get_embedding_provider("mock")
        second = get_embedding_provider("mock")
        assert first is second

    def test_builds_only_once_when_cached(self):
        with patch.object(
            embedding, "_build_provider", wraps=embedding._build_provider
        ) as build_spy:
            get_embedding_provider("mock")
            get_embedding_provider("mock")
            assert build_spy.call_count == 1

    def test_defaults_to_settings_default_embedding_model(self):
        with patch.object(embedding.settings, "default_embedding_model", "mock"):
            assert isinstance(get_embedding_provider(None), MockEmbeddingProvider)
