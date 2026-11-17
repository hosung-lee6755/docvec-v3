"""모니터링 지표(전체 점검 2-8). 형식이 Prometheus 규칙을 지키는지, 지표를 아무나 읽지 못하는지 본다."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import admin
from app.services import metrics
from app.services.metrics import Metric, render


def test_render_writes_help_type_and_sorted_labels():
    text = render([Metric("docvec_documents", "상태별 문서 수", (({"status": "INDEXED"}, 15.0),))])

    assert text == (
        "# HELP docvec_documents 상태별 문서 수\n"
        "# TYPE docvec_documents gauge\n"
        'docvec_documents{status="INDEXED"} 15\n'
    )


def test_render_keeps_fractions_and_escapes_label_values():
    text = render([
        Metric("m_avg", "h", (({}, 1234.5678),)),
        Metric("m_label", "h", (({"name": 'a"b\\c'}, 1.0),)),
    ])

    assert "m_avg 1234.568\n" in text
    assert 'm_label{name="a\\"b\\\\c"} 1\n' in text


def test_render_metric_without_samples_still_declares_it():
    assert render([Metric("m", "h", ())]) == "# HELP m h\n# TYPE m gauge\n"


def test_queue_lengths_returns_none_when_redis_is_unreachable(monkeypatch):
    client = MagicMock()
    client.llen.side_effect = ConnectionError("down")
    monkeypatch.setattr("app.core.rate_limit._get_client", lambda: client)

    assert metrics._queue_lengths() is None


def test_queue_lengths_reads_every_queue(monkeypatch):
    client = MagicMock()
    client.llen.return_value = 3
    monkeypatch.setattr("app.core.rate_limit._get_client", lambda: client)

    assert metrics._queue_lengths() == dict.fromkeys(metrics.QUEUE_NAMES, 3)


@pytest.mark.asyncio
async def test_metrics_reject_request_without_credentials():
    with pytest.raises(HTTPException) as exc_info:
        await admin._authorize_metrics(request=MagicMock(), credentials=None, db=AsyncMock())

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_metrics_accept_scraper_token(monkeypatch):
    monkeypatch.setattr(admin.settings, "metrics_token", "scrape-secret")
    monkeypatch.setattr(admin, "get_current_user", AsyncMock(side_effect=AssertionError("must not be called")))

    await admin._authorize_metrics(
        request=MagicMock(), credentials=SimpleNamespace(credentials="scrape-secret"), db=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_metrics_reject_non_admin_user(monkeypatch):
    monkeypatch.setattr(admin.settings, "metrics_token", "scrape-secret")
    monkeypatch.setattr(admin, "get_current_user", AsyncMock(return_value=MagicMock(role="viewer")))

    with pytest.raises(HTTPException) as exc_info:
        await admin._authorize_metrics(
            request=MagicMock(), credentials=SimpleNamespace(credentials="user-jwt"), db=AsyncMock(),
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_metrics_without_configured_token_need_admin(monkeypatch):
    monkeypatch.setattr(admin.settings, "metrics_token", None)
    monkeypatch.setattr(admin, "get_current_user", AsyncMock(return_value=MagicMock(role="admin")))

    await admin._authorize_metrics(
        request=MagicMock(), credentials=SimpleNamespace(credentials=""), db=AsyncMock(),
    )
