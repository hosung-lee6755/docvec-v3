"""dictionary.py 보강 — 저장 충돌(409), 영향 문서 미리보기, 버전 이력, 엑셀 행 변환 헬퍼."""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import dictionary as dict_api
from app.db.models.dictionary_application import DictionaryApplication
from app.db.models.dictionary_entry import DictionaryEntry
from app.db.models.dictionary_revision import DictionaryRevision
from app.schemas.dictionary import DictionaryEntryCreate, DictionaryEntryUpdate
from tests.unit._docs_api_support import (
    OWNER_ID,
    add_step,
    admin_user,
    assert_http_error,
    doc_with_run,
    owner_user,
)
from tests.unit._docs_api_support import db_session  # noqa: F401


# ------------------------------------------------------------- 409 conflicts
async def test_create_entry_maps_commit_failure_to_409_after_rollback():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit.side_effect = RuntimeError("duplicate key value violates unique constraint")

    with pytest.raises(HTTPException) as exc_info:
        await dict_api.create_dictionary_entry(DictionaryEntryCreate(entry_type="stopword", term="검토"), db, admin_user())

    assert exc_info.value.status_code == 409
    assert "duplicate key" not in exc_info.value.detail  # 내부 DB 오류는 노출하지 않는다
    db.rollback.assert_awaited_once()


async def test_update_entry_maps_commit_failure_to_409_after_rollback():
    entry = MagicMock(id=uuid4(), variants=[])
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar.return_value = entry
    db.commit.side_effect = RuntimeError("unique violation")

    with pytest.raises(HTTPException) as exc_info:
        await dict_api.update_dictionary_entry(entry.id, DictionaryEntryUpdate(term="새 용어"), db, admin_user())

    assert exc_info.value.status_code == 409
    db.rollback.assert_awaited_once()


# ------------------------------------------------------------------ impact
async def _entry(db) -> DictionaryEntry:
    entry = DictionaryEntry(id=uuid4(), entry_type="synonym", term="AI", created_by=OWNER_ID, scope=["ALL"])
    db.add(entry)
    await db.flush()
    return entry


def _application(doc, run, step, entry, reverted: bool) -> DictionaryApplication:
    return DictionaryApplication(
        id=uuid4(), run_id=run.id, step_id=step.id, document_id=doc.id, dictionary_type="SYNONYM",
        entry_id=entry.id, dictionary_version=1, original_text="AI", normalized_text="인공지능", reverted=reverted,
    )


async def test_impact_lists_distinct_documents_with_unreverted_applications(db_session):  # noqa: F811
    entry = await _entry(db_session)
    applied, run = await doc_with_run(db_session, "dict-applied", original_filename="적용.pdf")
    step = await add_step(db_session, run)
    reverted_doc, reverted_run = await doc_with_run(db_session, "dict-reverted", original_filename="취소.pdf")
    reverted_step = await add_step(db_session, reverted_run)
    # 같은 문서에 두 번 적용돼도 한 건으로 센다
    db_session.add_all([
        _application(applied, run, step, entry, reverted=False),
        _application(applied, run, step, entry, reverted=False),
        _application(reverted_doc, reverted_run, reverted_step, entry, reverted=True),
    ])
    await db_session.flush()

    result = await dict_api.get_dictionary_entry_impact(entry.id, db_session, admin_user())

    assert result.affected_document_count == 1
    assert [(d.id, d.filename) for d in result.documents] == [(applied.id, "적용.pdf")]


async def test_impact_and_revisions_require_admin(db_session):  # noqa: F811
    await assert_http_error(dict_api.get_dictionary_entry_impact(uuid4(), db_session, owner_user()), 403)
    await assert_http_error(dict_api.list_dictionary_revisions(db_session, owner_user()), 403)


async def test_impact_for_unused_entry_is_empty(db_session):  # noqa: F811
    result = await dict_api.get_dictionary_entry_impact(uuid4(), db_session, admin_user())

    assert (result.affected_document_count, result.documents) == (0, [])


