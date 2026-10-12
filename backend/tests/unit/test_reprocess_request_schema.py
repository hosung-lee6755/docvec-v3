"""DocumentReprocessRequest.use_latest_version 입력 검증."""
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.document import DocumentReprocessRequest


def test_use_latest_version_defaults_to_false():
    assert DocumentReprocessRequest(start_block_type="file_validate").use_latest_version is False


def test_use_latest_version_accepts_start_block_type():
    body = DocumentReprocessRequest(start_block_type="file_validate", use_latest_version=True)
    assert body.use_latest_version is True


def test_use_latest_version_rejects_specific_block_instance():
    with pytest.raises(ValidationError):
        DocumentReprocessRequest(start_block_instance_id=uuid4(), use_latest_version=True)


def test_use_latest_version_rejects_edited_text():
    with pytest.raises(ValidationError):
        DocumentReprocessRequest(edited_text="x", use_latest_version=True)
