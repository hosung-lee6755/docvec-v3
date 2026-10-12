"""Coverage for app.pipeline.tasks.process — chunking helpers, page mapping,
figure recognition, HWP repagination and the continue_processing Celery task.

All external boundaries (DB, embedding provider, Qdrant, MinIO, LLM, Tesseract)
are mocked; nothing here loads a model or touches the network."""

import io
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.adapters.base import (
    RawImageRegion,
    RawPage,
    RawParsedDocument,
    RawTableCandidate,
    RawTextBlock,
)
from app.pipeline.tasks import process as proc


# ---------------------------------------------------------------- _chunk_text


def test_chunk_text_returns_empty_for_blank_input():
    assert proc._chunk_text("   \n ") == []


def test_chunk_text_single_chunk_when_text_fits():
    assert proc._chunk_text("hello", max_chars=100) == [("hello", 0, 5)]


def test_chunk_text_prefers_paragraph_boundary_within_lookback():
    text = "a" * 85 + "\n\n" + "b" * 60
    chunks = proc._chunk_text(text, max_chars=100, overlap=0)

    assert chunks[0] == ("a" * 85 + "\n\n", 0, 87)
    assert chunks[1][1] == 87


def test_chunk_text_hard_cuts_with_overlap_when_no_boundary():
    text = "x" * 250
    chunks = proc._chunk_text(text, max_chars=100, overlap=20)

    assert [(s, e) for _t, s, e in chunks] == [(0, 100), (80, 180), (160, 250)]
    assert chunks[0][0][-20:] == chunks[1][0][:20]


def test_chunk_text_merges_undersized_trailing_chunk():
    text = "y" * 105
    chunks = proc._chunk_text(text, max_chars=100, overlap=0, min_chars=20)

    assert len(chunks) == 1
    assert chunks[0] == ("y" * 105, 0, 105)


# ---------------------------------------------------- _chunk_text_semantic


def test_semantic_chunking_blank_text_returns_empty():
    assert proc._chunk_text_semantic("  ", MagicMock(), 100, 0) == []


def test_semantic_chunking_few_sentences_falls_back_to_size_chunking():
    provider = MagicMock()
    out = proc._chunk_text_semantic("One. Two.", provider, max_chars=100, min_chars=0)

    assert out == [("One. Two.", 0, 9)]
    provider.embed.assert_not_called()


def test_semantic_chunking_cuts_at_topic_shift():
    text = "Cat one. Cat two. Cat three. Stock a. Stock b. Stock c."
    # two topics: first three sentences vs last three (orthogonal vectors)
    provider = MagicMock()
    provider.embed.return_value = [[1, 0]] * 3 + [[0, 1]] * 3

    out = proc._chunk_text_semantic(text, provider, max_chars=1000, min_chars=5)

    assert [c[0] for c in out] == ["Cat one. Cat two. Cat three.", "Stock a. Stock b. Stock c."]
    assert out[1][1] == text.index("Stock a.")


def test_semantic_chunking_size_break_splits_long_run():
    text = "Aaaa aaaa. Bbbb bbbb. Cccc cccc. Dddd dddd."
    provider = MagicMock()
    provider.embed.return_value = [[1, 0]] * 4  # no topic shift at all

    out = proc._chunk_text_semantic(text, provider, max_chars=15, min_chars=0)

    assert len(out) >= 2
    assert out[-1][2] == len(text)


def test_sentence_spans_skips_whitespace_only_pieces():
    spans = proc._sentence_spans("First.\n\nSecond one!  Third?")

    assert [("First.\n\nSecond one!  Third?"[s:e]) for s, e in spans] == [
        "First.",
        "Second one!",
        "Third?",
    ]


# ----------------------------------------------------------------- page map


def _page(number, *texts):
    return SimpleNamespace(
        page_number=number, text_blocks=[SimpleNamespace(text=t) for t in texts]
    )


