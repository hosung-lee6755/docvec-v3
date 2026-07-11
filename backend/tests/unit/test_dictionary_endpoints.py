"""Access-control and CRUD coverage for the admin-only dictionary endpoints —
a non-admin must never manage the shared stopword/synonym/custom-word
dictionary used by BM25 tokenization. Column layouts for export/import follow
문서_처리_사전_스키마.md §6 and differ per entry_type."""

import io
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from openpyxl import Workbook, load_workbook

from app.api.v1.endpoints.dictionary import (
    create_dictionary_entry,
    delete_dictionary_entry,
    export_dictionary_entries,
    import_dictionary_entries,
    list_dictionary_entries,
    update_dictionary_entry,
)
from app.schemas.dictionary import DictionaryEntryCreate, DictionaryEntryUpdate


def _entry(**kwargs):
    defaults = dict(
        id=uuid4(), entry_type="stopword", term="검토", variants=[],
        match_type="EXACT", direction=None, processing_mode=None,
        term_type=None, processing_rule=None, pronunciation=None,
        case_sensitive=False, language="ko", scope=["ALL"], description=None,
        enabled=True,
    )
    defaults.update(kwargs)
    entry = MagicMock(**defaults)
    entry.variants = [MagicMock(variant_term=v) for v in kwargs.get("variants", [])]
    return entry


def _xlsx_upload(header: list[str], rows: list[tuple]) -> MagicMock:
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for row in rows:
        ws.append(list(row))
    buffer = io.BytesIO()
    wb.save(buffer)

    upload = MagicMock()
    upload.read = AsyncMock(return_value=buffer.getvalue())
    return upload


