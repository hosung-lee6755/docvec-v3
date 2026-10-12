"""Coverage for small service/core modules: summary_index, chunk_stats,
reranker, document_service, crypto and rate_limit's IP-based limiter."""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.core import crypto, rate_limit
from app.core.config import settings
from app.services import chunk_stats, document_service, reranker, summary_index

# ----------------------------------------------------------- summary_index


def _index_env(dimension=4):
    provider = MagicMock()
    provider.dimension = dimension
    provider.embed.return_value = [[0.1] * dimension]
    qdrant = MagicMock()
    return provider, qdrant


def test_index_document_summary_upserts_point_keyed_by_document_id():
    provider, qdrant = _index_env()
    with patch.object(summary_index, "get_embedding_provider", return_value=provider), \
         patch.object(summary_index, "qdrant_service", qdrant):
        summary_index.index_document_summary("doc-1", "요약문", embedding_model="m")

    qdrant.init_collection.assert_called_once_with(summary_index.SUMMARY_COLLECTION_NAME, 4)
    name, points = qdrant.upsert_points.call_args.args
    assert name == summary_index.SUMMARY_COLLECTION_NAME
    assert points == [{
        "id": "doc-1", "vector": [0.1] * 4,
        "payload": {"document_id": "doc-1", "summary": "요약문"},
    }]


@pytest.mark.parametrize("blank", ["", "   \n", None])
def test_index_document_summary_ignores_blank_summary(blank):
    provider, qdrant = _index_env()
    with patch.object(summary_index, "get_embedding_provider", return_value=provider), \
         patch.object(summary_index, "qdrant_service", qdrant):
        summary_index.index_document_summary("doc-1", blank)

    provider.embed.assert_not_called()
    qdrant.upsert_points.assert_not_called()


def test_delete_document_summary_removes_point_by_document_id():
    qdrant = MagicMock()
    with patch.object(summary_index, "qdrant_service", qdrant):
        summary_index.delete_document_summary("doc-9")

    qdrant.delete_points.assert_called_once_with(summary_index.SUMMARY_COLLECTION_NAME, ["doc-9"])


def test_search_document_summaries_embeds_query_and_limits_results():
    provider, qdrant = _index_env()
    qdrant.search.return_value = [{"id": "d1"}]
    with patch.object(summary_index, "get_embedding_provider", return_value=provider), \
         patch.object(summary_index, "qdrant_service", qdrant):
        out = summary_index.search_document_summaries("질의", limit=3)

    provider.embed.assert_called_once_with(["질의"])
    qdrant.search.assert_called_once_with(
        summary_index.SUMMARY_COLLECTION_NAME, [0.1] * 4, limit=3
    )
    assert out == [{"id": "d1"}]


# ------------------------------------------------------------- chunk_stats


@pytest.fixture
def stats_client():
    client = MagicMock()
    with patch.object(chunk_stats, "_get_client", return_value=client):
        yield client


def test_record_hits_increments_each_point_in_one_pipeline(stats_client):
    chunk_stats.record_hits(["a", "b"])

    pipe = stats_client.pipeline.return_value
    assert [c.args[0] for c in pipe.incr.call_args_list] == ["chunk_hits:a", "chunk_hits:b"]
    pipe.execute.assert_called_once()


def test_record_hits_noop_for_empty_list(stats_client):
    chunk_stats.record_hits([])

    stats_client.pipeline.assert_not_called()


def test_record_hits_swallows_redis_errors(stats_client):
    stats_client.pipeline.side_effect = ConnectionError("down")

    chunk_stats.record_hits(["a"])  # must not raise


def test_get_hit_counts_converts_values_and_defaults_missing_to_zero(stats_client):
    stats_client.mget.return_value = [b"3", None]

    assert chunk_stats.get_hit_counts(["a", "b"]) == {"a": 3, "b": 0}
    stats_client.mget.assert_called_once_with(["chunk_hits:a", "chunk_hits:b"])


