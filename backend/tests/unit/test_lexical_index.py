"""키워드 색인(전체 점검 1-1): sparse 벡터 생성과 Qdrant 보조 컬렉션 연동."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from qdrant_client.models import Filter, HasIdCondition

from app.core.config import settings
from app.services import lexical_index as li
from app.services import qdrant_service as qs

CHUNKS = settings.qdrant_collection_name
LEX = f"{CHUNKS}_lex"


@pytest.fixture
def words():
    """형태소 분석기 대신 공백으로 나눈다."""
    with patch.object(li, "_tokenize", side_effect=lambda texts: [t.split() for t in texts]):
        yield


@pytest.fixture
def qdrant(words):
    with patch.object(qs, "QdrantClient"):
        yield qs.QdrantService()


def test_document_vector_weights_repeated_terms_higher_and_is_sorted():
    indices, values = li.document_vector(["KS-100", "규격", "KS-100"])

    weights = dict(zip(indices, values))
    assert indices == sorted(indices)
    assert weights[li.term_index("KS-100")] > weights[li.term_index("규격")]


def test_document_vector_penalises_long_chunks():
    short = li.document_vector(["품번"])[1][0]
    long = li.document_vector(["품번"] + [f"w{i}" for i in range(400)])
    assert short > dict(zip(*long))[li.term_index("품번")]


def test_term_index_ignores_case_and_empty_inputs_give_empty_vectors(words):
    assert li.term_index("ABC") == li.term_index("abc")
    assert li.document_vector([]) == ([], [])
    assert li.query_vector_for("   ") == ([], [])


def test_query_vector_counts_each_term_once_and_caps_length(words):
    indices, values = li.query_vector_for("a a b")
    assert len(indices) == 2 and values == [1.0, 1.0]
    assert len(li.query_vector([f"t{i}" for i in range(200)])[0]) == li.MAX_QUERY_TERMS


def test_hybrid_query_vector_only_for_hybrid_and_swallows_tokenizer_failure(words):
    assert li.hybrid_query_vector("a", "vector") is None
    assert li.hybrid_query_vector("a", "hybrid") == ([li.term_index("a")], [1.0])
    with patch.object(li, "_tokenize", side_effect=RuntimeError("kiwi")):
        assert li.hybrid_query_vector("a", "hybrid") is None


def _point(pid, text, **payload):
    return {"id": pid, "vector": [0.1], "payload": {"text": text, "collection_id": "c1", "document_id": "d1", **payload}}


def test_upsert_mirrors_chunk_points_into_lexical_collection(qdrant):
    qdrant._client.collection_exists.return_value = False

    qdrant.upsert_points(CHUNKS, [_point("p1", "본문", index_text="머리말 본문"), _point("p2", "")])

    created = qdrant._client.create_collection.call_args.kwargs
    assert created["collection_name"] == LEX and "text" in created["sparse_vectors_config"]
    lex_upsert = qdrant._client.upsert.call_args_list[-1].kwargs
    assert lex_upsert["collection_name"] == LEX
    (row,) = lex_upsert["points"]
    assert row.id == "p1" and row.payload == {"collection_id": "c1", "document_id": "d1"}
    # index_text(문맥을 붙인 본문)가 있으면 그것으로 색인한다
    assert set(row.vector["text"].indices) == {li.term_index("머리말"), li.term_index("본문")}
    # 낱말이 없는 점은 색인에서 지운다
    qdrant._client.delete.assert_called_once_with(collection_name=LEX, points_selector=["p2"])


def test_upsert_points_sends_large_documents_in_batches(qdrant, monkeypatch):
    # 검색용 청크 5,584개를 한 요청에 담으면 128MB가 되어 Qdrant 한도(32MB)를 넘었다(2026-11-17, 511쪽 PDF)
    monkeypatch.setattr(qs, "_UPSERT_BATCH_SIZE", 2)
    points = [_point(f"p{i}", f"본문{i}") for i in range(5)]

    qdrant.upsert_points("summaries", points)

    sent = [c.kwargs["points"] for c in qdrant._client.upsert.call_args_list]
    assert [len(batch) for batch in sent] == [2, 2, 1]
    assert [p.id for batch in sent for p in batch] == [f"p{i}" for i in range(5)]


def test_lexical_mirror_is_also_sent_in_batches(qdrant, monkeypatch):
    monkeypatch.setattr(qs, "_UPSERT_BATCH_SIZE", 2)
    qdrant._client.collection_exists.return_value = True

    qdrant.upsert_points(CHUNKS, [_point(f"p{i}", f"본문{i}") for i in range(5)])

    by_target = {}
    for c in qdrant._client.upsert.call_args_list:
        by_target.setdefault(c.kwargs["collection_name"], []).append(len(c.kwargs["points"]))
    assert by_target == {CHUNKS: [2, 2, 1], LEX: [2, 2, 1]}


def test_other_collections_are_not_mirrored(qdrant):
    qdrant.upsert_points("summaries", [_point("p1", "본문")])
    qdrant.delete_points("summaries", ["p1"])

    assert qdrant._client.upsert.call_count == 1
    assert qdrant._client.delete.call_count == 1
    qdrant._client.create_collection.assert_not_called()


def test_lexical_failure_does_not_fail_chunk_upsert_or_delete(qdrant):
    def upsert(collection_name, points):
        if collection_name == LEX:
            raise RuntimeError("down")

    qdrant._client.upsert.side_effect = upsert
    qdrant.upsert_points(CHUNKS, [_point("p1", "본문")])

    qdrant._client.collection_exists.side_effect = RuntimeError("down")
    qdrant.delete_by_document(CHUNKS, "d1")
    assert qdrant._client.delete.call_args.kwargs["collection_name"] == CHUNKS


def test_delete_is_mirrored(qdrant):
    qdrant._client.collection_exists.return_value = True
    qdrant.delete_points(CHUNKS, ["p1"])
    assert [c.kwargs["collection_name"] for c in qdrant._client.delete.call_args_list] == [CHUNKS, LEX]


def _hit(pid, score=0.5):
    return SimpleNamespace(id=pid, score=score, payload={"document_id": "d1"}, vector=None)


def test_search_adds_lexical_only_candidates_through_the_access_filter(qdrant):
    access = Filter(must=[])
    qdrant._client.collection_exists.return_value = True
    qdrant._client.query_points.side_effect = [
        SimpleNamespace(points=[_hit("a", 0.9)]),            # 벡터 후보
        SimpleNamespace(points=[_hit("a"), _hit("b")]),      # 키워드 후보
        SimpleNamespace(points=[_hit("b", 0.3)]),            # 청크 컬렉션 재조회
    ]

    hits = qdrant.search(CHUNKS, [0.1], limit=5, query_filter=access, lexical=([1], [1.0]), lexical_scope=["c1"])

    assert [(h["id"], h.get("lexical_only", False)) for h in hits] == [("a", False), ("b", True)]
    lex_call, requery = (c.kwargs for c in qdrant._client.query_points.call_args_list[1:])
    assert lex_call["collection_name"] == LEX and lex_call["using"] == "text"
    assert lex_call["query_filter"].must[0].match.any == ["c1"]
    # 재조회는 권한 필터를 그대로 두고 새 id로만 좁힌다
    assert requery["collection_name"] == CHUNKS
    assert requery["query_filter"].must[0] is access
    assert isinstance(requery["query_filter"].must[1], HasIdCondition)
    assert requery["query_filter"].must[1].has_id == ["b"]


def test_search_falls_back_to_vector_hits_when_lexical_lookup_fails(qdrant):
    qdrant._client.collection_exists.return_value = True
    qdrant._client.query_points.side_effect = [SimpleNamespace(points=[_hit("a")]), RuntimeError("down")]

    hits = qdrant.search(CHUNKS, [0.1], limit=5, query_filter=Filter(must=[]), lexical=([1], [1.0]))

    assert [h["id"] for h in hits] == ["a"]


def test_search_without_lexical_index_or_terms_queries_once(qdrant):
    qdrant._client.collection_exists.return_value = False
    qdrant._client.query_points.return_value = SimpleNamespace(points=[_hit("a")])

    qdrant.search(CHUNKS, [0.1], limit=5, query_filter=Filter(must=[]), lexical=([], []))
    qdrant.search(CHUNKS, [0.1], limit=5, query_filter=Filter(must=[]), lexical=([1], [1.0]))

    assert qdrant._client.query_points.call_count == 2


def test_rebuild_scrolls_every_page(qdrant):
    page = lambda ids: [SimpleNamespace(id=i, payload={"text": "본문", "collection_id": "c1", "document_id": "d1"}) for i in ids]
    qdrant._client.scroll.side_effect = [(page(["a", "b"]), "next"), (page(["c"]), None)]

    assert qdrant.rebuild_lexical(CHUNKS, batch_size=2) == {"scanned": 3, "indexed": 3}