def test_build_page_map_tracks_offsets_across_page_transitions():
    pages = [_page(1, "abc", "de"), _page(2, "fgh"), _page(3, "  ")]

    # "abc\n\nde\n\nfgh" -> page1 ends at 7, page2 ends at 12
    assert proc._build_page_map(pages) == [[7, 1], [12, 2]]


def test_build_page_map_empty_when_no_text():
    assert proc._build_page_map([_page(1, " ")]) == []


@pytest.mark.parametrize(
    "offset,expected", [(0, 1), (6, 1), (7, 2), (11, 2), (999, 2)]
)
def test_page_number_for_offset_bisects_and_clamps(offset, expected):
    assert proc._page_number_for_offset([[7, 1], [12, 2]], offset) == expected


@pytest.mark.parametrize("page_map", [None, []])
def test_page_number_for_offset_none_without_map(page_map):
    assert proc._page_number_for_offset(page_map, 3) is None


# -------------------------------------------------- collection / credentials


def test_resolve_collection_settings_uses_collection_values():
    coll = SimpleNamespace(
        embedding_model="m", chunk_max_tokens=10, chunk_min_tokens=2,
        chunk_overlap_tokens=1, chunk_strategy="semantic",
    )
    db = MagicMock()
    db.get.return_value = coll

    out = proc._resolve_collection_settings(db, SimpleNamespace(collection_id="c1"))

    assert out == ("m", 10, 2, 1, "semantic")


def test_resolve_collection_settings_defaults_strategy_to_size():
    coll = SimpleNamespace(
        embedding_model="m", chunk_max_tokens=10, chunk_min_tokens=2,
        chunk_overlap_tokens=1, chunk_strategy=None,
    )
    db = MagicMock()
    db.get.return_value = coll

    assert proc._resolve_collection_settings(db, SimpleNamespace(collection_id="c"))[4] == "size"


@pytest.mark.parametrize("collection_id,found", [(None, None), ("c1", None)])
def test_resolve_collection_settings_falls_back_to_global_defaults(collection_id, found):
    db = MagicMock()
    db.get.return_value = found

    out = proc._resolve_collection_settings(db, SimpleNamespace(collection_id=collection_id))

    assert out[0] == proc.settings.default_embedding_model
    assert out[4] == "size"


def _db_with_keys(project_key=None, user_key=None):
    """db.query(Model).filter_by(...).first() keyed by model class name."""
    db = MagicMock()

    def query(model):
        q = MagicMock()
        row = project_key if model.__name__ == "ProjectApiKey" else user_key
        q.filter_by.return_value.first.return_value = row
        return q

    db.query.side_effect = query
    return db


def test_resolve_vision_credentials_prefers_project_key():
    db = _db_with_keys(project_key=SimpleNamespace(encrypted_key="P"),
                       user_key=SimpleNamespace(encrypted_key="U"))
    db.get.return_value = SimpleNamespace(project_id="p1")
    doc = SimpleNamespace(collection_id="c1", created_by="u1")

    with patch("app.core.crypto.decrypt_secret", side_effect=lambda v: f"dec-{v}"):
        out = proc._resolve_vision_credentials(db, doc)

    assert out == {"vision_backend": "openai", "vision_api_key": "dec-P"}


def test_resolve_vision_credentials_falls_back_to_user_key():
    db = _db_with_keys(user_key=SimpleNamespace(encrypted_key="U"))
    db.get.return_value = None  # collection missing -> no project scope
    doc = SimpleNamespace(collection_id="c1", created_by="u1")

    with patch("app.core.crypto.decrypt_secret", return_value="plain"):
        out = proc._resolve_vision_credentials(db, doc)

    assert out == {"vision_backend": "openai", "vision_api_key": "plain"}


def test_resolve_vision_credentials_empty_when_no_keys():
    db = _db_with_keys()
    doc = SimpleNamespace(collection_id=None, created_by="u1")

    assert proc._resolve_vision_credentials(db, doc) == {}


# -------------------------------------------------------- figure recognition