def test_get_hit_counts_empty_input_and_error_fallback(stats_client):
    assert chunk_stats.get_hit_counts([]) == {}

    stats_client.mget.side_effect = ConnectionError("down")
    assert chunk_stats.get_hit_counts(["a", "b"]) == {"a": 0, "b": 0}


def test_chunk_stats_client_is_created_once_and_cached():
    with patch.object(chunk_stats, "_client", None), \
         patch("redis.from_url", return_value="CLIENT") as from_url:
        first = chunk_stats._get_client()
        second = chunk_stats._get_client()

    assert first == second == "CLIENT"
    from_url.assert_called_once_with(settings.redis_url)


# ---------------------------------------------------------------- reranker


@pytest.fixture
def clean_reranker():
    with patch.object(reranker, "_reranker", None), patch.object(reranker, "_load_failed", False):
        yield


def _fake_flag_module(instance=None, error=None):
    module = MagicMock()
    if error:
        module.FlagReranker.side_effect = error
    else:
        module.FlagReranker.return_value = instance
    return {"FlagEmbedding": module}, module


def test_reranker_loads_once_without_fp16(clean_reranker):
    modules, module = _fake_flag_module(instance="MODEL")
    with patch.dict("sys.modules", modules):
        assert reranker._get_reranker() == "MODEL"
        assert reranker._get_reranker() == "MODEL"

    module.FlagReranker.assert_called_once_with(reranker._MODEL_NAME, use_fp16=False)


def test_reranker_load_failure_is_permanent_and_not_retried(clean_reranker):
    modules, module = _fake_flag_module(error=RuntimeError("oom"))
    with patch.dict("sys.modules", modules):
        assert reranker._get_reranker() is None
        assert reranker._get_reranker() is None

    module.FlagReranker.assert_called_once()
    assert reranker._load_failed is True


def _model(scores):
    model = MagicMock()
    model.compute_score.return_value = scores
    return model


def test_cross_encoder_rerank_orders_by_score_and_trims(clean_reranker):
    candidates = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
    with patch.object(reranker, "_get_reranker", return_value=_model([0.1, 0.9, 0.5])):
        out = reranker.cross_encoder_rerank("q", candidates, top_k=2)

    assert [c["text"] for c in out] == ["b", "c"]
    assert out[0]["rerank_score"] == pytest.approx(0.9)


def test_cross_encoder_rerank_wraps_scalar_score_for_single_candidate():
    with patch.object(reranker, "_get_reranker", return_value=_model(0.7)):
        out = reranker.cross_encoder_rerank("q", [{"text": "only"}])

    assert out[0]["rerank_score"] == pytest.approx(0.7)


def test_cross_encoder_rerank_scores_requested_text_field():
    model = _model([0.2])
    with patch.object(reranker, "_get_reranker", return_value=model):
        reranker.cross_encoder_rerank("q", [{"body": "내용"}], text_field="body")

    model.compute_score.assert_called_once_with([["q", "내용"]], normalize=True)


def test_cross_encoder_rerank_passthrough_when_reranker_unavailable():
    candidates = [{"text": "a"}, {"text": "b"}]
    with patch.object(reranker, "_get_reranker", return_value=None):
        assert reranker.cross_encoder_rerank("q", candidates, top_k=1) == [{"text": "a"}]
        assert reranker.cross_encoder_rerank("q", candidates) == candidates


def test_cross_encoder_rerank_empty_candidates_skips_model():
    model = _model([])
    with patch.object(reranker, "_get_reranker", return_value=model):
        assert reranker.cross_encoder_rerank("q", []) == []

    model.compute_score.assert_not_called()


def test_cross_encoder_rerank_falls_back_to_input_order_on_scoring_error():
    model = MagicMock()
    model.compute_score.side_effect = RuntimeError("cuda error")
    candidates = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
    with patch.object(reranker, "_get_reranker", return_value=model):
        out = reranker.cross_encoder_rerank("q", candidates, top_k=2)

    assert [c["text"] for c in out] == ["a", "b"]


