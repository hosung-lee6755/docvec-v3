"""Coverage for app.services.qdrant_service.QdrantService and
app.services.storage.StorageService with the Qdrant/MinIO clients mocked."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from minio.error import S3Error
from qdrant_client.models import Filter, MatchAny, MatchValue

from app.core.config import settings
from app.services import qdrant_service as qs
from app.services import storage as st

# ------------------------------------------------------------------ qdrant


@pytest.fixture
def qdrant():
    with patch.object(qs, "QdrantClient") as client_cls:
        service = qs.QdrantService()
        service.client_cls = client_cls
        yield service


def _conditions(flt: Filter) -> dict:
    return {c.key: c.match for c in (flt.must or [])}


def test_client_is_built_from_settings(qdrant):
    qdrant.client_cls.assert_called_once_with(host=settings.qdrant_host, port=settings.qdrant_port)


def test_init_collection_creates_only_when_missing(qdrant):
    client = qdrant._client
    client.get_collections.return_value = SimpleNamespace(
        collections=[SimpleNamespace(name="exists")]
    )

    qdrant.init_collection("exists", 8)
    client.create_collection.assert_not_called()

    qdrant.init_collection("fresh", 8)
    kwargs = client.create_collection.call_args.kwargs
    assert kwargs["collection_name"] == "fresh"
    assert kwargs["vectors_config"].size == 8


def test_upsert_points_converts_dicts_and_defaults_payload(qdrant):
    qdrant.upsert_points("c", [
        {"id": "1", "vector": [0.1], "payload": {"a": 1}},
        {"id": "2", "vector": [0.2]},
    ])

    points = qdrant._client.upsert.call_args.kwargs["points"]
    assert [p.id for p in points] == ["1", "2"]
    assert points[0].payload == {"a": 1}
    assert points[1].payload == {}


def test_upsert_points_skips_call_for_empty_list(qdrant):
    qdrant.upsert_points("c", [])

    qdrant._client.upsert.assert_not_called()


def _search(qdrant, **kwargs):
    qdrant._client.query_points.return_value = SimpleNamespace(points=[
        SimpleNamespace(id=7, score=0.9, payload={"text": "t"}, vector=[1.0]),
        SimpleNamespace(id=8, score=0.1, payload=None, vector=None),
    ])
    out = qdrant.search("c", [0.1, 0.2], **kwargs)
    return out, qdrant._client.query_points.call_args.kwargs


def test_search_always_excludes_disabled_chunks_and_stringifies_ids(qdrant):
    out, call = _search(qdrant, limit=3)

    flt = call["query_filter"]
    assert flt.must is None
    assert flt.must_not[0].key == "disabled" and flt.must_not[0].match.value is True
    assert call["limit"] == 3 and call["with_vectors"] is False
    assert out == [
        {"id": "7", "score": 0.9, "payload": {"text": "t"}},
        {"id": "8", "score": 0.1, "payload": {}},
    ]


def test_search_single_collection_filter_wins_over_collection_ids(qdrant):
    _out, call = _search(qdrant, collection_id="c1", collection_ids=["a", "b"])

    match = _conditions(call["query_filter"])["collection_id"]
    assert isinstance(match, MatchValue) and match.value == "c1"


def test_search_restricts_to_accessible_collection_ids(qdrant):
    _out, call = _search(qdrant, collection_ids=["a", "b"])

    match = _conditions(call["query_filter"])["collection_id"]
    assert isinstance(match, MatchAny) and match.any == ["a", "b"]


def test_search_empty_accessible_list_still_scopes_to_nothing(qdrant):
    """collection_ids=[] must not degrade into an unscoped (all users) search."""
    _out, call = _search(qdrant, collection_ids=[])

    assert "collection_id" in _conditions(call["query_filter"])


def test_search_applies_extra_filters_and_returns_vectors_on_request(qdrant):
    out, call = _search(qdrant, filters={"document_id": "d1"}, with_vectors=True)

    assert _conditions(call["query_filter"])["document_id"].value == "d1"
    assert call["with_vectors"] is True
    assert out[0]["vector"] == [1.0]


def test_get_point_returns_none_when_missing_else_payload(qdrant):
    qdrant._client.retrieve.return_value = []
    assert qdrant.get_point("c", "p") is None

    qdrant._client.retrieve.return_value = [SimpleNamespace(id=5, payload=None)]
    assert qdrant.get_point("c", "p") == {"id": "5", "payload": {}}


def test_set_point_payload_targets_single_point(qdrant):
    qdrant.set_point_payload("c", "p1", {"disabled": True})

    qdrant._client.set_payload.assert_called_once_with(
        collection_name="c", payload={"disabled": True}, points=["p1"]
    )


def test_delete_points_skips_empty_and_deletes_ids(qdrant):
    qdrant.delete_points("c", [])
    qdrant._client.delete.assert_not_called()

    qdrant.delete_points("c", ["a"])
    qdrant._client.delete.assert_called_once_with(collection_name="c", points_selector=["a"])


def test_set_payload_by_document_uses_document_filter(qdrant):
    qdrant.set_payload_by_document("c", "d1", {"tags": ["x"]})

    kwargs = qdrant._client.set_payload.call_args.kwargs
    assert _conditions(kwargs["points"])["document_id"].value == "d1"
    assert kwargs["payload"] == {"tags": ["x"]}


def test_delete_by_document_uses_document_filter(qdrant):
    qdrant.delete_by_document("c", "d1")

    selector = qdrant._client.delete.call_args.kwargs["points_selector"]
    assert _conditions(selector)["document_id"].value == "d1"


def test_count_by_collection_excludes_disabled_and_is_exact(qdrant):
    qdrant._client.count.return_value = SimpleNamespace(count=42)

    assert qdrant.count_by_collection("c", "coll-1") == 42

    kwargs = qdrant._client.count.call_args.kwargs
    assert kwargs["exact"] is True
    assert _conditions(kwargs["count_filter"])["collection_id"].value == "coll-1"
    assert kwargs["count_filter"].must_not[0].key == "disabled"


def test_scroll_by_document_returns_id_payload_dicts_from_shared_collection(qdrant):
    qdrant._client.scroll.return_value = (
        [SimpleNamespace(id=1, payload={"x": 1}), SimpleNamespace(id=2, payload=None)], None,
    )

    out = qdrant.scroll_by_document("d1", limit=5)

    assert out == [{"id": "1", "payload": {"x": 1}}, {"id": "2", "payload": {}}]
    kwargs = qdrant._client.scroll.call_args.kwargs
    assert kwargs["collection_name"] == settings.qdrant_collection_name
    assert kwargs["limit"] == 5 and kwargs["with_vectors"] is False


# ----------------------------------------------------------------- storage


@pytest.fixture
def storage():
    with patch.object(st, "Minio", side_effect=[MagicMock(), MagicMock()]) as minio_cls:
        service = st.StorageService()
        service.minio_cls = minio_cls
        yield service


def test_storage_builds_internal_and_public_clients(storage):
    calls = storage.minio_cls.call_args_list

    assert calls[0].args[0] == settings.minio_endpoint
    assert calls[1].args[0] == settings.minio_public_endpoint
    # public client must not trigger a region lookup against an unreachable host
    assert calls[1].kwargs["region"] == "us-east-1"


def test_init_buckets_creates_only_missing(storage):
    storage._client.bucket_exists.side_effect = lambda b: b == settings.minio_bucket_originals

    storage.init_buckets()

    storage._client.make_bucket.assert_called_once_with(settings.minio_bucket_artifacts)


def test_upload_file_streams_bytes_and_returns_key(storage):
    key = storage.upload_file("b", "k", b"hello", "text/plain")

    assert key == "k"
    args = storage._client.put_object.call_args
    assert args.args[0:2] == ("b", "k")
    assert args.args[2].read() == b"hello"
    assert args.args[3] == 5
    assert args.kwargs["content_type"] == "text/plain"


def test_download_file_reads_and_releases_connection(storage):
    response = MagicMock()
    response.read.return_value = b"data"
    storage._client.get_object.return_value = response

    assert storage.download_file("b", "k") == b"data"

    response.close.assert_called_once()
    response.release_conn.assert_called_once()


def test_download_file_releases_connection_even_when_read_fails(storage):
    response = MagicMock()
    response.read.side_effect = OSError("reset")
    storage._client.get_object.return_value = response

    with pytest.raises(OSError):
        storage.download_file("b", "k")

    response.release_conn.assert_called_once()


def test_presigned_url_comes_from_public_client_with_expiry(storage):
    from datetime import timedelta

    storage._public_client.presigned_get_object.return_value = "https://pub/x"

    assert storage.get_presigned_url("b", "k", expires_seconds=90) == "https://pub/x"
    storage._public_client.presigned_get_object.assert_called_once_with(
        "b", "k", expires=timedelta(seconds=90)
    )
    storage._client.presigned_get_object.assert_not_called()


def test_presigned_url_is_origin_relative_when_relative_urls_enabled(storage, monkeypatch):
    """Caddy 가 서명 Host 로 되돌려 보내므로, URL 은 브라우저가 접속한 출처 기준(경로+쿼리)이어야 한다.
    공유기가 내부→공인 IP 접속을 지원하지 않아도 서버 PC 에서 원본이 열린다."""
    monkeypatch.setattr(settings, "minio_relative_urls", True)
    storage._public_client.presigned_get_object.return_value = (
        "https://49.168.97.107:4443/originals/doc/a%20b.pdf?X-Amz-Signature=abc&X-Amz-Expires=3600"
    )

    assert storage.get_presigned_url("originals", "doc/a b.pdf") == (
        "/originals/doc/a%20b.pdf?X-Amz-Signature=abc&X-Amz-Expires=3600"
    )


def test_presigned_url_stays_absolute_by_default(storage, monkeypatch):
    monkeypatch.setattr(settings, "minio_relative_urls", False)
    storage._public_client.presigned_get_object.return_value = "https://pub/x?sig=1"

    assert storage.get_presigned_url("b", "k") == "https://pub/x?sig=1"


def test_delete_file_removes_object(storage):
    storage.delete_file("b", "k")

    storage._client.remove_object.assert_called_once_with("b", "k")


def test_delete_file_swallows_s3_errors_but_logs_them(storage, caplog):
    storage._client.remove_object.side_effect = S3Error(
        "NoSuchKey", "gone", "r", "rid", "hid", MagicMock()
    )

    with caplog.at_level("WARNING", logger=st.logger.name):
        storage.delete_file("b", "k")  # must not raise

    assert any("객체 삭제 실패" in r.getMessage() for r in caplog.records)