def test_recognize_figure_text_uses_vlm_when_key_registered():
    provider = MagicMock()
    provider.generate_vision.return_value = "  차트 설명  "
    opts = {"vision_backend": "openai", "vision_api_key": "k"}

    with patch("app.services.llm.get_llm_provider", return_value=provider) as getter:
        out = proc._recognize_figure_text(b"png", opts)

    assert out == "차트 설명"
    assert getter.call_args.kwargs == {"api_key": "k"}


def test_recognize_figure_text_falls_back_to_tesseract_when_vlm_raises():
    opts = {"vision_backend": "openai", "vision_api_key": "k"}
    fake_tess = MagicMock()
    fake_tess.image_to_string.return_value = " ocr text \n"

    with patch("app.services.llm.get_llm_provider", side_effect=RuntimeError("boom")), \
         patch.dict("sys.modules", {"pytesseract": fake_tess}), \
         patch("app.pipeline.adapters.pdf_adapter._preprocess_for_ocr", side_effect=lambda i: i):
        out = proc._recognize_figure_text(_png(80, 80), opts)

    assert out == "ocr text"


def test_recognize_figure_text_returns_empty_when_everything_fails():
    # undecodable bytes -> PIL raises -> swallowed, "" returned
    assert proc._recognize_figure_text(b"not-an-image", {}) == ""


# ------------------------------------------------- _recognize_document_images


def _png(width, height, mode="RGB", noisy=True):
    import os

    from PIL import Image

    if noisy:
        channels = len(Image.new(mode, (1, 1)).getbands())
        img = Image.frombytes(mode, (width, height), os.urandom(width * height * channels))
    else:
        img = Image.new(mode, (width, height))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _parsed_with_images(*datas):
    regions = [RawImageRegion(page_number=1, bbox=(0, 0, 0, 0), image_bytes=d) for d in datas]
    page = RawPage(page_number=1, width=1, height=1, text_blocks=[], table_candidates=[],
                   image_regions=regions)
    return RawParsedDocument(format_id="x", page_count=1, pages=[page], metadata={}, warnings=[])


def test_recognize_document_images_filters_dedupes_and_stores():
    big = _png(100, 100)
    tiny_dim = _png(10, 10)
    parsed = _parsed_with_images(big, big, b"", b"x" * 10, b"y" * 5000, tiny_dim)
    storage = MagicMock()

    with patch("app.services.storage.storage_service", storage), \
         patch.object(proc, "_recognize_figure_text", return_value="그림에 담긴 충분히 긴 설명"):
        records = proc._recognize_document_images("doc-1", parsed, {})

    assert [r["storage_key"] for r in records] == ["images/doc-1/1.png"]
    storage.upload_file.assert_called_once()
    assert storage.upload_file.call_args.args[1] == "images/doc-1/1.png"
    figure_blocks = [b for b in parsed.pages[0].text_blocks if b.block_type == "image"]
    assert figure_blocks[0].text.startswith("[그림 1]\n그림에 담긴")


def test_recognize_document_images_short_text_not_merged_into_page():
    parsed = _parsed_with_images(_png(100, 100))

    with patch("app.services.storage.storage_service", MagicMock()), \
         patch.object(proc, "_recognize_figure_text", return_value="짧음"):
        records = proc._recognize_document_images("d", parsed, {})

    assert records[0]["text"] == "짧음"
    assert parsed.pages[0].text_blocks == []


def test_recognize_document_images_flattens_transparency_onto_white():
    rgba = _png(100, 100, mode="RGBA", noisy=False)
    # fully transparent RGBA compresses to < 3 KB, so pad the bytes via noise layer
    import os

    from PIL import Image

    img = Image.frombytes("RGBA", (120, 120), os.urandom(120 * 120 * 4))
    img.putalpha(0)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    parsed = _parsed_with_images(buf.getvalue() or rgba)
    storage = MagicMock()

    with patch("app.services.storage.storage_service", storage), \
         patch.object(proc, "_recognize_figure_text", return_value=""):
        proc._recognize_document_images("d", parsed, {})

    from PIL import Image as PILImage

    saved = PILImage.open(io.BytesIO(storage.upload_file.call_args.args[2]))
    assert saved.mode == "RGB"
    assert saved.getpixel((5, 5)) == (255, 255, 255)