@pytest.mark.asyncio
async def test_create_rejects_non_admin():
    db = AsyncMock()
    non_admin = MagicMock(role="editor")
    data = DictionaryEntryCreate(entry_type="stopword", term="검토")

    with pytest.raises(HTTPException) as exc_info:
        await create_dictionary_entry(data, db=db, current_user=non_admin)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_list_rejects_non_admin():
    db = AsyncMock()
    non_admin = MagicMock(role="viewer")

    with pytest.raises(HTTPException) as exc_info:
        await list_dictionary_entries(current_user=non_admin, db=db)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_update_rejects_non_admin():
    db = AsyncMock()
    non_admin = MagicMock(role="editor")

    with pytest.raises(HTTPException) as exc_info:
        await update_dictionary_entry(
            uuid4(), DictionaryEntryUpdate(), db=db, current_user=non_admin
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_delete_rejects_non_admin():
    db = AsyncMock()
    non_admin = MagicMock(role="editor")

    with pytest.raises(HTTPException) as exc_info:
        await delete_dictionary_entry(uuid4(), db=db, current_user=non_admin)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_create_admin_persists_synonym_with_variants():
    db = AsyncMock()
    db.add = MagicMock()

    async def _fake_refresh(entry, attribute_names=None):
        entry.id = entry.id or uuid4()
        entry.created_at = entry.created_at or datetime.now(timezone.utc)
        entry.updated_at = entry.updated_at or entry.created_at

    db.refresh = AsyncMock(side_effect=_fake_refresh)
    admin = MagicMock(role="admin", id=uuid4())
    data = DictionaryEntryCreate(entry_type="synonym", term="인공지능", variants=["AI", "인공 지능"])

    with patch(
        "app.api.v1.endpoints.dictionary.refresh_dictionary_cache", new=AsyncMock()
    ) as mock_refresh:
        result = await create_dictionary_entry(data, db=db, current_user=admin)

    db.add.assert_called_once()
    db.commit.assert_awaited_once()
    mock_refresh.assert_awaited_once_with(db)
    assert result.entry_type == "synonym"
    assert result.term == "인공지능"
    assert result.variants == ["AI", "인공 지능"]
    assert result.direction == "ONE_WAY"
    assert result.processing_mode == "NORMALIZE"


@pytest.mark.asyncio
async def test_create_synonym_without_variants_rejected_by_schema():
    with pytest.raises(ValueError):
        DictionaryEntryCreate(entry_type="synonym", term="인공지능")


@pytest.mark.asyncio
async def test_update_admin_replaces_variants_and_toggles_enabled():
    db = AsyncMock()
    entry = _entry(entry_type="synonym", term="인공지능", variants=["AI"])
    db.scalar.return_value = entry
    admin = MagicMock(role="admin")

    with patch("app.api.v1.endpoints.dictionary.refresh_dictionary_cache", new=AsyncMock()):
        result = await update_dictionary_entry(
            uuid4(),
            DictionaryEntryUpdate(variants=["AI", "Artificial Intelligence"], enabled=False),
            db=db,
            current_user=admin,
        )

    assert result.enabled is False
    assert result.variants == ["AI", "Artificial Intelligence"]
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_404_when_entry_missing():
    db = AsyncMock()
    db.scalar.return_value = None
    admin = MagicMock(role="admin")

    with pytest.raises(HTTPException) as exc_info:
        await update_dictionary_entry(
            uuid4(), DictionaryEntryUpdate(enabled=False), db=db, current_user=admin
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_admin_404_when_entry_missing():
    db = AsyncMock()
    db.scalar.return_value = None
    admin = MagicMock(role="admin")

    with pytest.raises(HTTPException) as exc_info:
        await delete_dictionary_entry(uuid4(), db=db, current_user=admin)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_admin_removes_entry_and_refreshes_cache():
    db = AsyncMock()
    existing = MagicMock()
    db.scalar.return_value = existing
    admin = MagicMock(role="admin")

    with patch(
        "app.api.v1.endpoints.dictionary.refresh_dictionary_cache", new=AsyncMock()
    ) as mock_refresh:
        await delete_dictionary_entry(uuid4(), db=db, current_user=admin)

    db.delete.assert_awaited_once_with(existing)
    db.commit.assert_awaited_once()
    mock_refresh.assert_awaited_once_with(db)


@pytest.mark.asyncio
async def test_list_admin_filters_by_entry_type():
    db = AsyncMock()
    db.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
    admin = MagicMock(role="admin")

    result = await list_dictionary_entries(entry_type="stopword", current_user=admin, db=db)

    assert result == {"items": []}


@pytest.mark.asyncio
async def test_export_rejects_non_admin():
    db = AsyncMock()
    non_admin = MagicMock(role="viewer")

    with pytest.raises(HTTPException) as exc_info:
        await export_dictionary_entries(entry_type="stopword", db=db, current_user=non_admin)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_export_stopword_matches_schema_doc_columns():
    db = AsyncMock()
    db.scalars.return_value = MagicMock(
        all=MagicMock(return_value=[
            _entry(term="그리고", match_type="EXACT", description="접속사", enabled=True)
        ])
    )
    admin = MagicMock(role="admin")

    response = await export_dictionary_entries(entry_type="stopword", db=db, current_user=admin)
    body = b"".join([chunk async for chunk in response.body_iterator])
    ws = load_workbook(io.BytesIO(body)).active

    assert [c.value for c in ws[1]] == ["단어", "일치방식", "대소문자구분", "언어", "적용범위", "제외사유", "사용여부"]
    assert [c.value for c in ws[2]] == ["그리고", "EXACT", "N", "ko", "ALL", "접속사", "Y"]


@pytest.mark.asyncio
async def test_export_synonym_joins_variants_with_semicolon():
    db = AsyncMock()
    db.scalars.return_value = MagicMock(
        all=MagicMock(return_value=[
            _entry(
                entry_type="synonym", term="인공지능", variants=["AI", "인공 지능"],
                direction="ONE_WAY", processing_mode="NORMALIZE", enabled=True,
            )
        ])
    )
    admin = MagicMock(role="admin")

    response = await export_dictionary_entries(entry_type="synonym", db=db, current_user=admin)
    body = b"".join([chunk async for chunk in response.body_iterator])
    ws = load_workbook(io.BytesIO(body)).active

    assert [c.value for c in ws[2]] == [
        "인공지능", "AI;인공 지능", "ONE_WAY", "NORMALIZE", "N", "ko", "ALL", "Y",
    ]


@pytest.mark.asyncio
async def test_export_includes_schema_guide_sheet_without_shifting_active_sheet():
    db = AsyncMock()
    db.scalars.return_value = MagicMock(
        all=MagicMock(return_value=[_entry(term="그리고")])
    )
    admin = MagicMock(role="admin")

    response = await export_dictionary_entries(entry_type="stopword", db=db, current_user=admin)
    body = b"".join([chunk async for chunk in response.body_iterator])
    wb = load_workbook(io.BytesIO(body))

    assert wb.sheetnames == ["stopword", "스키마 안내"]
    assert wb.active.title == "stopword"  # import_dictionary_entries relies on this staying the data sheet

    guide = wb["스키마 안내"]
    assert guide["A2"].value == "컬럼명"
    row3_values = tuple(c.value for c in guide[3])[:5]
    assert row3_values == ("단어", "제외할 단어 또는 표현", "필수", "텍스트", "그리고")


@pytest.mark.asyncio
async def test_import_rejects_non_admin():
    db = AsyncMock()
    non_admin = MagicMock(role="editor")
    upload = _xlsx_upload(["단어", "일치방식", "대소문자구분", "언어", "적용범위", "제외사유", "사용여부"], [])

    with pytest.raises(HTTPException) as exc_info:
        await import_dictionary_entries(
            entry_type="stopword", file=upload, db=db, current_user=non_admin
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_import_rejects_non_xlsx_file():
    db = AsyncMock()
    admin = MagicMock(role="admin")
    bad_file = MagicMock()
    bad_file.read = AsyncMock(return_value=b"not an xlsx file")

    with pytest.raises(HTTPException) as exc_info:
        await import_dictionary_entries(
            entry_type="stopword", file=bad_file, db=db, current_user=admin
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_import_stopword_creates_updates_and_skips_blank_term():
    db = AsyncMock()
    db.add = MagicMock()
    existing_entry = _entry(term="검토")
    db.scalars.return_value = MagicMock(all=MagicMock(return_value=[existing_entry]))
    admin = MagicMock(role="admin", id=uuid4())

    upload = _xlsx_upload(
        ["단어", "일치방식", "대소문자구분", "언어", "적용범위", "제외사유", "사용여부"],
        [
            ("검토", "CONTAINS", "N", "ko", "ALL", "갱신됨", "Y"),  # update
            ("그리고", "EXACT", "N", "ko", "ALL", "접속사", "Y"),  # create
            ("", "", "", "", "", "", ""),  # blank — not reported
            ("", "EXACT", "", "", "", "제외사유만있음", ""),  # skipped — no term
        ],
    )

    with patch(
        "app.api.v1.endpoints.dictionary.refresh_dictionary_cache", new=AsyncMock()
    ) as mock_refresh:
        result = await import_dictionary_entries(
            entry_type="stopword", file=upload, db=db, current_user=admin
        )

    assert result.created == 1
    assert result.updated == 1
    assert result.skipped == 1
    assert result.skipped_rows == [5]
    assert existing_entry.match_type == "CONTAINS"
    assert existing_entry.description == "갱신됨"
    db.add.assert_called_once()
    db.commit.assert_awaited_once()
    mock_refresh.assert_awaited_once_with(db)


@pytest.mark.asyncio
async def test_import_synonym_requires_variants_or_skips():
    db = AsyncMock()
    db.add = MagicMock()
    db.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
    admin = MagicMock(role="admin", id=uuid4())

    upload = _xlsx_upload(
        ["대표용어", "동의어", "적용방향", "처리방식", "대소문자구분", "언어", "적용범위", "사용여부"],
        [
            ("전세", "", "ONE_WAY", "NORMALIZE", "N", "ko", "ALL", "Y"),  # skipped — no variants
            ("인공지능", "AI;인공 지능", "ONE_WAY", "NORMALIZE", "N", "ko", "ALL", "Y"),  # created
        ],
    )

    with patch("app.api.v1.endpoints.dictionary.refresh_dictionary_cache", new=AsyncMock()):
        result = await import_dictionary_entries(
            entry_type="synonym", file=upload, db=db, current_user=admin
        )

    assert result.created == 1
    assert result.skipped == 1
    assert result.skipped_rows == [2]


@pytest.mark.asyncio
async def test_import_custom_word_parses_all_columns():
    db = AsyncMock()
    db.add = MagicMock()
    db.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
    admin = MagicMock(role="admin", id=uuid4())

    upload = _xlsx_upload(
        ["표준용어", "변형표현", "용어유형", "처리규칙", "정의", "대소문자구분", "언어", "적용범위", "사용여부", "발음"],
        [
            (
                "LangGraph", "랭그래프;Lang Graph", "PRODUCT", "KEEP",
                "AI 워크플로우 프레임워크", "Y", "en", "기술설계서", "Y", "랭그래프",
            ),
        ],
    )

    with patch("app.api.v1.endpoints.dictionary.refresh_dictionary_cache", new=AsyncMock()):
        result = await import_dictionary_entries(
            entry_type="custom_word", file=upload, db=db, current_user=admin
        )

    assert result.created == 1
    created_entry = db.add.call_args[0][0]
    assert created_entry.term == "LangGraph"
    assert [v.variant_term for v in created_entry.variants] == ["랭그래프", "Lang Graph"]
    assert created_entry.term_type == "PRODUCT"
    assert created_entry.processing_rule == "KEEP"
    assert created_entry.case_sensitive is True
    assert created_entry.language == "en"
    assert created_entry.scope == ["기술설계서"]
    assert created_entry.pronunciation == "랭그래프"


@pytest.mark.asyncio
async def test_import_rejects_more_than_max_rows():
    db = AsyncMock()
    admin = MagicMock(role="admin")
    upload = _xlsx_upload(
        ["단어", "일치방식", "대소문자구분", "언어", "적용범위", "제외사유", "사용여부"],
        [(f"단어{i}", "EXACT", "N", "ko", "ALL", "", "Y") for i in range(15)],
    )

    with patch("app.api.v1.endpoints.dictionary._MAX_IMPORT_ROWS", 10):
        with pytest.raises(HTTPException) as exc_info:
            await import_dictionary_entries(
                entry_type="stopword", file=upload, db=db, current_user=admin
            )

    assert exc_info.value.status_code == 400