# --------------------------------------------------------------- revisions
async def test_revisions_show_newest_first_with_entry_and_author_names(db_session):  # noqa: F811
    entry = await _entry(db_session)
    for change_type, entry_id in (("CREATE", entry.id), ("UPDATE", entry.id), ("DELETE", None)):
        db_session.add(
            DictionaryRevision(changed_entry_id=entry_id, change_type=change_type, created_by=OWNER_ID, created_at=datetime.utcnow())
        )
        await db_session.flush()

    result = await dict_api.list_dictionary_revisions(db_session, admin_user())

    revisions = result.revisions
    assert [r.change_type for r in revisions[:3]] == ["DELETE", "UPDATE", "CREATE"]
    assert revisions[0].version > revisions[1].version > revisions[2].version
    assert (revisions[1].entry_term, revisions[1].entry_type, revisions[1].created_by_name) == ("AI", "synonym", "owner")
    assert (revisions[0].entry_term, revisions[0].entry_type) == (None, None)  # 삭제된 항목은 이름 없이 이력만 남는다


# -------------------------------------------------- 엑셀 변환 헬퍼(순수 함수)
def test_yn_helpers_round_trip_and_defaults():
    assert (dict_api._bool_to_yn(True), dict_api._bool_to_yn(False)) == ("Y", "N")
    assert [dict_api._yn_to_bool(v) for v in ("y", " TRUE ", "1", "yes", "n", "0")] == [True, True, True, True, False, False]
    assert dict_api._yn_to_bool(None, default=True) is True
    assert dict_api._yn_to_bool("   ", default=True) is True
    assert dict_api._yn_to_bool("", default=False) is False


def test_list_helpers_split_join_and_default():
    assert dict_api._join_list(["a", "b"], ";") == "a;b"
    assert dict_api._join_list([], ";") == ""
    assert dict_api._split_list(" a ; ;b", ";") == ["a", "b"]
    assert dict_api._split_list(None, ",", ["ALL"]) == ["ALL"]
    assert dict_api._split_list("", ",") == []


def test_cell_handles_short_rows_blank_and_non_string_values():
    assert dict_api._cell((), 0) is None
    assert dict_api._cell(("a",), 3) is None
    assert dict_api._cell((None,), 0) is None
    assert dict_api._cell(("  ",), 0) is None
    assert dict_api._cell((12,), 0) == "12"


def _stub_entry(**kwargs) -> MagicMock:
    defaults = dict(
        term="용어", match_type=None, direction=None, processing_mode=None, term_type=None, processing_rule=None,
        pronunciation=None, case_sensitive=True, language="ko", scope=None, description=None, enabled=False,
        variants=[MagicMock(variant_term="a"), MagicMock(variant_term="b")],
    )
    defaults.update(kwargs)
    return MagicMock(**defaults)


def test_export_row_layout_per_entry_type_with_defaults():
    assert dict_api._export_row("stopword", _stub_entry()) == ["용어", "EXACT", "Y", "ko", "", "", "N"]
    assert dict_api._export_row("synonym", _stub_entry(scope=["ALL", "X"])) == [
        "용어", "a;b", "ONE_WAY", "NORMALIZE", "Y", "ko", "ALL,X", "N",
    ]
    assert dict_api._export_row("custom_word", _stub_entry(description="설명", pronunciation="yong")) == [
        "용어", "a;b", "CUSTOM", "KEEP", "설명", "Y", "ko", "", "N", "yong",
    ]


def test_parse_import_row_applies_defaults_and_skips_unusable_rows():
    assert dict_api._parse_import_row("stopword", (None,)) is None
    assert dict_api._parse_import_row("synonym", ("AI", None)) is None  # 변형어 없는 동의어는 의미 없음
    assert dict_api._parse_import_row("synonym", (None, "x")) is None
    assert dict_api._parse_import_row("custom_word", ()) is None

    stop = dict_api._parse_import_row("stopword", ("검토", "regex"))
    assert (stop["match_type"], stop["scope"], stop["enabled"], stop["language"]) == ("REGEX", ["ALL"], True, "ko")

    syn = dict_api._parse_import_row("synonym", ("AI", "인공지능; 에이아이", "bidirectional", None, "Y", "en", "A,B", "N"))
    assert syn["variants"] == ["인공지능", "에이아이"] and syn["direction"] == "BIDIRECTIONAL"
    assert (syn["processing_mode"], syn["case_sensitive"], syn["scope"], syn["enabled"]) == ("NORMALIZE", True, ["A", "B"], False)

    word = dict_api._parse_import_row("custom_word", ("한컴", None, "brand", None, "메모", None, None, None, None))
    assert (word["term_type"], word["processing_rule"], word["variants"], word["description"]) == ("BRAND", "KEEP", [], "메모")