def test_recognize_document_images_caps_candidate_count():
    datas = [_png(70, 70) for _ in range(proc._FIGURE_MAX_COUNT + 3)]
    parsed = _parsed_with_images(*datas)

    with patch("app.services.storage.storage_service", MagicMock()), \
         patch.object(proc, "_recognize_figure_text", return_value=""):
        records = proc._recognize_document_images("d", parsed, {})

    assert len(records) == proc._FIGURE_MAX_COUNT


# ------------------------------------------------------------ text cleaning


def test_clean_rag_text_strips_control_chars_and_normalizes_whitespace():
    raw = "a\x00b \t  c  \n\n\n\n d \x0b"

    assert proc._clean_rag_text(raw) == "ab c\n\nd"


def test_clean_rag_text_only_control_chars_becomes_empty():
    assert proc._clean_rag_text("\x00\x01 \x02") == ""


def test_normalize_ws_removes_all_whitespace():
    assert proc._normalize_ws(" a\tb \n c ") == "abc"


# ------------------------------------------------------- HWP repagination


def _hwp_parsed(blocks, tables=(), images=()):
    page = RawPage(
        page_number=1, width=595, height=842, text_blocks=list(blocks),
        table_candidates=list(tables), image_regions=list(images),
    )
    return RawParsedDocument(format_id="hwp", page_count=1, pages=[page], metadata={}, warnings=[])


def _repaginate(parsed, pages_text, preview_side_effect=None):
    doc = SimpleNamespace(filename="a.hwp", minio_key="k")
    with patch("app.services.preview_service.preview_url_for",
               side_effect=preview_side_effect) as preview, \
         patch("app.services.preview_service.pdf_pages_text_for", return_value=pages_text):
        proc._repaginate_hwp_like("doc-1", doc, parsed)
    return preview


def test_repaginate_noop_when_not_single_page():
    parsed = _hwp_parsed([RawTextBlock("a", 1)])
    parsed.pages.append(parsed.pages[0])

    preview = _repaginate(parsed, [])

    preview.assert_not_called()


def test_repaginate_noop_when_only_blank_blocks():
    parsed = _hwp_parsed([RawTextBlock("   ", 1)])

    preview = _repaginate(parsed, [])

    preview.assert_not_called()
    assert len(parsed.pages) == 1


def test_repaginate_keeps_single_page_when_preview_generation_fails():
    parsed = _hwp_parsed([RawTextBlock("본문", 1)])

    _repaginate(parsed, [{"page_number": 1, "text": "본문"}],
                preview_side_effect=RuntimeError("soffice missing"))

    assert [p.page_number for p in parsed.pages] == [1]
    assert parsed.pages[0].text_blocks[0].page_number == 1


def test_repaginate_noop_when_no_preview_pdf_text():
    parsed = _hwp_parsed([RawTextBlock("본문", 1)])

    _repaginate(parsed, None)

    assert parsed.page_count == 1


