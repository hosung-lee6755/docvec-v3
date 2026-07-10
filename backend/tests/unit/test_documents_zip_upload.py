"""Safety-net coverage for the bulk ZIP upload endpoint
(app.api.v1.endpoints.documents.upload_documents_zip) — path-traversal
flattening and the zip-bomb entry-count cap were verified manually via the
browser earlier this session but had no automated regression test."""

import io
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile

from app.api.v1.endpoints.documents import _ZIP_MAX_ENTRIES, upload_documents_zip


def _zip_upload_file(entries: dict[str, bytes]) -> UploadFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    buf.seek(0)
    return UploadFile(file=buf, filename="upload.zip")


@pytest.mark.asyncio
async def test_upload_zip_flattens_path_traversal_entries():
    """A zip entry named with directory-traversal components must be
    flattened to its bare filename before ever being used as a storage key
    or Document.filename — the whole point of the PurePosixPath(...).name
    defense."""
    upload = _zip_upload_file({"../../etc/evil.pdf": b"%PDF-1.4 fake content"})
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar.return_value = None  # no duplicate found

    with (
        patch("app.services.storage.storage_service.upload_file") as mock_upload,
        patch("app.pipeline.tasks.pipeline.create_processing_chain") as mock_chain,
    ):
        response = await upload_documents_zip(
            file=upload, collection_id=None, skip_review=False, db=db, current_user=MagicMock()
        )

    assert response["results"][0]["filename"] == "evil.pdf"
    assert response["results"][0]["status"] == "queued"
    mock_chain.return_value.delay.assert_called_once()
    stored_key = mock_upload.call_args[0][1]
    assert ".." not in stored_key
    added_doc = db.add.call_args[0][0]
    assert added_doc.filename == "evil.pdf"
    assert added_doc.original_filename == "evil.pdf"


@pytest.mark.asyncio
async def test_upload_zip_rejects_too_many_entries():
    entries = {f"file-{i}.pdf": b"content" for i in range(_ZIP_MAX_ENTRIES + 1)}
    upload = _zip_upload_file(entries)
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await upload_documents_zip(
            file=upload, collection_id=None, skip_review=False, db=db, current_user=MagicMock()
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_upload_zip_skips_unsupported_extensions():
    upload = _zip_upload_file({"notes.txt": b"just text"})
    db = AsyncMock()
    db.add = MagicMock()

    with (
        patch("app.services.storage.storage_service.upload_file"),
        patch("app.pipeline.tasks.pipeline.create_processing_chain"),
    ):
        response = await upload_documents_zip(
            file=upload, collection_id=None, skip_review=False, db=db, current_user=MagicMock()
        )

    assert response["results"][0]["status"] == "skipped"
    db.add.assert_not_called()
