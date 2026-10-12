"""extract_metadata 보강 — 빈 문자열 한자 비율과 실패 상태 기록 자체가 실패하는 경로."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.tasks import metadata


@pytest.mark.parametrize("text,expected", [("", 0.0), (" \n", 0.0), ("漢字", 1.0), ("한漢", 0.5)])
def test_han_ratio(text, expected):
    assert metadata._han_ratio(text) == expected


def test_extract_metadata_survives_failure_state_recording_error():
    doc = SimpleNamespace(parsed_text="본문", tags=None, suggested_tags=None,
                          metadata_status="PENDING")
    db = MagicMock()
    db.get.side_effect = [doc, RuntimeError("db gone")]
    provider = MagicMock()
    provider.generate.side_effect = RuntimeError("model oom")

    with patch("app.db.session.get_sync_db", return_value=db), \
         patch("app.services.llm.get_llm_provider", return_value=provider):
        result = metadata.extract_metadata("d1")

    assert result == {"document_id": "d1", "status": "FAILED", "error": "model oom"}
    db.rollback.assert_called_once()
    db.close.assert_called_once()