def test_repaginate_assigns_pages_tables_and_images():
    para_a = RawTextBlock("첫째 문단 내용입니다", 1)
    para_b = RawTextBlock("둘째 문단 내용입니다", 1)
    para_missing = RawTextBlock("PDF에 없는 문단", 1)
    table = RawTableCandidate(page_number=1, rows=[["셀A", "셀B"], ["셀C", "셀D"]])
    table_block = RawTextBlock("[표 1]\n셀A | 셀B\n셀C | 셀D", 1, block_type="table")
    image = RawImageRegion(page_number=1, bbox=(0, 0, 0, 0), image_bytes=b"i")
    parsed = _hwp_parsed([para_a, para_b, para_missing, table_block],
                         tables=[table], images=[image])
    pages_text = [
        {"page_number": 1, "text": "첫째 문단\n내용입니다"},
        {"page_number": 2, "text": "둘째 문단 내용입니다"},
        {"page_number": 3, "text": "셀A 셀B 셀C 셀D"},
    ]

    _repaginate(parsed, pages_text)

    assert [p.page_number for p in parsed.pages] == [1, 2, 3]
    assert parsed.page_count == 3
    assert para_a.page_number == 1 and para_b.page_number == 2
    # unmatched block stays on the current page (monotonic, never rewinds)
    assert para_missing.page_number == 2
    assert table.page_number == 3
    assert parsed.pages[2].table_candidates == [table]
    assert parsed.pages[0].image_regions == [image]


def test_repaginate_attaches_images_to_page_one_when_all_blocks_land_there():
    para = RawTextBlock("유일한 문단", 1)
    image = RawImageRegion(page_number=1, bbox=(0, 0, 0, 0), image_bytes=b"i")
    parsed = _hwp_parsed([para], images=[image])

    _repaginate(parsed, [{"page_number": 4, "text": "유일한 문단"}])

    assert [p.page_number for p in parsed.pages] == [4]
    assert parsed.pages[0].image_regions == [image]


# ------------------------------------------------------ continue_processing


def _doc(text="첫 문장입니다.\n\n둘째 문장입니다.", **over):
    doc = MagicMock()
    doc.parsed_text = text
    doc.page_map = [[len(text), 1]]
    doc.collection_id = None
    doc.original_filename = "f.txt"
    doc.tags = None
    doc.status = "PARSED"
    for k, v in over.items():
        setattr(doc, k, v)
    return doc


class _Harness:
    """Patches every external boundary continue_processing touches."""

    def __init__(self, doc, strategy="size", vectors=None, max_chars=30):
        self.db = MagicMock()
        self.db.get.return_value = doc
        self.stages: list[str] = []
        self.provider = MagicMock()
        self.provider.dimension = 3
        self.provider.embed.side_effect = vectors or (lambda t: [[0.1, 0.2, 0.3]] * len(t))
        self.qdrant = MagicMock()
        self.summary = MagicMock()
        self.metadata = MagicMock()
        self.fail_job = MagicMock()
        self.settings = ("model-x", max_chars, 0, 0, strategy)

    def _start(self, _db, _doc_id, stage):
        self.stages.append(stage)
        return f"job-{stage}"

    def run(self, document_id="d1", edited_text=None):
        with patch("app.db.session.get_sync_db", return_value=self.db), \
             patch("app.pipeline.job_tracker.start_job", side_effect=self._start), \
             patch("app.pipeline.job_tracker.complete_job"), \
             patch("app.pipeline.job_tracker.fail_job", self.fail_job), \
             patch("app.services.embedding.get_embedding_provider", return_value=self.provider), \
             patch("app.services.qdrant_service.qdrant_service", self.qdrant), \
             patch("app.pipeline.tasks.summary.generate_summary", self.summary), \
             patch("app.pipeline.tasks.metadata.extract_metadata", self.metadata), \
             patch.object(proc, "_resolve_collection_settings", return_value=self.settings):
            return proc.continue_processing.run(document_id, edited_text)


def test_continue_processing_not_found_returns_status_without_side_effects():
    h = _Harness(None)

    assert h.run() == {"document_id": "d1", "status": "NOT_FOUND"}
    assert h.stages == []
    h.db.close.assert_called_once()


def test_continue_processing_happy_path_indexes_and_triggers_followups():
    doc = _doc()
    h = _Harness(doc)

    result = h.run()

    assert result["status"] == "INDEXED"
    assert h.stages == ["CHUNK", "NORMALIZE", "EMBED", "UPLOAD"]
    assert doc.status == "INDEXED"
    points = h.qdrant.upsert_points.call_args.args[1]
    assert result["chunks"] == len(points) >= 1
    assert points[0]["payload"]["document_id"] == "d1"
    assert points[0]["payload"]["collection_id"] is None
    assert points[0]["payload"]["tags"] == []
    assert points[0]["payload"]["page_number"] == 1
    h.qdrant.init_collection.assert_called_once()
    h.qdrant.delete_by_document.assert_called_once()
    h.summary.delay.assert_called_once_with("d1")
    h.metadata.delay.assert_called_once_with("d1")