# --------------------------------------------------------- document_service


def test_merge_chunks_trims_overlap_between_adjacent_chunks():
    merged = document_service._merge_chunks(["hello world", "world and more"])

    assert merged == "hello world\n\n and more"


def test_merge_chunks_without_overlap_joins_with_blank_line():
    assert document_service._merge_chunks(["abc", "xyz"]) == "abc\n\nxyz"


def test_merge_chunks_empty_and_single():
    assert document_service._merge_chunks([]) == ""
    assert document_service._merge_chunks(["only"]) == "only"


def test_get_document_content_sorts_by_chunk_index_and_merges():
    doc_id = UUID("11111111-1111-1111-1111-111111111111")
    qdrant = MagicMock()
    qdrant.scroll_by_document.return_value = [
        {"id": "2", "payload": {"chunk_index": 1, "text": "둘째"}},
        {"id": "1", "payload": {"chunk_index": 0, "text": "첫째"}},
    ]
    with patch.object(document_service, "_get_qdrant", return_value=qdrant):
        out = document_service.get_document_content(doc_id)

    qdrant.scroll_by_document.assert_called_once_with(str(doc_id))
    assert [c["text"] for c in out["chunks"]] == ["첫째", "둘째"]
    assert out["full_text"] == "첫째\n\n둘째"
    assert out["chunk_count"] == 2


def test_get_document_content_empty_document():
    qdrant = MagicMock()
    qdrant.scroll_by_document.return_value = []
    with patch.object(document_service, "_get_qdrant", return_value=qdrant):
        out = document_service.get_document_content(UUID(int=1))

    assert out == {"document_id": str(UUID(int=1)), "chunks": [], "full_text": ""}


def test_get_document_content_defaults_missing_chunk_index_and_text():
    qdrant = MagicMock()
    qdrant.scroll_by_document.return_value = [{"id": "1", "payload": {}}]
    with patch.object(document_service, "_get_qdrant", return_value=qdrant):
        out = document_service.get_document_content(UUID(int=2))

    assert out["chunks"] == [{"chunk_index": 0, "text": ""}]


def test_get_download_url_returns_presigned_url_for_originals_bucket():
    storage = MagicMock()
    storage.get_presigned_url.return_value = "https://signed"
    with patch.object(document_service, "_get_storage", return_value=storage):
        url = document_service.get_download_url("k/file.pdf", expires_seconds=60)

    assert url == "https://signed"
    storage.get_presigned_url.assert_called_once_with(
        settings.minio_bucket_originals, "k/file.pdf", expires_seconds=60
    )


def test_get_download_url_default_lifetime_is_at_most_one_hour():
    # 서명 URL 은 문서 접근 권한이 회수·삭제된 뒤에도 만료 전까지 유효하다. 요청마다 새로 발급하므로
    # 하루(86400초)처럼 길 필요가 없다.
    storage = MagicMock()
    storage.get_presigned_url.return_value = "https://signed"
    with patch.object(document_service, "_get_storage", return_value=storage):
        document_service.get_download_url("k/file.pdf")

    assert storage.get_presigned_url.call_args.kwargs["expires_seconds"] <= 3600


def test_get_download_url_raises_503_when_no_url_generated():
    storage = MagicMock()
    storage.get_presigned_url.return_value = ""
    with patch.object(document_service, "_get_storage", return_value=storage):
        with pytest.raises(HTTPException) as caught:
            document_service.get_download_url("k")

    assert caught.value.status_code == 503


def test_document_service_factories_build_real_service_objects():
    with patch.object(document_service, "QdrantService", return_value="Q"), \
         patch.object(document_service, "StorageService", return_value="S"):
        assert document_service._get_qdrant() == "Q"
        assert document_service._get_storage() == "S"


# ------------------------------------------------------------------ crypto


