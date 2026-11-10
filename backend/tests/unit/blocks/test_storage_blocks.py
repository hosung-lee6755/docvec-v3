"""storage_blocks: ChunkSplitBlock / RagStoreBlock 테스트 (DB·임베딩·Qdrant 경계는 모킹)."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.blocks import storage_blocks as sb
from app.pipeline.blocks.base import BlockContext

TEXT = ("첫째 문단입니다. " * 8 + "\n\n" + "둘째 문단입니다. " * 8 + "\n\n" + "셋째 문단입니다. " * 8)


def _ctx(config=None, upstream=None, document_id="doc-1", run_id="run-1"):
    return BlockContext(
        run_id=run_id, block_instance_id="b", document_id=document_id,
        upstream_outputs={"up": upstream or {}}, config=config or {},
    )


def _doc(**kw):
    base = dict(
        id="doc-1", parsed_text=TEXT, page_map=[], tables=None, language="ko", title="제목",
        original_filename="a.pdf", collection_id="col-1", tags=["t"], status="PARSED",
        updated_at=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ---- ChunkSplitBlock ----
def _split(doc, config=None, upstream=None, nodes=None, run_row="default", settings=None):
    db = MagicMock()
    run = SimpleNamespace(dictionary_version=4, version_id="v1") if run_row == "default" else run_row

    def _get(model, _id):
        name = model.__name__
        if name == "Document":
            return doc
        if name == "WorkflowRun":
            return run
        return SimpleNamespace(version_number=7)

    db.get.side_effect = _get
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = nodes or []
    coll = settings or ("model", 100, 10, 0, "fixed")
    with patch("app.db.session.get_sync_db", return_value=db), \
            patch("app.pipeline.tasks.process._resolve_collection_settings", return_value=coll), \
            patch("app.services.embedding.get_embedding_provider", return_value=MagicMock()):
        result = sb.ChunkSplitBlock().run(_ctx(config, upstream))
    return result, db


def _added(db):
    return [c.args[0] for c in db.add.call_args_list]


def test_chunk_split_requires_document_id():
    with pytest.raises(ValueError):
        sb.ChunkSplitBlock().run(_ctx(document_id=None))


def test_chunk_split_missing_document():
    db = MagicMock()
    db.get.return_value = None
    with patch("app.db.session.get_sync_db", return_value=db), \
            patch("app.pipeline.tasks.process._resolve_collection_settings"), \
            patch("app.services.embedding.get_embedding_provider"):
        with pytest.raises(ValueError, match="찾을 수 없"):
            sb.ChunkSplitBlock().run(_ctx())
    db.close.assert_called_once()


def test_chunk_split_fixed_creates_children_parents_and_links():
    result, db = _split(_doc(), {"strategy": "fixed", "max_tokens": 100, "min_tokens": 10, "overlap_tokens": 0})
    rows = _added(db)
    children = [r for r in rows if r.chunk_tier == "child"]
    parents = [r for r in rows if r.chunk_tier == "parent"]
    assert len(children) == result.output["chunk_count"] >= 2
    assert parents and all(p.embedded is False for p in parents)
    assert result.output["chunk_ids"] == [str(c.id) for c in children]
    assert all(c.parent_chunk_id for c in children)
    assert children[0].prev_chunk_id is None and children[-1].next_chunk_id is None
    assert children[0].next_chunk_id == children[1].id
    assert children[1].prev_chunk_id == children[0].id
    assert all(c.workflow_version == 7 and c.dictionary_version == 4 for c in children)
    assert all(c.language == "ko" and c.source_file == "a.pdf" for c in children)
    db.flush.assert_called_once()
    db.commit.assert_called_once()
    db.close.assert_called_once()
    assert result.metrics == {"chunk_count": len(children), "strategy": "fixed"}


def test_chunk_split_inherits_collection_strategy_and_sizes():
    result, _ = _split(_doc(), settings=("m", 80, 5, 0, "fixed"))
    assert result.metrics["strategy"] == "fixed"


def test_chunk_split_sentence_strategy():
    result, db = _split(_doc(), {"strategy": "sentence", "max_tokens": 100, "min_tokens": 10})
    assert result.metrics["strategy"] == "sentence"
    assert result.output["chunk_count"] >= 1


def test_chunk_split_semantic_strategy_uses_embedding_provider():
    with patch("app.pipeline.tasks.process._chunk_text_semantic",
               return_value=[("의미 단위 청크", 0, 8)]) as semantic:
        result, db = _split(_doc(), {"strategy": "semantic"})
    semantic.assert_called_once()
    assert result.output["chunk_count"] == 1


def test_chunk_split_unknown_strategy_falls_back_to_fixed():
    result, _ = _split(_doc(), {"strategy": "whatever", "max_tokens": 100, "min_tokens": 10})
    assert result.output["chunk_count"] >= 1


@pytest.mark.parametrize("strategy", ["paragraph", "section_aware", "table_unit"])
def test_chunk_split_tree_strategies_require_nodes(strategy):
    with pytest.raises(ValueError, match="구조 분석"):
        _split(_doc(), {"strategy": strategy}, nodes=[])


def test_chunk_split_tree_strategy_copies_node_type_and_element_id():
    node = SimpleNamespace(
        id="n1", node_type="PARAGRAPH", element_id="el-1", text="본문입니다 " * 5,
        sort_order=0, span_start=0, span_end=len("본문입니다 " * 5), level=None,
        parent_id=None, page_number=1, meta=None,
    )
    spans = [SimpleNamespace(text="본문입니다", start=0, end=5, section_path=["1장"], source_node_ids=["n1"])]
    with patch("app.pipeline.blocks.chunk_strategies._tree_based_chunks", return_value=spans):
        result, db = _split(_doc(), {"strategy": "paragraph"}, nodes=[node])
    child = [r for r in _added(db) if r.chunk_tier == "child"][0]
    assert child.chunk_type == "PARAGRAPH"
    assert child.element_id == "el-1"
    assert child.section_path == ["1장"]
    assert child.source_node_ids == ["n1"]


def test_chunk_split_flags_chunks_overlapping_pii_spans():
    result, db = _split(
        _doc(), {"strategy": "fixed", "max_tokens": 100, "min_tokens": 10},
        upstream={"text": TEXT, "pii_excluded_spans": [[0, 5]]},
    )
    children = [r for r in _added(db) if r.chunk_tier == "child"]
    assert children[0].excluded_pii is True
    assert children[-1].excluded_pii is False


def test_chunk_split_without_run_row_leaves_versions_none():
    result, db = _split(_doc(), {"strategy": "fixed"}, run_row=None)
    child = [r for r in _added(db) if r.chunk_tier == "child"][0]
    assert child.workflow_version is None and child.dictionary_version is None


def test_chunk_split_falls_back_to_parsed_text_and_handles_empty():
    result, db = _split(_doc(parsed_text=""), {"strategy": "fixed"})
    assert result.output["chunk_count"] == 0
    assert result.output["chunk_ids"] == []
    db.commit.assert_called_once()


def test_chunk_split_clears_previous_chunks_before_insert():
    _, db = _split(_doc(), {"strategy": "fixed"})
    db.query.return_value.filter.return_value.delete.assert_called_once()


def test_chunk_split_config_defaults_and_validation():
    cfg = sb.ChunkSplitConfig()
    assert cfg.strategy is None and cfg.preserve_table is True
    with pytest.raises(Exception):
        sb.ChunkSplitConfig(max_tokens="many")


# ---- 문맥 헬퍼 ----
def test_llm_chunk_contexts_rejects_hanja_heavy_and_blank_answers(monkeypatch):
    answers = iter(["漢字漢字漢字", "   ", "정상적인 한국어 문장"])
    monkeypatch.setattr("app.pipeline.blocks.content_blocks._generate", lambda s, u: next(answers))
    chunks = [SimpleNamespace(id=i, chunk_text="본문") for i in ("a", "b", "c")]
    assert sb._llm_chunk_contexts("제목", "발췌", chunks) == {"c": "정상적인 한국어 문장"}


def test_llm_chunk_contexts_takes_first_nonempty_line(monkeypatch):
    monkeypatch.setattr("app.pipeline.blocks.content_blocks._generate", lambda s, u: "\n\n  첫 줄  \n둘째 줄")
    chunks = [SimpleNamespace(id="a", chunk_text="본문")]
    assert sb._llm_chunk_contexts(None, "발췌", chunks) == {"a": "첫 줄"}


# ---- RagStoreBlock ----
def _chunk(cid, order=0, text="청크 본문", section_path=None):
    return SimpleNamespace(
        id=cid, chunk_order=order, chunk_text=text, section_path=section_path, page_start=1,
        embedded=False, embedding_model=None, version=None, context_header=None,
    )


def _rag(doc, chunks, config=None, upstream=None, excluded=0, llm=None):
    db = MagicMock()
    db.get.return_value = doc
    query = db.query.return_value.filter.return_value
    query.filter.return_value.count.return_value = excluded
    query.filter.return_value.order_by.return_value.all.return_value = chunks
    query.order_by.return_value.all.return_value = chunks
    provider = MagicMock()
    provider.dimension = 3
    provider.embed.side_effect = lambda texts: [[0.1, 0.2, 0.3] for _ in texts]
    qdrant = MagicMock()
    with patch("app.db.session.get_sync_db", return_value=db), \
            patch("app.pipeline.tasks.process._resolve_collection_settings", return_value=("coll-model", 1, 1, 0, "fixed")), \
            patch("app.services.embedding.get_embedding_provider", return_value=provider) as getter, \
            patch("app.services.qdrant_service.qdrant_service", qdrant), \
            patch.object(sb, "_llm_chunk_contexts", return_value=llm or {}) as llm_mock:
        result = sb.RagStoreBlock().run(_ctx(config, upstream or {"chunk_ids": ["c1"]}))
    return result, db, provider, qdrant, getter, llm_mock


def test_rag_store_requires_document_id():
    with pytest.raises(ValueError):
        sb.RagStoreBlock().run(_ctx(document_id=None))


def test_rag_store_missing_document():
    db = MagicMock()
    db.get.return_value = None
    with patch("app.db.session.get_sync_db", return_value=db):
        with pytest.raises(ValueError, match="찾을 수 없"):
            sb.RagStoreBlock().run(_ctx())
    db.close.assert_called_once()


def test_rag_store_upserts_points_and_stamps_chunks():
    doc = _doc()
    chunks = [_chunk("c1", 0, "본문1", ["1장"]), _chunk("c2", 1, "본문2")]
    result, db, provider, qdrant, _, _ = _rag(doc, chunks, upstream={"chunk_ids": ["c1", "c2"]}, excluded=2)
    points = qdrant.upsert_points.call_args.args[1]
    assert [p["id"] for p in points] == ["c1", "c2"]
    assert points[0]["payload"]["index_text"] == "제목 > 1장\n\n본문1"
    assert points[0]["payload"]["text"] == "본문1"
    assert points[0]["payload"]["workflow_run_id"] == "run-1"
    assert points[0]["payload"]["tags"] == ["t"]
    assert chunks[0].embedded and chunks[0].embedding_model == "coll-model"
    assert chunks[0].version == "3" and chunks[0].context_header == "제목 > 1장"
    assert chunks[1].context_header == "제목"
    assert doc.status == "INDEXED"
    assert result.output["points_upserted"] == 2
    assert result.metrics == {"points_upserted": 2, "excluded_pii_chunks": 2}
    qdrant.delete_by_document.assert_called_once()
    qdrant.init_collection.assert_called_once()
    db.commit.assert_called_once()
    db.close.assert_called_once()


def test_rag_store_without_title_or_path_uses_raw_text():
    doc = _doc(title=None, collection_id=None, tags=None)
    chunk = _chunk("c1", text="원문")
    _, _, provider, qdrant, _, _ = _rag(doc, [chunk])
    assert provider.embed.call_args.args[0] == ["원문"]
    payload = qdrant.upsert_points.call_args.args[1][0]["payload"]
    assert payload["collection_id"] is None and payload["tags"] == []
    assert chunk.context_header is None


def test_rag_store_no_chunks_marks_indexed_without_upsert():
    doc = _doc()
    result, db, _, qdrant, _, _ = _rag(doc, [])
    assert result.output["points_upserted"] == 0
    assert result.output["text"] == TEXT
    assert doc.status == "INDEXED"
    qdrant.delete_by_document.assert_called_once()
    qdrant.init_collection.assert_not_called()
    qdrant.upsert_points.assert_not_called()


def test_rag_store_exclude_pii_disabled_skips_count():
    _, _, _, _, _, _ = _rag(_doc(), [_chunk("c1")], config={"exclude_pii": False})
    result, *_ = _rag(_doc(), [_chunk("c1")], config={"exclude_pii": False}, excluded=9)
    assert result.metrics["excluded_pii_chunks"] == 0


def test_rag_store_embedding_model_override():
    result, _, _, _, getter, _ = _rag(_doc(), [_chunk("c1")], config={"embedding_model": "custom"})
    getter.assert_called_once_with("custom")
    assert result.output["embedding_model"] == "custom"


def test_rag_store_llm_context_appended_when_enabled():
    chunk = _chunk("c1", text="본문")
    result, _, provider, _, _, llm_mock = _rag(
        _doc(), [chunk], config={"enable_llm_context": True}, llm={"c1": "역할 설명"},
    )
    llm_mock.assert_called_once()
    assert provider.embed.call_args.args[0] == ["제목 — 역할 설명\n\n본문"]
    assert chunk.context_header == "제목 — 역할 설명"


def test_rag_store_llm_context_not_called_by_default():
    *_, llm_mock = _rag(_doc(), [_chunk("c1")])
    llm_mock.assert_not_called()


def test_rag_store_closes_db_on_embedding_error():
    db = MagicMock()
    db.get.return_value = _doc()
    provider = MagicMock()
    provider.embed.side_effect = RuntimeError("gpu")
    db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value = [_chunk("c1")]
    with patch("app.db.session.get_sync_db", return_value=db), \
            patch("app.pipeline.tasks.process._resolve_collection_settings", return_value=("m", 1, 1, 0, "f")), \
            patch("app.services.embedding.get_embedding_provider", return_value=provider), \
            patch("app.services.qdrant_service.qdrant_service", MagicMock()):
        with pytest.raises(RuntimeError):
            sb.RagStoreBlock().run(_ctx(upstream={"chunk_ids": ["c1"]}))
    db.close.assert_called_once()
    db.commit.assert_not_called()


def test_block_metadata():
    split, store = sb.ChunkSplitBlock(), sb.RagStoreBlock()
    assert (split.block_type, store.block_type) == ("chunk_split", "rag_store")
    assert split.block_version == "1.5.0" and store.block_version == "1.4.0"
    assert split.category == store.category == "분할·저장"
    assert split.config_schema is sb.ChunkSplitConfig
    assert store.config_schema is sb.RagStoreConfig