def test_continue_processing_deletes_old_vectors_before_upserting_new_ones():
    h = _Harness(_doc())
    order: list[str] = []
    h.qdrant.delete_by_document.side_effect = lambda *a: order.append("delete")
    h.qdrant.upsert_points.side_effect = lambda *a: order.append("upsert")

    h.run()

    assert order == ["delete", "upsert"]


def test_continue_processing_edited_text_replaces_text_and_clears_page_map():
    doc = _doc(text="old")
    h = _Harness(doc)

    h.run(edited_text="새로 편집된 본문입니다.")

    assert doc.parsed_text == "새로 편집된 본문입니다."
    points = h.qdrant.upsert_points.call_args.args[1]
    assert points[0]["payload"]["text"] == "새로 편집된 본문입니다."
    assert points[0]["payload"]["page_number"] is None


def test_continue_processing_empty_document_is_indexed_with_zero_chunks():
    doc = _doc(text="   ")
    h = _Harness(doc)

    result = h.run()

    assert result == {"document_id": "d1", "status": "INDEXED", "chunks": 0}
    assert h.stages == ["CHUNK", "NORMALIZE"]
    h.qdrant.upsert_points.assert_not_called()
    h.summary.delay.assert_called_once_with("d1")
    h.metadata.delay.assert_called_once_with("d1")


def test_continue_processing_drops_chunks_that_clean_to_empty():
    doc = _doc(text="\x01\x02\x03" * 20 + "\n\n" + "정상 텍스트 문단입니다.")
    h = _Harness(doc, max_chars=62)

    result = h.run()

    texts = [p["payload"]["text"] for p in h.qdrant.upsert_points.call_args.args[1]]
    assert all(t.strip() for t in texts)
    assert result["chunks"] == len(texts)


def test_continue_processing_semantic_strategy_uses_semantic_chunker():
    doc = _doc()
    h = _Harness(doc, strategy="semantic")

    with patch.object(proc, "_chunk_text_semantic",
                      return_value=[("의미 청크", 0, 5)]) as semantic, \
         patch.object(proc, "_chunk_text") as size:
        result = h.run()

    semantic.assert_called_once()
    size.assert_not_called()
    assert result["chunks"] == 1


def test_continue_processing_failure_marks_job_and_document_failed_then_retries():
    doc = _doc()
    h = _Harness(doc)
    h.provider.embed.side_effect = RuntimeError("gpu oom")

    with pytest.raises(RuntimeError, match="gpu oom"):
        h.run()

    h.fail_job.assert_called_once()
    assert h.fail_job.call_args.args[1] == "job-EMBED"
    assert doc.status == "FAILED"
    assert doc.error_message == "gpu oom"
    h.db.rollback.assert_called_once()
    h.qdrant.delete_by_document.assert_not_called()  # old index untouched on failure
    h.db.close.assert_called_once()


def test_continue_processing_truncates_error_message_to_500_chars():
    doc = _doc()
    h = _Harness(doc)
    h.provider.embed.side_effect = RuntimeError("e" * 900)

    with pytest.raises(RuntimeError):
        h.run()

    assert len(doc.error_message) == 500


def test_continue_processing_survives_failure_recording_error():
    doc = _doc()
    h = _Harness(doc)
    h.provider.embed.side_effect = RuntimeError("primary")
    h.fail_job.side_effect = RuntimeError("db gone")

    # the original error still surfaces, not the bookkeeping one
    with pytest.raises(RuntimeError, match="primary"):
        h.run()

    h.db.close.assert_called_once()
