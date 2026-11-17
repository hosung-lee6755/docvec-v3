"""GET /documents/{id}/chunks/{chunk_id}/context — 쪽 그림이 없는 형식의 인용 위치 보기."""
from uuid import uuid4

from app.api.v1.endpoints.documents import chunks as chunks_api
from app.db.models.document_chunk import DocumentChunk
from app.db.models.document_revision import NORMALIZED_REVISION_SOURCE, DocumentTextRevision
from tests.unit._docs_api_support import (
    add_doc,
    assert_http_error,
    doc_with_run,
    owner_user,
    stranger_user,
)
from tests.unit._docs_api_support import db_session  # noqa: F401

NORMALIZED = "첫 절 내용입니다. 인용된 문장입니다. 마지막 내용입니다."
RAW = "주민번호 900101-1234567 가 있는 원문. 인용된 문장입니다."


async def _chunk(db, doc, run, **fields) -> DocumentChunk:
    start = NORMALIZED.index("인용된")
    base = dict(
        id=uuid4(), document_id=doc.id, run_id=run.id, chunk_order=0, chunk_text="인용된 문장입니다.",
        original_text="인용된 문장입니다.", span_start=start, span_end=start + len("인용된 문장입니다."),
        page_start=3, page_end=4, section_path=["2장 운영", "2.1 백업"],
    )
    chunk = DocumentChunk(**{**base, **fields})
    db.add(chunk)
    await db.flush()
    return chunk


async def _normalized(db, doc, text=NORMALIZED, source=NORMALIZED_REVISION_SOURCE):
    db.add(DocumentTextRevision(document_id=doc.id, source=source, parsed_text=text))
    await db.flush()


async def test_context_returns_text_around_chunk_with_section_path(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "ctx-ok", parsed_text=RAW)
    await _normalized(db_session, doc)
    chunk = await _chunk(db_session, doc, run)

    result = await chunks_api.get_chunk_context(doc.id, chunk.id, db_session, owner_user())

    assert result["located"] is True
    assert result["text"] == "인용된 문장입니다."
    assert result["before"] == "첫 절 내용입니다. " and result["after"] == " 마지막 내용입니다."
    assert result["section_path"] == ["2장 운영", "2.1 백업"]
    assert (result["page_start"], result["page_end"]) == (3, 4)


async def test_context_never_reads_unmasked_parsed_text(db_session):  # noqa: F811
    # 개인정보 마스킹 전의 parsed_text에는 주민번호가 있다. 마스킹된 NORMALIZED 글만 써야 한다
    doc, run = await doc_with_run(db_session, "ctx-pii", parsed_text=RAW)
    chunk = await _chunk(db_session, doc, run)  # NORMALIZED 스냅샷 없음

    result = await chunks_api.get_chunk_context(doc.id, chunk.id, db_session, owner_user())

    assert result["located"] is False and result["before"] == "" and result["after"] == ""
    assert "900101" not in str(result)


async def test_context_ignores_other_snapshot_sources(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "ctx-src")
    await _normalized(db_session, doc, RAW, source="PARSE")
    chunk = await _chunk(db_session, doc, run)

    result = await chunks_api.get_chunk_context(doc.id, chunk.id, db_session, owner_user())

    assert result["located"] is False and "900101" not in str(result)


async def test_context_uses_the_latest_normalized_snapshot(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "ctx-latest")
    await _normalized(db_session, doc, "오래된 글")
    await _normalized(db_session, doc)
    chunk = await _chunk(db_session, doc, run)

    result = await chunks_api.get_chunk_context(doc.id, chunk.id, db_session, owner_user())

    assert result["located"] is True and result["before"] == "첫 절 내용입니다. "


async def test_context_404_for_unknown_chunk_or_other_documents_chunk(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "ctx-404")
    other = await add_doc(db_session, "ctx-404-other")
    chunk = await _chunk(db_session, doc, run)

    await assert_http_error(chunks_api.get_chunk_context(doc.id, uuid4(), db_session, owner_user()), 404)
    await assert_http_error(chunks_api.get_chunk_context(other.id, chunk.id, db_session, owner_user()), 404)
    await assert_http_error(chunks_api.get_chunk_context(uuid4(), chunk.id, db_session, owner_user()), 404)


async def test_context_requires_document_access(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "ctx-403")
    await _normalized(db_session, doc)
    chunk = await _chunk(db_session, doc, run)

    await assert_http_error(chunks_api.get_chunk_context(doc.id, chunk.id, db_session, stranger_user()), 403)
