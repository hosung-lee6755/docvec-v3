"""v3 마일스톤 2 — AI 기본법 대응 근거 자료(docx).

집계는 기간으로 거르므로, 다른 테스트가 남긴 데이터와 섞이지 않게 2001년 기간에만 데이터를 둔다.
기간과 무관한 전체 집계(보안등급별 문서 수)는 데이터 추가 전후의 차이로 검증한다.
"""
import io
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from docx import Document as DocxDocument
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.endpoints import governance as governance_api
from app.db.models.answer_trace import AnswerTrace, AnswerTraceSource
from app.db.models.audit_log import AuditLog
from app.services.governance_report import (
    DISCLAIMER,
    LEGAL_REVIEW,
    SECTIONS,
    collect_governance_data,
    render_governance_docx,
)
from tests.unit.api_pg_helpers import (  # noqa: F401
    db_session,
    make_collection,
    make_document,
    make_user,
)

pytestmark = pytest.mark.asyncio

START = datetime(2001, 1, 1, tzinfo=timezone.utc)
END = datetime(2001, 12, 31, tzinfo=timezone.utc)
AT = datetime(2001, 6, 1, 9, 0, tzinfo=timezone.utc)


def _trace(user, **fields) -> AnswerTrace:
    base = dict(
        id=str(uuid4()), user_id=str(user.id), username=user.username, query="질문",
        status="DONE", grounding="passed", model_key="qwen2.5-3b", latency_ms=100, created_at=AT,
    )
    return AnswerTrace(**{**base, **fields})


@pytest.fixture
async def world(db_session):  # noqa: F811
    db = db_session
    admin = await make_user(db, "admin", username="admin")
    asker = await make_user(db, "viewer", username="asker")
    cited = _trace(asker)
    db.add_all([
        cited,
        _trace(asker, grounding="failed", broadened=True, query="근거 부족 질문", latency_ms=300),
        _trace(asker, cache_hit=True, grounding=None),
        _trace(asker, status="FAILED", grounding=None, latency_ms=None),
        _trace(asker, created_at=datetime(2002, 1, 5, tzinfo=timezone.utc)),  # 기간 밖
    ])
    await db.flush()
    db.add(AnswerTraceSource(trace_id=cited.id, rank=1, source_kind="chunk", text_sha256="0" * 64,
                             cited=True))
    for action in ("document.acl_update", "document.acl_update", "document.preview"):
        db.add(AuditLog(user_id=str(admin.id), action=action, created_at=AT))
    await db.commit()
    return dict(db=db, admin=admin, asker=asker)


async def test_collects_period_figures(world):
    data = await collect_governance_data(world["db"], START, END, "admin")

    assert data.answers == 4
    assert (data.failed_answers, data.broadened, data.cache_hits) == (1, 1, 1)
    assert data.grounding == {"passed": 1, "failed": 1}
    assert data.answers_without_citation == 2  # DONE 3건 중 인용이 있는 1건 제외
    assert data.avg_latency_ms == 166  # (100 + 300 + 100) / 3
    assert data.answers_by_model == {"qwen2.5-3b": 4}
    assert data.permission_changes == {"document.acl_update": 2}
    assert data.access_audits == {"document.preview": 1}
    assert data.admin_actions.get("document.acl_update") == 2
    assert "document.preview" not in data.admin_actions
    assert [(who, q) for _, who, q in data.ungrounded_samples] == [("asker", "근거 부족 질문")]


async def test_documents_by_effective_level(world):
    db = world["db"]
    before = (await collect_governance_data(db, START, END, "admin")).documents_by_level
    col = await make_collection(db, world["admin"], default_security_level="Internal")
    await make_document(db, world["admin"], col)  # 컬렉션 기본값을 따른다 → Internal
    await make_document(db, world["admin"], col, security_level="Confidential")
    await db.flush()

    after = (await collect_governance_data(db, START, END, "admin")).documents_by_level
    assert after["Internal"] - before["Internal"] == 1
    assert after["Confidential"] - before["Confidential"] == 1
    assert after["Public"] == before["Public"]


async def test_docx_has_every_section_disclaimer_and_manual_fields(world):
    data = await collect_governance_data(world["db"], START, END, "admin")
    doc = DocxDocument(io.BytesIO(render_governance_docx(data)))

    paragraphs = [p.text for p in doc.paragraphs]
    for section in SECTIONS:
        assert section.title in paragraphs
    assert DISCLAIMER in paragraphs
    assert sum(LEGAL_REVIEW in p for p in paragraphs) >= len(SECTIONS)
    cells = [c.text for t in doc.tables for row in t.rows for c in row.cells]
    assert "4건 (실패 1건, 캐시 재사용 1건)" in cells
    assert any("asker: 근거 부족 질문" in c for c in cells)


async def test_docx_survives_control_characters_in_queries(world):
    from dataclasses import replace

    data = await collect_governance_data(world["db"], START, END, "admin")
    at, who, _ = data.ungrounded_samples[0]
    nasty = replace(data, ungrounded_samples=[(at, who, "질문\x00\x0b끝")])
    doc = DocxDocument(io.BytesIO(render_governance_docx(nasty)))

    cells = [c.text for t in doc.tables for row in t.rows for c in row.cells]
    assert any("질문끝" in c for c in cells)


def test_safe_cell_neutralizes_spreadsheet_formulas():
    from app.services.governance_report import _safe_cell

    assert _safe_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert _safe_cell("평범한 값\x07") == "평범한 값"


async def test_report_endpoint_is_admin_only_audited_and_validates_range(world):
    db = world["db"]
    with pytest.raises(HTTPException) as exc:
        await governance_api.download_governance_report(START, END, db, world["asker"])
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        await governance_api.download_governance_report(END, START, db, world["admin"])
    assert exc.value.status_code == 422

    response = await governance_api.download_governance_report(START, END, db, world["admin"])

    assert response.media_type == governance_api.DOCX_MEDIA_TYPE
    assert "attachment" in response.headers["content-disposition"]
    assert DocxDocument(io.BytesIO(response.body)).paragraphs  # 열리는 docx
    rows = (await db.scalars(
        select(AuditLog).where(AuditLog.action == "governance.report_download")
    )).all()
    assert [str(r.user_id) for r in rows] == [str(world["admin"].id)]
