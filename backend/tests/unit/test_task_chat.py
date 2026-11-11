"""Coverage for app.pipeline.tasks.chat — RAG answer generation task and its
retrieval/verification helpers.

Real Postgres is used where access-scoping / persisted message state matters;
the LLM, embedding model, Qdrant, Redis and reranker are all faked."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.answer_trace import AnswerTrace
from app.db.models.chat_conversation import ChatConversation
from app.db.models.chat_message import ChatMessage
from app.db.models.collection import Collection
from app.db.models.collection_member import CollectionMember
from app.db.models.document import Document
from app.db.models.llm_usage_log import LLMUsageLog
from app.db.models.project import Project
from app.db.models.project_api_key import ProjectApiKey
from app.db.models.project_member import ProjectMember
from app.db.models.user import User
from app.db.models.user_api_key import UserApiKey
from app.pipeline.tasks import chat
from app.services.agentic.planner import DECOMPOSE_SYSTEM_PROMPT
from tests.conftest import TEST_DATABASE_URL

SYNC_URL = TEST_DATABASE_URL.replace("+asyncpg", "+psycopg2")


# ------------------------------------------------------------- pure helpers


def test_answer_cache_key_normalizes_case_and_whitespace():
    a = chat._answer_cache_key("  Hello World ", "c1", "p1", "m", "fp")
    b = chat._answer_cache_key("hello world", "c1", "p1", "m", "fp")

    assert a == b
    assert a.startswith("rag_answer:m:c1:p1:fp:")


def test_answer_cache_key_scopes_by_collection_project_model_and_access():
    base = chat._answer_cache_key("q", None, None, "m", "fp")

    assert "rag_answer:m:all:none:" in base
    assert chat._answer_cache_key("q", "c", None, "m", "fp") != base
    assert chat._answer_cache_key("q", None, "p", "m", "fp") != base
    assert chat._answer_cache_key("q", None, None, "other", "fp") != base
    # v3: 권한 조합이 다르면 같은 질문이라도 캐시를 공유하지 않는다(답변·인용 누출 방지)
    assert chat._answer_cache_key("q", None, None, "m", "other-fp") != base


def test_answer_cache_key_keeps_deep_answers_apart_from_standard_ones():
    standard = chat._answer_cache_key("q", None, None, "m", "fp")
    assert chat._answer_cache_key("q", None, None, "m", "fp", mode="standard") == standard
    assert standard.startswith("rag_answer:")
    deep = chat._answer_cache_key("q", None, None, "m", "fp", mode="deep")
    assert deep.startswith("rag_answer_deep:") and deep != standard


@pytest.mark.parametrize(
    "answer,expected",
    [("[1], [4]", True), ("  [1]  ", True), ("", False), ("설명입니다[1]", False),
     ("[1] 이 문서는", False)],
)
def test_is_degenerate_answer(answer, expected):
    assert chat._is_degenerate_answer(answer) is expected


@pytest.mark.parametrize(
    "verdict,expected",
    [("TABLE_QUERY", "table_query"), (" summary_lookup \n", "summary_lookup"),
     ("CHUNK_SEARCH", "chunk_search"), ("gibberish", "chunk_search")],
)
def test_classify_intent_maps_labels(verdict, expected):
    provider = MagicMock()
    provider.generate.return_value = verdict

    assert chat._classify_intent(provider, "q") == expected


def test_classify_intent_defaults_to_chunk_search_on_provider_error():
    provider = MagicMock()
    provider.generate.side_effect = RuntimeError("down")

    assert chat._classify_intent(provider, "q") == "chunk_search"


def test_is_answer_grounded_false_only_when_insufficient():
    provider = MagicMock()
    provider.generate.return_value = "insufficient"
    assert chat._is_answer_grounded(provider, "q", "ctx", "a") is False

    provider.generate.return_value = "SUFFICIENT"
    assert chat._is_answer_grounded(provider, "q", "ctx", "a") is True


def test_build_context_numbers_citations_and_shows_page_when_known():
    chunks = [
        {"filename": "a.pdf", "page_number": 3, "text": "alpha"},
        {"filename": "b.pdf", "page_number": None, "text": "beta"},
    ]

    assert chat._build_context(chunks) == "[1] a.pdf (3쪽): alpha\n\n[2] b.pdf: beta"


def test_build_context_placeholder_when_no_chunks():
    assert chat._build_context([]) == "(관련 발췌문 없음)"


# ------------------------------------------------------------- real DB fixtures


@pytest.fixture(scope="module")
def session_factory():
    engine = create_engine(SYNC_URL)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


def _user(db: Session, name: str) -> User:
    user = User(
        id=uuid4(), email=f"{uuid4()}@example.com", username=name,
        hashed_password="!", role="viewer", is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _collection(db, owner, *, project=None, restricted=False, name="c") -> Collection:
    coll = Collection(
        id=uuid4(), name=name, qdrant_collection_name=f"q-{uuid4()}", created_by=owner.id,
        project_id=project.id if project else None, restrict_to_members=restricted,
    )
    db.add(coll)
    db.flush()
    return coll


def _document(db, owner, coll, **fields) -> Document:
    doc = Document(
        id=uuid4(), filename="a.pdf", original_filename=fields.pop("original_filename", "a.pdf"),
        file_size=1, mime_type="application/pdf", file_hash="h" * 64,
        minio_key=f"{uuid4()}/a.pdf", status=fields.pop("status", "INDEXED"),
        created_by=owner.id, collection_id=coll.id, **fields,
    )
    db.add(doc)
    db.flush()
    return doc


@pytest.fixture
def world(session_factory):
    """alice owns project P (member: carol) and a private collection; bob owns
    collections shared with alice via project / membership / not at all."""
    db = session_factory()
    alice, bob, carol, stranger = (_user(db, n) for n in ("alice", "bob", "carol", "stranger"))
    project = Project(id=uuid4(), name="P", created_by=alice.id)
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=carol.id, role="viewer",
                         invited_by=alice.id))
    c_own = _collection(db, alice, name="own")
    c_open = _collection(db, bob, project=project, name="proj-open")
    c_restricted = _collection(db, bob, project=project, restricted=True, name="proj-restricted")
    c_member = _collection(db, bob, name="member-of")
    c_other = _collection(db, bob, name="other")
    db.add(CollectionMember(collection_id=c_member.id, user_id=alice.id, role="viewer",
                            invited_by=bob.id))
    db.commit()
    yield SimpleNamespace(
        db=db, alice=alice, bob=bob, carol=carol, stranger=stranger, project=project,
        c_own=c_own, c_open=c_open, c_restricted=c_restricted, c_member=c_member,
        c_other=c_other, factory=session_factory,
    )
    db.close()


def _ids(*collections):
    return {str(c.id) for c in collections}


# ------------------------------------------------------ access scoping


def test_accessible_collections_unions_owned_member_and_open_project(world):
    out = chat._accessible_collection_ids(world.db, str(world.alice.id))

    assert set(out) == _ids(world.c_own, world.c_member, world.c_open)
    assert str(world.c_restricted.id) not in out
    assert str(world.c_other.id) not in out


def test_accessible_collections_project_member_sees_only_open_project_collections(world):
    out = chat._accessible_collection_ids(world.db, str(world.carol.id))

    assert set(out) == _ids(world.c_open)


def test_accessible_collections_narrowed_to_project(world):
    out = chat._accessible_collection_ids(
        world.db, str(world.alice.id), project_id=str(world.project.id)
    )

    assert set(out) == _ids(world.c_open)


def test_accessible_collections_project_scope_denied_for_non_member(world):
    out = chat._accessible_collection_ids(
        world.db, str(world.stranger.id), project_id=str(world.project.id)
    )

    assert out == []


def test_accessible_documents_uses_explicit_collection_and_only_indexed(world):
    indexed = _document(world.db, world.alice, world.c_own)
    _document(world.db, world.alice, world.c_own, status="FAILED")
    world.db.commit()

    docs = chat._accessible_documents(
        world.db, str(world.alice.id), str(world.c_own.id)
    )

    assert [d.id for d in docs] == [indexed.id]


def test_accessible_documents_empty_when_user_has_no_collections(world):
    assert chat._accessible_documents(world.db, str(world.stranger.id), None) == []


# --------------------------------------------- table / summary retrieval


def test_retrieve_table_chunks_flattens_rows_and_ranks_by_bm25(world):
    _document(world.db, world.alice, world.c_own, original_filename="budget.xlsx", tables=[
        {"page_number": 2, "rows": [["항목", "금액"], ["예산", "100"]]},
        {"page_number": 3, "rows": []},
    ])
    _document(world.db, world.alice, world.c_own, original_filename="none.pdf", tables=None)
    world.db.commit()

    out = chat._retrieve_table_chunks(
        world.db, str(world.alice.id), "예산 금액", str(world.c_own.id)
    )

    assert len(out) == 1
    assert out[0]["filename"] == "budget.xlsx"
    assert out[0]["page_number"] == 2
    assert out[0]["text"] == "항목 | 금액\n예산 | 100"
    assert out[0]["collection_name"] == "own"


def test_retrieve_table_chunks_empty_when_no_tables(world):
    assert chat._retrieve_table_chunks(
        world.db, str(world.stranger.id), "q", None
    ) == []


def test_retrieve_summary_chunks_returns_all_when_few_documents(world):
    _document(world.db, world.alice, world.c_own, original_filename="s1.pdf",
              summary="요약 하나", summary_status="DONE")
    _document(world.db, world.alice, world.c_own, original_filename="s2.pdf",
              summary="요약 둘", summary_status="PENDING")
    _document(world.db, world.alice, world.c_own, original_filename="s3.pdf",
              summary=None, summary_status="DONE")
    world.db.commit()

    out = chat._retrieve_summary_chunks(
        world.db, str(world.alice.id), "요약", str(world.c_own.id)
    )

    assert [c["filename"] for c in out] == ["s1.pdf"]
    assert out[0]["page_number"] is None
    assert out[0]["collection_name"] == "own"


def test_retrieve_summary_chunks_ranks_and_caps_when_many_documents(world):
    for i in range(4):
        _document(world.db, world.alice, world.c_own, original_filename=f"d{i}.pdf",
                  summary=f"주제{i} 내용" + (" 매출" if i == 2 else ""), summary_status="DONE")
    world.db.commit()

    out = chat._retrieve_summary_chunks(
        world.db, str(world.alice.id), "매출", str(world.c_own.id), limit=2
    )

    assert len(out) == 2
    assert out[0]["filename"] == "d2.pdf"


def test_retrieve_summary_chunks_empty_when_nothing_summarised(world):
    assert chat._retrieve_summary_chunks(
        world.db, str(world.stranger.id), "q", None
    ) == []


# ------------------------------------------------------------ _retrieve_chunks


def _hit(point_id, text, coll_id=None, document_id="doc", **payload):
    return {
        "id": point_id, "score": 0.5,
        "payload": {"text": text, "document_id": document_id, "filename": "f.pdf",
                    "collection_id": coll_id, **payload},
    }


def _filter_scope(query_filter) -> set[str]:
    """qdrant_access_filter가 만든 필터의 컬렉션 범위(첫 must 조건)."""
    return set(query_filter.must[0].match.any)


def _retrieve(db, hits, *, collection_id=None, user_id="u", limit=2):
    provider = MagicMock()
    provider.embed.return_value = [[0.1, 0.2]]
    qdrant = MagicMock()
    qdrant.search.return_value = hits
    recorded = MagicMock()
    with patch("app.services.embedding.get_embedding_provider", return_value=provider), \
         patch("app.services.qdrant_service.qdrant_service", qdrant), \
         patch("app.services.reranker.cross_encoder_rerank",
               side_effect=lambda q, c, text_field, top_k: c[:top_k]) as rerank, \
         patch("app.services.chunk_stats.record_hits", recorded):
        out = chat._retrieve_chunks(db, user_id, "질문 키워드", collection_id, limit=limit)
    return out, qdrant, rerank, recorded


def test_retrieve_chunks_unscoped_query_without_accessible_collections_is_empty(world):
    out, qdrant, _rerank, _rec = _retrieve(world.db, [], user_id=str(world.stranger.id))

    assert out == []
    qdrant.search.assert_not_called()


def test_retrieve_chunks_restricts_unscoped_search_to_accessible_collections(world):
    out, qdrant, _r, _rec = _retrieve(world.db, [], user_id=str(world.alice.id))

    kwargs = qdrant.search.call_args.kwargs
    assert _filter_scope(kwargs["query_filter"]) == _ids(world.c_own, world.c_member, world.c_open)
    assert kwargs["limit"] == 2 * chat._HYBRID_CANDIDATE_MULTIPLIER
    assert out == []


def test_retrieve_chunks_rerank_trim_names_and_hit_recording(world):
    cid = str(world.c_own.id)
    doc_id = str(_document(world.db, world.alice, world.c_own).id)
    world.db.commit()
    hits = [
        _hit("p1", "질문 키워드 관련 본문", cid, doc_id, page_number=4),
        _hit("p2", "무관한 내용", cid, doc_id, index_text="질문 키워드 문맥"),
        _hit("p3", "또 다른 내용", cid, doc_id),
    ]

    out, qdrant, rerank, recorded = _retrieve(
        world.db, hits, collection_id=cid, user_id=str(world.alice.id), limit=2
    )

    assert _filter_scope(qdrant.search.call_args.kwargs["query_filter"]) == {cid}
    assert len(out) == 2
    assert out[0]["collection_name"] == "own"
    assert {o["text"] for o in out} <= {h["payload"]["text"] for h in hits}
    assert rerank.call_args.kwargs["top_k"] == 2
    recorded.assert_called_once()
    assert len(recorded.call_args.args[0]) == 2


def test_retrieve_chunks_no_hits_skips_rerank_and_stats(world):
    out, _q, rerank, recorded = _retrieve(
        world.db, [], collection_id=str(world.c_own.id), user_id=str(world.alice.id)
    )

    assert out == []
    rerank.assert_not_called()
    recorded.assert_not_called()


# -- 컬렉션 검색 설정과 근거(v3 마일스톤 6) --------------------------------------

def _settings_world(world, settings, **doc_fields):
    world.c_own.search_settings = settings
    doc = _document(world.db, world.alice, world.c_own, **doc_fields)
    world.db.commit()
    cid = str(world.c_own.id)
    hits = [
        {**_hit("p1", "질문 키워드 관련 본문", cid, str(doc.id), page_number=1), "score": 0.4},
        {**_hit("p2", "전혀 다른 내용", cid, str(doc.id), page_number=2), "score": 0.9},
        {**_hit("p3", "또 다른 내용", cid, str(doc.id), page_number=3), "score": 0.2},
        {**_hit("p4", "넷째 내용", cid, str(doc.id), page_number=3), "score": 0.1},
    ]
    return cid, hits


def test_retrieve_chunks_follows_vector_only_settings_without_rerank(world):
    cid, hits = _settings_world(world, {"mode": "vector", "top_k": 3, "rerank": False})

    with patch("app.services.bm25_service.bm25_rerank") as bm25:
        out, qdrant, rerank, _rec = _retrieve(world.db, hits, collection_id=cid,
                                              user_id=str(world.alice.id), limit=None)

    bm25.assert_not_called()
    rerank.assert_not_called()
    # 근거 수는 컬렉션 설정(3)이고, 벡터 점수 순서다
    assert [o["chunk_ref"] for o in out] == ["p2", "p1", "p3"]
    assert qdrant.search.call_args.kwargs["limit"] == 3 * chat._HYBRID_CANDIDATE_MULTIPLIER
    assert out[0]["evidence"]["scores"] == {"vector": 0.9}


def test_retrieve_chunks_hybrid_weight_and_evidence(world):
    cid, hits = _settings_world(
        world, {"mode": "hybrid", "vector_weight": 0.3},
        ocr_page_confidence=[{"page_number": 1, "confidence": 0.31, "word_count": 10},
                             {"page_number": 2, "confidence": 0.95, "word_count": 10}],
    )

    out, _q, rerank, _rec = _retrieve(world.db, hits, collection_id=cid, user_id=str(world.alice.id), limit=2)

    rerank.assert_called_once()
    first = next(o for o in out if o["chunk_ref"] == "p1")
    scores = first["evidence"]["scores"]
    # 키워드가 겹친 p1이 키워드 비중 0.7 덕분에 앞선다
    assert out[0]["chunk_ref"] == "p1"
    assert scores["fused"] == round(0.3 * 0.4 + 0.7 * scores["bm25"], 4)
    assert "키워드" in first["evidence"]["matched_terms"]
    assert first["evidence"]["ocr_confidence"] == 0.31 and first["evidence"]["low_ocr"] is True
    second = next(o for o in out if o["chunk_ref"] == "p2")
    assert second["evidence"]["low_ocr"] is False


def test_retrieve_chunks_ignores_broken_settings(world):
    cid, hits = _settings_world(world, {"mode": "nope", "top_k": 99})

    out, _q, rerank, _rec = _retrieve(world.db, hits, collection_id=cid, user_id=str(world.alice.id), limit=None)

    # 형식이 틀린 설정은 기본값(하이브리드, 5건, 재순위)으로 돈다
    assert rerank.call_args.kwargs["top_k"] == 5 and len(out) == 4


# ----------------------------------------------------------- api keys / verifier


def _fake_decrypt():
    return patch("app.core.crypto.decrypt_secret", side_effect=lambda v: f"plain-{v}")


def test_find_api_key_prefers_project_key_over_user_key(world):
    conv = SimpleNamespace(project_id=world.project.id, user_id=world.alice.id)
    world.db.add_all([
        ProjectApiKey(project_id=world.project.id, provider="openai", encrypted_key="PK"),
        UserApiKey(user_id=world.alice.id, provider="openai", encrypted_key="UK"),
        UserApiKey(user_id=world.alice.id, provider="anthropic", encrypted_key="UA"),
    ])
    world.db.commit()

    with _fake_decrypt():
        assert chat._find_api_key(world.db, conv, "openai") == "plain-PK"
        assert chat._find_api_key(world.db, conv, "anthropic") == "plain-UA"


def test_find_api_key_none_when_unregistered(world):
    conv = SimpleNamespace(project_id=None, user_id=world.stranger.id)

    assert chat._find_api_key(world.db, conv, "openai") is None


def test_verifier_reuses_cloud_generation_provider():
    gen = MagicMock()

    assert chat._get_verifier_provider(MagicMock(), MagicMock(), gen, "openai") is gen


def test_verifier_uses_cloud_model_when_byok_key_exists_for_local_generation():
    gen, cloud = MagicMock(), MagicMock()
    keys = {"openai": None, "anthropic": "k-ant"}

    with patch.object(chat, "_find_api_key", side_effect=lambda d, c, b: keys[b]), \
         patch("app.services.llm.get_llm_provider", return_value=cloud) as getter:
        out = chat._get_verifier_provider(MagicMock(), MagicMock(), gen, "local")

    assert out is cloud
    getter.assert_called_once_with("claude-3-5-haiku", api_key="k-ant")


def test_verifier_falls_back_to_generation_provider_without_keys_or_on_init_error():
    gen = MagicMock()

    with patch.object(chat, "_find_api_key", return_value=None):
        assert chat._get_verifier_provider(MagicMock(), MagicMock(), gen, "local") is gen

    with patch.object(chat, "_find_api_key", return_value="k"), \
         patch("app.services.llm.get_llm_provider", side_effect=RuntimeError("bad key")):
        assert chat._get_verifier_provider(MagicMock(), MagicMock(), gen, "local") is gen


# ------------------------------------------------------------ generate_answer


class ScriptedProvider:
    """Routes calls by system prompt so intent / reflection / answer are scripted."""

    def __init__(self, *, intent="CHUNK_SEARCH", grounded=("SUFFICIENT",),
                 stream_answers=("정답입니다[1]",), generate_answer="재시도 답변입니다[1]",
                 usage=None, plan="[]"):
        self.intent = intent
        self.plan = plan
        self.grounded = list(grounded)
        self.stream_answers = list(stream_answers)
        self.generate_answer = generate_answer
        self.last_usage = usage
        self.stream_calls: list[tuple[str, list]] = []
        self.generate_calls: list[tuple[str, list]] = []

    def generate(self, system_prompt, messages):
        self.generate_calls.append((system_prompt, messages))
        if system_prompt == chat._INTENT_SYSTEM_PROMPT:
            return self.intent
        if system_prompt == DECOMPOSE_SYSTEM_PROMPT:
            return self.plan
        if system_prompt == chat._REFLECTION_SYSTEM_PROMPT:
            return self.grounded.pop(0) if len(self.grounded) > 1 else self.grounded[0]
        return self.generate_answer

    def generate_stream(self, system_prompt, messages, on_delta):
        self.stream_calls.append((system_prompt, messages))
        text = self.stream_answers.pop(0) if len(self.stream_answers) > 1 else self.stream_answers[0]
        on_delta(text)
        return text


CHUNK = {
    "document_id": "d1", "collection_id": "c1", "collection_name": "Coll",
    "filename": "a.pdf", "page_number": 2, "text": "본문 발췌",
}


@pytest.fixture
def chat_env(world):
    """conversation + pending message for alice; returns a runner."""
    def build(*, model_key="qwen2.5-3b", project=None, collection=None, query="질문입니다", mode="standard"):
        db = world.db
        conv = ChatConversation(
            id=uuid4(), user_id=world.alice.id, project_id=project.id if project else None,
            collection_id=collection.id if collection else None, model_key=model_key,
            title="t",
        )
        db.add(conv)
        db.flush()
        msg = ChatMessage(id=uuid4(), conversation_id=conv.id, query=query, status="PENDING", mode=mode)
        db.add(msg)
        db.commit()
        return conv, msg

    redis_client = MagicMock()
    redis_client.get.return_value = None

    def run(msg_id, provider, *, retrieve=None, redis_=None, **patches):
        session = world.factory()
        retrieval = retrieve if retrieve is not None else MagicMock(return_value=[CHUNK])
        with patch("app.db.session.get_sync_db", return_value=session), \
             patch("redis.from_url", return_value=redis_ or redis_client), \
             patch("app.services.llm.get_llm_provider", return_value=provider), \
             patch.object(chat, "_retrieve_chunks", retrieval), \
             patch.object(chat, "_retrieve_table_chunks", patches.get("table", MagicMock())), \
             patch.object(chat, "_retrieve_summary_chunks", patches.get("summary", MagicMock())):
            result = chat.generate_answer.run(str(msg_id))
        return result, retrieval

    def reload(msg_id):
        fresh = world.factory()
        return fresh.get(ChatMessage, msg_id), fresh

    return SimpleNamespace(build=build, run=run, reload=reload, redis=redis_client)


def test_generate_answer_not_found_when_message_missing(chat_env):
    result, _ = chat_env.run(uuid4(), ScriptedProvider())

    assert result["status"] == "NOT_FOUND"


def test_generate_answer_happy_path_persists_answer_citations_and_cache(chat_env):
    _conv, msg = chat_env.build()
    provider = ScriptedProvider()

    result, _ = chat_env.run(msg.id, provider)

    stored, db = chat_env.reload(msg.id)
    assert result == {"chat_message_id": str(msg.id), "status": "DONE"}
    assert stored.status == "DONE"
    assert stored.answer == "정답입니다[1]"
    assert stored.citations == [{
        "index": 1, "document_id": "d1", "collection_id": "c1", "collection_name": "Coll",
        "filename": "a.pdf", "page_number": 2, "text": "본문 발췌", "evidence": None,
    }]
    cache_args = chat_env.redis.setex.call_args_list[-1].args
    assert cache_args[0].startswith("rag_answer:qwen2.5-3b:")
    assert cache_args[1] == chat._ANSWER_CACHE_TTL_SECONDS
    assert json.loads(cache_args[2])["answer"] == "정답입니다[1]"
    chat_env.redis.delete.assert_called_once_with(f"chat_partial:{msg.id}", f"chat_progress:{msg.id}")
    # the question and retrieved context both reach the model
    sent = provider.stream_calls[0][1][-1]["content"]
    assert "질문입니다" in sent and "[1] a.pdf (2쪽): 본문 발췌" in sent
    db.close()


def test_generate_answer_serves_exact_match_from_cache_without_calling_llm(chat_env):
    _conv, msg = chat_env.build()
    redis_hit = MagicMock()
    redis_hit.get.return_value = json.dumps({"answer": "캐시 답", "citations": [{"index": 1}]})
    provider = ScriptedProvider()

    result, retrieval = chat_env.run(msg.id, provider, redis_=redis_hit)

    stored, db = chat_env.reload(msg.id)
    assert result["cached"] is True
    assert stored.status == "DONE" and stored.answer == "캐시 답"
    assert stored.citations == [{"index": 1}]
    assert provider.stream_calls == [] and provider.generate_calls == []
    retrieval.assert_not_called()
    db.close()


def test_generate_answer_unknown_model_marks_message_failed(chat_env):
    _conv, msg = chat_env.build(model_key="no-such-model")

    result, _ = chat_env.run(msg.id, ScriptedProvider())

    stored, db = chat_env.reload(msg.id)
    assert result["status"] == "FAILED"
    assert stored.status == "FAILED"
    assert "Unknown model" in stored.error_message
    db.close()


def test_generate_answer_cloud_model_without_registered_key_fails_with_clear_message(chat_env):
    _conv, msg = chat_env.build(model_key="gpt-4o-mini")

    with patch.object(chat, "_find_api_key", return_value=None):
        result, _ = chat_env.run(msg.id, ScriptedProvider())

    stored, db = chat_env.reload(msg.id)
    assert result["status"] == "FAILED"
    assert "API 키가 등록되어 있지 않습니다" in stored.error_message
    db.close()


def test_generate_answer_missing_conversation_records_failure():
    msg = SimpleNamespace(conversation_id="gone", status="PENDING", error_message=None)
    db = MagicMock()
    db.get.side_effect = [msg, None, msg]

    with patch("app.db.session.get_sync_db", return_value=db):
        result = chat.generate_answer.run("m1")

    assert result["status"] == "FAILED"
    assert "Conversation not found" in result["error"]
    assert msg.status == "FAILED"
    db.rollback.assert_called_once()
    db.close.assert_called_once()


def test_generate_answer_truncates_long_error_message(chat_env):
    _conv, msg = chat_env.build()
    boom = MagicMock(side_effect=RuntimeError("x" * 800))

    result, _ = chat_env.run(msg.id, ScriptedProvider(), retrieve=boom)

    stored, db = chat_env.reload(msg.id)
    assert stored.status == "FAILED"
    assert len(stored.error_message) == 500
    db.close()


@pytest.mark.parametrize(
    "intent,expected_fn", [("TABLE_QUERY", "table"), ("SUMMARY_LOOKUP", "summary")]
)
def test_generate_answer_routes_to_intent_specific_retrieval(chat_env, intent, expected_fn):
    _conv, msg = chat_env.build()
    table, summary = MagicMock(return_value=[CHUNK]), MagicMock(return_value=[CHUNK])

    _result, chunk_search = chat_env.run(
        msg.id, ScriptedProvider(intent=intent), table=table, summary=summary
    )

    called = {"table": table, "summary": summary}[expected_fn]
    called.assert_called_once()
    chunk_search.assert_not_called()


def test_generate_answer_retries_once_on_citation_only_output(chat_env):
    _conv, msg = chat_env.build()
    provider = ScriptedProvider(stream_answers=("[1], [2]",), generate_answer="완전한 설명 문장입니다[1].")

    chat_env.run(msg.id, provider)

    stored, db = chat_env.reload(msg.id)
    assert stored.answer == "완전한 설명 문장입니다[1]."
    retry_messages = [c for c in provider.generate_calls
                      if c[0] not in (chat._INTENT_SYSTEM_PROMPT, chat._REFLECTION_SYSTEM_PROMPT)]
    assert len(retry_messages) == 1
    assert retry_messages[0][1][-2] == {"role": "assistant", "content": "[1], [2]"}
    db.close()


def test_generate_answer_broadens_retrieval_once_when_answer_ungrounded(chat_env):
    _conv, msg = chat_env.build()
    provider = ScriptedProvider(grounded=("INSUFFICIENT",), stream_answers=("첫 답[1]", "확장 답[1]"))
    broader = {**CHUNK, "filename": "wide.pdf"}
    retrieval = MagicMock(side_effect=[[CHUNK], [broader, broader]])

    chat_env.run(msg.id, provider, retrieve=retrieval)

    stored, db = chat_env.reload(msg.id)
    assert retrieval.call_count == 2
    assert retrieval.call_args_list[1].kwargs["limit"] == 10
    assert stored.answer == "확장 답[1]"
    assert [c["filename"] for c in stored.citations] == ["wide.pdf", "wide.pdf"]
    assert len(provider.stream_calls) == 2  # capped at exactly one extra hop
    db.close()


def test_generate_answer_keeps_first_answer_when_broadening_finds_nothing(chat_env):
    _conv, msg = chat_env.build()
    provider = ScriptedProvider(grounded=("INSUFFICIENT",), stream_answers=("첫 답[1]",))
    retrieval = MagicMock(side_effect=[[CHUNK], []])

    chat_env.run(msg.id, provider, retrieve=retrieval)

    stored, db = chat_env.reload(msg.id)
    assert stored.answer == "첫 답[1]"
    assert len(stored.citations) == 1
    db.close()


def test_generate_answer_skips_reflection_when_nothing_retrieved(chat_env):
    _conv, msg = chat_env.build()
    provider = ScriptedProvider()

    chat_env.run(msg.id, provider, retrieve=MagicMock(return_value=[]))

    stored, db = chat_env.reload(msg.id)
    assert stored.status == "DONE" and stored.citations == []
    assert all(c[0] != chat._REFLECTION_SYSTEM_PROMPT for c in provider.generate_calls)
    assert "(관련 발췌문 없음)" in provider.stream_calls[0][1][-1]["content"]
    db.close()


def test_generate_answer_logs_usage_and_cost_for_cloud_provider(chat_env, world):
    _conv, msg = chat_env.build(model_key="gpt-4o-mini")
    provider = ScriptedProvider(usage={"input_tokens": 1000, "output_tokens": 500})

    with patch.object(chat, "_find_api_key", return_value="sk-test"):
        result, _ = chat_env.run(msg.id, provider)

    db = world.factory()
    log = db.query(LLMUsageLog).filter_by(conversation_id=_conv.id).one()
    assert result["status"] == "DONE"
    assert (log.provider, log.model_key) == ("openai", "gpt-4o-mini")
    assert (log.input_tokens, log.output_tokens) == (1000, 500)
    assert float(log.estimated_cost_usd) == pytest.approx(0.00045)
    db.close()


def test_generate_answer_prompt_priority_project_then_user_then_default(chat_env, world):
    world.project.system_prompt = "PROJECT PROMPT"
    world.alice.system_prompt = "USER PROMPT"
    world.db.merge(world.project)
    world.db.merge(world.alice)
    world.db.commit()
    _c1, with_project = chat_env.build(project=world.project)
    _c2, user_only = chat_env.build()
    p1, p2 = ScriptedProvider(), ScriptedProvider()

    chat_env.run(with_project.id, p1)
    chat_env.run(user_only.id, p2)
    world.alice.system_prompt = None
    world.db.merge(world.alice)
    world.db.commit()
    _c3, default_msg = chat_env.build()
    p3 = ScriptedProvider()
    chat_env.run(default_msg.id, p3)

    assert p1.stream_calls[0][0] == "PROJECT PROMPT"
    assert p2.stream_calls[0][0] == "USER PROMPT"
    assert p3.stream_calls[0][0] == chat._SYSTEM_PROMPT


def test_generate_answer_includes_only_last_three_done_turns_as_history(chat_env, world):
    conv, msg = chat_env.build()
    base = msg.created_at
    from datetime import timedelta

    for i in range(5):
        world.db.add(ChatMessage(
            id=uuid4(), conversation_id=conv.id, query=f"이전질문{i}", answer=f"이전답{i}",
            status="DONE", created_at=base - timedelta(minutes=10 - i),
        ))
    world.db.add(ChatMessage(id=uuid4(), conversation_id=conv.id, query="실패한질문",
                             status="FAILED", created_at=base - timedelta(minutes=1)))
    world.db.commit()
    provider = ScriptedProvider()

    chat_env.run(msg.id, provider)

    sent = provider.stream_calls[0][1]
    assert [m["content"] for m in sent[:-1]] == [
        "이전질문2", "이전답2", "이전질문3", "이전답3", "이전질문4", "이전답4",
    ]
    assert sent[-1]["role"] == "user"


def test_generate_answer_survives_redis_write_failures(chat_env):
    _conv, msg = chat_env.build()
    flaky = MagicMock()
    flaky.get.return_value = None
    flaky.setex.side_effect = RuntimeError("redis down")
    flaky.delete.side_effect = RuntimeError("redis down")

    result, _ = chat_env.run(msg.id, ScriptedProvider(), redis_=flaky)

    stored, db = chat_env.reload(msg.id)
    assert result["status"] == "DONE" and stored.status == "DONE"
    db.close()


# -- 심층 검색(v3 마일스톤 5) ----------------------------------------------------

DEEP_PLAN = '["2027년 영업 목표는?", "2026년 영업 실적은?"]'


def test_deep_mode_splits_the_question_and_searches_each_part(chat_env):
    _conv, msg = chat_env.build(mode="deep", query="2027년 목표와 2026년 실적을 비교해 줘")
    provider = ScriptedProvider(plan=DEEP_PLAN)
    retrieval = MagicMock(side_effect=[
        [{**CHUNK, "chunk_ref": "c1", "score": 2.0}, {**CHUNK, "chunk_ref": "c2", "score": 1.0}],
        [{**CHUNK, "document_id": "d2", "filename": "b.pdf", "chunk_ref": "c3", "score": 2.0},
         {**CHUNK, "document_id": "d2", "filename": "b.pdf", "chunk_ref": "c4", "score": 1.5}],
    ])

    result, _ = chat_env.run(msg.id, provider, retrieve=retrieval)

    stored, db = chat_env.reload(msg.id)
    assert result["status"] == "DONE" and stored.mode == "deep"
    # 의도 분류 대신 분해를 쓰고, 하위 질문마다 4개씩 찾는다
    prompts = [c[0] for c in provider.generate_calls]
    assert chat._INTENT_SYSTEM_PROMPT not in prompts and DECOMPOSE_SYSTEM_PROMPT in prompts
    assert [(c.args[2], c.kwargs["limit"]) for c in retrieval.call_args_list] == [
        ("2027년 영업 목표는?", 4), ("2026년 영업 실적은?", 4)]
    sent = provider.stream_calls[0][1][-1]["content"]
    assert "1. 2027년 영업 목표는?" in sent and "2. 2026년 영업 실적은?" in sent
    assert [q["question"] for q in stored.agent_steps["subquestions"]] == ["2027년 영업 목표는?", "2026년 영업 실적은?"]
    assert {"plan", "search", "answer", "verify"} <= set(stored.agent_steps["timings_ms"])
    assert len(stored.citations) == 4
    keys = [c.args[0] for c in chat_env.redis.setex.call_args_list]
    assert f"chat_progress:{msg.id}" in keys
    assert any(k.startswith("rag_answer_deep:qwen2.5-3b:") for k in keys)
    trace = db.scalar(select(AnswerTrace).where(AnswerTrace.chat_message_id == msg.id))
    assert trace.mode == "deep" and trace.intent == "deep" and trace.agent_steps["decomposed"] is True
    db.close()


def test_deep_mode_does_not_broaden_again_when_grounding_fails(chat_env):
    _conv, msg = chat_env.build(mode="deep")
    provider = ScriptedProvider(plan=DEEP_PLAN, grounded=("INSUFFICIENT",))
    retrieval = MagicMock(return_value=[{**CHUNK, "chunk_ref": "c1", "score": 2.0},
                                        {**CHUNK, "chunk_ref": "c2", "score": 2.0}])

    chat_env.run(msg.id, provider, retrieve=retrieval)

    stored, db = chat_env.reload(msg.id)
    assert stored.status == "DONE" and retrieval.call_count == 2 and len(provider.stream_calls) == 1
    db.close()


def test_deep_mode_cache_hit_restores_the_search_steps(chat_env):
    _conv, msg = chat_env.build(mode="deep")
    redis_hit = MagicMock()
    redis_hit.get.return_value = json.dumps({"answer": "캐시 답", "citations": [], "agent_steps": {"subquestions": []}})

    chat_env.run(msg.id, ScriptedProvider(), redis_=redis_hit)

    stored, db = chat_env.reload(msg.id)
    assert stored.answer == "캐시 답" and stored.agent_steps == {"subquestions": []}
    assert redis_hit.get.call_args.args[0].startswith("rag_answer_deep:")
    db.close()


def test_deep_mode_cache_is_dropped_when_a_searched_document_is_no_longer_visible(chat_env):
    # 인용은 없지만 검색 과정에 지금 볼 수 없는 문서가 남은 캐시는 쓰지 않고 새로 만든다
    _conv, msg = chat_env.build(mode="deep")
    redis_hit = MagicMock()
    stale_steps = {"subquestions": [{"question": "q", "documents": [{"document_id": str(uuid4()), "filename": "기밀.pdf"}]}]}
    redis_hit.get.return_value = json.dumps({"answer": "캐시 답", "citations": [], "agent_steps": stale_steps})
    retrieval = MagicMock(return_value=[{**CHUNK, "chunk_ref": "c1", "score": 2.0},
                                        {**CHUNK, "chunk_ref": "c2", "score": 2.0}])

    chat_env.run(msg.id, ScriptedProvider(plan=DEEP_PLAN), retrieve=retrieval, redis_=redis_hit)

    stored, db = chat_env.reload(msg.id)
    assert stored.answer != "캐시 답" and "기밀.pdf" not in json.dumps(stored.agent_steps, ensure_ascii=False)
    assert redis_hit.delete.call_args_list[0].args[0].startswith("rag_answer_deep:")
    db.close()


def test_deep_mode_failure_keeps_the_search_steps_and_clears_progress(chat_env):
    _conv, msg = chat_env.build(mode="deep")
    provider = ScriptedProvider(plan=DEEP_PLAN)
    provider.generate_stream = MagicMock(side_effect=RuntimeError("cuda oom"))
    retrieval = MagicMock(return_value=[{**CHUNK, "chunk_ref": "c1", "score": 2.0},
                                        {**CHUNK, "chunk_ref": "c2", "score": 2.0}])
    redis_ = MagicMock()
    redis_.get.return_value = None

    result, _ = chat_env.run(msg.id, provider, retrieve=retrieval, redis_=redis_)

    stored, db = chat_env.reload(msg.id)
    assert result["status"] == "FAILED" and stored.status == "FAILED"
    trace = db.scalar(select(AnswerTrace).where(AnswerTrace.chat_message_id == msg.id))
    assert trace.status == "FAILED" and len(trace.agent_steps["subquestions"]) == 2
    deleted = [k for c in redis_.delete.call_args_list for k in c.args]
    assert f"chat_progress:{msg.id}" in deleted
    db.close()



def test_answer_cache_key_changes_with_retrieval_variant():
    base = chat._answer_cache_key("q", "c", None, "m", "fp")
    with_variant = chat._answer_cache_key("q", "c", None, "m", "fp", variant="s1:d2")
    assert with_variant != base
    assert chat._answer_cache_key("q", "c", None, "m", "fp", variant="s1:d3") != with_variant


def test_retrieval_variant_follows_collection_settings_and_dictionary_revision():
    from app.services.search_settings import SearchSettings

    def variant(search, revision):
        with patch("app.services.search_settings.collection_search_settings_sync", return_value=search),              patch("app.services.dictionary_service.ensure_dictionary_cache_sync"),              patch("app.services.dictionary_service._loaded_revision", revision):
            return chat._retrieval_variant(MagicMock(), "c")

    base = variant(SearchSettings(), 4)
    assert variant(SearchSettings(), 4) == base
    assert variant(SearchSettings(rerank=False), 4) != base
    assert variant(SearchSettings(), 5) != base


def test_retrieval_variant_survives_a_dictionary_failure():
    from app.services.search_settings import SearchSettings

    with patch("app.services.search_settings.collection_search_settings_sync", return_value=SearchSettings()),          patch("app.services.dictionary_service.ensure_dictionary_cache_sync", side_effect=RuntimeError("kiwi")):
        assert chat._retrieval_variant(MagicMock(), "c").startswith("s")


def test_retrieve_chunks_searches_the_original_query_when_expansion_fails(world):
    cid, hits = _settings_world(world, {"mode": "vector", "rerank": False})

    with patch("app.services.dictionary_service.expand_query", side_effect=RuntimeError("kiwi")):
        out, qdrant, _rerank, _rec = _retrieve(world.db, hits, collection_id=cid,
                                              user_id=str(world.alice.id), limit=None)

    assert qdrant.search.called and out