def test_secret_roundtrip_returns_original_and_ciphertext_differs():
    token = crypto.encrypt_secret("sk-live-한글")

    assert token != "sk-live-한글"
    assert crypto.decrypt_secret(token) == "sk-live-한글"


def test_decrypt_fails_when_encryption_key_changes():
    from cryptography.fernet import InvalidToken

    with patch.object(settings, "encryption_key", "key-one-for-test"):
        token = crypto.encrypt_secret("secret")
    with patch.object(settings, "encryption_key", "key-two-for-test"):
        with pytest.raises(InvalidToken):
            crypto.decrypt_secret(token)


def test_decrypt_rejects_garbage_ciphertext():
    from cryptography.fernet import InvalidToken

    with pytest.raises(InvalidToken):
        crypto.decrypt_secret("not-a-fernet-token")


# -------------------------------------------------------------- rate_limit


class _Redis:
    def __init__(self):
        self.counts: dict[str, int] = {}

    def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key, seconds):
        pass


def _request(host="1.2.3.4"):
    return SimpleNamespace(client=SimpleNamespace(host=host) if host else None)


def test_get_client_ip_uses_client_host_or_unknown():
    assert rate_limit._get_client_ip(_request("9.9.9.9")) == "9.9.9.9"
    assert rate_limit._get_client_ip(_request(None)) == "unknown"


def test_rate_limit_client_is_created_once_and_cached():
    with patch.object(rate_limit, "_client", None), \
         patch("redis.from_url", return_value="R") as from_url:
        assert rate_limit._get_client() == "R"
        assert rate_limit._get_client() == "R"

    from_url.assert_called_once_with(settings.redis_url)


def test_enforce_rate_limit_counts_by_ip_and_by_email_separately(monkeypatch):
    fake = _Redis()
    monkeypatch.setattr(rate_limit, "_get_client", lambda: fake)

    rate_limit.enforce_rate_limit(_request(), "login", 2, 60, email="a@x.com")
    rate_limit.enforce_rate_limit(_request("5.5.5.5"), "login", 2, 60, email="a@x.com")

    assert fake.counts["ratelimit:login:email:a@x.com"] == 2
    assert fake.counts["ratelimit:login:1.2.3.4"] == 1
    assert fake.counts["ratelimit:login:5.5.5.5"] == 1


def test_enforce_rate_limit_blocks_account_across_ips(monkeypatch):
    fake = _Redis()
    monkeypatch.setattr(rate_limit, "_get_client", lambda: fake)
    rate_limit.enforce_rate_limit(_request("1.1.1.1"), "login", 1, 60, email="a@x.com")

    with pytest.raises(HTTPException) as caught:
        rate_limit.enforce_rate_limit(_request("2.2.2.2"), "login", 1, 60, email="a@x.com")

    assert caught.value.status_code == 429


def test_enforce_rate_limit_without_email_only_tracks_ip(monkeypatch):
    fake = _Redis()
    monkeypatch.setattr(rate_limit, "_get_client", lambda: fake)

    rate_limit.enforce_rate_limit(_request(), "refresh", 5, 60)

    assert list(fake.counts) == ["ratelimit:refresh:1.2.3.4"]


def test_redis_outage_is_logged_once_per_outage_then_resets_on_recovery(monkeypatch, caplog):
    monkeypatch.setattr(rate_limit, "_redis_outage_logged", False)

    def broken():
        raise ConnectionError("down")

    monkeypatch.setattr(rate_limit, "_get_client", broken)
    with caplog.at_level(logging.ERROR, logger=rate_limit.logger.name):
        rate_limit.enforce_rate_limit(_request(), "login", 1, 60)
        rate_limit.enforce_rate_limit(_request(), "login", 1, 60)
    assert len([r for r in caplog.records if "failing open" in r.getMessage()]) == 1

    monkeypatch.setattr(rate_limit, "_get_client", lambda: _Redis())
    rate_limit.enforce_rate_limit(_request(), "login", 1, 60)
    assert rate_limit._redis_outage_logged is False
