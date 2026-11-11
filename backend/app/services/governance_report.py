"""AI 기본법 대응 근거 자료(docx) 생성 — v3 마일스톤 2.

운영 데이터(답변 추적 기록, 감사 로그, 권한 설정, PII 처리 기록)를 기간별로 집계해
제34조(고영향 AI 사업자 책무) 관련 항목별로 정리한다. 시스템은 수치와 설정만 채운다.
법적 해석이 필요한 칸은 "법률 검토 필요"로 표시한 담당자 작성란으로 남기며, 이 문서가
법적 적합성을 증명하지 않는다는 점을 첫 장에 밝힌다.

항목 구성은 `SECTIONS` 한 곳에서 정의한다. 법률 검토 결과에 따라 항목이 바뀌면 여기만 고친다.
"""
from __future__ import annotations

import io
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.answer_trace import AnswerTrace, AnswerTraceSource
from app.db.models.audit_log import AuditLog
from app.db.models.collection import Collection
from app.db.models.document import Document
from app.db.models.document_acl import DocumentAclEntry
from app.db.models.pii_detection import PiiDetection
from app.db.models.user_group import UserGroup
from app.services.access_policy import DEFAULT_DOCUMENT_LEVEL, SECURITY_LEVELS

LEGAL_REVIEW = "법률 검토 필요"
DISCLAIMER = (
    "이 문서는 시스템 운영 데이터를 요약한 근거 자료이며, AI 기본법 의무를 충족했는지를 판정하지 않는다. "
    "고영향 AI 해당 여부, 각 의무의 적용 범위, 기록 보관 기간은 법률 검토로 확인해야 한다."
)
AI_GENERATED_NOTICE = "이 시스템의 채팅 답변에는 \"AI가 생성한 답변\" 표시가 붙는다(제31조 생성형 AI 표시 관련)."

PERMISSION_ACTIONS = (
    "document.security_level_update", "document.acl_update", "collection.security_level_update",
    "user.clearance_update", "group.create", "group.update", "group.delete",
    "group.member_add", "group.member_remove",
)
ACCESS_AUDIT_ACTIONS = (
    "document.preview", "document.download", "collection.export", "answer_trace.view",
    "governance.report_download",
)
_FAILED_ANSWER_LIST_LIMIT = 20
_QUERY_PREVIEW_LEN = 80


@dataclass(frozen=True)
class GovernanceData:
    start: datetime
    end: datetime
    generated_at: datetime
    generated_by: str
    documents_by_level: dict[str, int]
    restricted_documents: int
    group_count: int
    permission_changes: dict[str, int]
    answers: int
    grounding: dict[str, int]
    broadened: int
    cache_hits: int
    failed_answers: int
    avg_latency_ms: int | None
    answers_by_model: dict[str, int]
    answers_without_citation: int
    pii_by_action: dict[str, int]
    admin_actions: dict[str, int]
    ungrounded_samples: list[tuple[datetime, str, str]] = field(default_factory=list)
    access_audits: dict[str, int] = field(default_factory=dict)
    oldest_trace_at: datetime | None = None


async def _count_by(db: AsyncSession, column, *filters) -> dict[str, int]:
    rows = await db.execute(select(column, func.count()).where(*filters).group_by(column))
    return {str(key): n for key, n in rows.all() if key is not None}


async def collect_governance_data(
    db: AsyncSession, start: datetime, end: datetime, generated_by: str
) -> GovernanceData:
    in_period = (AnswerTrace.created_at >= start, AnswerTrace.created_at <= end)
    audit_period = (AuditLog.created_at >= start, AuditLog.created_at <= end)

    effective_level = func.coalesce(
        Document.security_level, Collection.default_security_level, DEFAULT_DOCUMENT_LEVEL
    )
    level_rows = await db.execute(
        select(effective_level, func.count())
        .select_from(Document)
        .outerjoin(Collection, Collection.id == Document.collection_id)
        .group_by(effective_level)
    )
    documents_by_level = {level: 0 for level in SECURITY_LEVELS}
    documents_by_level.update({str(k): n for k, n in level_rows.all()})

    cited = (
        select(AnswerTraceSource.trace_id)
        .where(AnswerTraceSource.cited.is_(True))
        .group_by(AnswerTraceSource.trace_id)
        .subquery()
    )
    totals = (
        await db.execute(
            select(
                func.count(AnswerTrace.id),
                func.count().filter(AnswerTrace.broadened.is_(True)),
                func.count().filter(AnswerTrace.cache_hit.is_(True)),
                func.count().filter(AnswerTrace.status == "FAILED"),
                func.avg(AnswerTrace.latency_ms),
                func.count().filter(
                    (AnswerTrace.status == "DONE") & (cited.c.trace_id.is_(None))
                ),
            )
            .outerjoin(cited, cited.c.trace_id == AnswerTrace.id)
            .where(*in_period)
        )
    ).one()
    answers, broadened, cache_hits, failed, avg_latency, without_citation = totals

    samples = (
        await db.execute(
            select(AnswerTrace.created_at, AnswerTrace.username, AnswerTrace.query)
            .where(*in_period, AnswerTrace.grounding == "failed")
            .order_by(AnswerTrace.created_at.desc())
            .limit(_FAILED_ANSWER_LIST_LIMIT)
        )
    ).all()

    pii_rows = await db.execute(
        select(PiiDetection.action, func.count())
        .where(PiiDetection.created_at >= start, PiiDetection.created_at <= end)
        .group_by(PiiDetection.action)
    )

    return GovernanceData(
        start=start,
        end=end,
        generated_at=datetime.now(timezone.utc),
        generated_by=generated_by,
        documents_by_level=documents_by_level,
        restricted_documents=await db.scalar(
            select(func.count(func.distinct(DocumentAclEntry.document_id)))
        ) or 0,
        group_count=await db.scalar(select(func.count(UserGroup.id))) or 0,
        permission_changes=await _count_by(
            db, AuditLog.action, *audit_period, AuditLog.action.in_(PERMISSION_ACTIONS)
        ),
        answers=answers or 0,
        grounding=await _count_by(db, AnswerTrace.grounding, *in_period),
        broadened=broadened or 0,
        cache_hits=cache_hits or 0,
        failed_answers=failed or 0,
        avg_latency_ms=int(avg_latency) if avg_latency is not None else None,
        answers_by_model=await _count_by(db, AnswerTrace.model_key, *in_period),
        answers_without_citation=without_citation or 0,
        pii_by_action={str(a): n for a, n in pii_rows.all()},
        admin_actions=await _count_by(
            db, AuditLog.action, *audit_period, AuditLog.action.notin_(ACCESS_AUDIT_ACTIONS)
        ),
        ungrounded_samples=[
            (at, name or "(삭제된 사용자)", (query or "")[:_QUERY_PREVIEW_LEN])
            for at, name, query in samples
        ],
        access_audits=await _count_by(
            db, AuditLog.action, *audit_period, AuditLog.action.in_(ACCESS_AUDIT_ACTIONS)
        ),
        oldest_trace_at=await db.scalar(select(func.min(AnswerTrace.created_at))),
    )


# ---------------------------------------------------------------------------
# 항목 정의 — 법률 검토 결과에 따라 바뀌면 여기만 고친다.
# ---------------------------------------------------------------------------

def _pct(part: int, whole: int) -> str:
    return f"{part}건 ({part * 100 / whole:.1f}%)" if whole else f"{part}건"


def _counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{k} {v}건" for k, v in sorted(counts.items())) or "없음"


@dataclass(frozen=True)
class Section:
    title: str
    purpose: str
    rows: Callable[[GovernanceData], list[tuple[str, str]]]
    manual_fields: tuple[str, ...]


SECTIONS: tuple[Section, ...] = (
    Section(
        title="1. 위험관리",
        purpose="문서 권한 체계와 권한 변경 이력으로, 허용되지 않은 사람에게 문서가 근거로 쓰이지 않도록 관리한 내용을 보인다.",
        rows=lambda d: [
            ("보안등급별 문서 수(유효 등급 기준)", _counts(d.documents_by_level)),
            ("접근 허용 목록으로 제한된 문서 수", f"{d.restricted_documents}건"),
            ("사용자 그룹 수", f"{d.group_count}개"),
            ("기간 중 권한 변경 건수", _counts(d.permission_changes)),
            ("권한 판정 방식", "검색 단계에서 보안등급·허용 목록으로 거르고, 답변 생성 전에 다시 확인한다. 관리자도 예외 없음."),
        ],
        manual_fields=("위험 식별·평가 결과", "위험 완화 조치 계획"),
    ),
    Section(
        title="2. 설명",
        purpose="답변이 어떤 근거와 절차로 만들어졌는지 보인다. 개별 답변은 관리 화면의 답변 추적에서 근거 문서까지 확인할 수 있다.",
        rows=lambda d: [
            ("기간 중 답변 수", f"{d.answers}건 (실패 {d.failed_answers}건, 캐시 재사용 {d.cache_hits}건)"),
            ("근거 검증 결과", _counts(d.grounding)),
            ("근거 부족으로 재검색한 답변", _pct(d.broadened, d.answers)),
            ("인용이 없는 답변", _pct(d.answers_without_citation, d.answers)),
            ("사용 모델별 답변 수", _counts(d.answers_by_model)),
            ("평균 응답 시간", f"{d.avg_latency_ms}ms" if d.avg_latency_ms is not None else "기록 없음"),
        ],
        manual_fields=("이용자에게 제공하는 설명 방식",),
    ),
    Section(
        title="3. 이용자 보호",
        purpose="개인정보 처리와 생성물 표시 현황을 보인다.",
        rows=lambda d: [
            ("기간 중 개인정보 탐지·처리 건수", _counts(d.pii_by_action)),
            ("생성물 표시", AI_GENERATED_NOTICE),
        ],
        manual_fields=("이용자 고지 내용", "이의 제기·피해 구제 절차"),
    ),
    Section(
        title="4. 사람의 감독",
        purpose="관리자가 시스템 운영에 개입한 기록과, 사람이 검토해야 할 답변 목록을 보인다.",
        rows=lambda d: [
            ("기간 중 관리 조치 건수(감사 로그)", _counts(d.admin_actions)),
            ("근거 검증에 실패한 답변(최근 20건)",
             "\n".join(f"{at:%Y-%m-%d %H:%M} {who}: {q}" for at, who, q in d.ungrounded_samples) or "없음"),
        ],
        manual_fields=("감독 담당자와 검토 주기", "검토 결과와 후속 조치"),
    ),
    Section(
        title="5. 기록 보관",
        purpose="답변 추적 기록과 조회 감사 기록이 남아 있는 범위를 보인다.",
        rows=lambda d: [
            ("기간 중 답변 추적 기록", f"{d.answers}건"),
            ("보관 중인 가장 오래된 추적 기록",
             f"{d.oldest_trace_at:%Y-%m-%d}" if d.oldest_trace_at else "없음"),
            ("기간 중 조회 감사 건수", _counts(d.access_audits)),
            ("보관 정책", f"자동 삭제 없음(무기한). 보관 기간은 {LEGAL_REVIEW}."),
        ],
        manual_fields=("법정 보관 기간과 파기 절차",),
    ),
)


_XML_ILLEGAL = re.compile("[^\u0009\u000a\u000d\u0020-\ud7ff\ue000-\ufffd]")
_FORMULA_PREFIX = ("=", "+", "-", "@")


def _safe_cell(value: str) -> str:
    """사용자가 입력한 질문이 docx 생성을 깨뜨리거나 스프레드시트 수식으로 붙지 않게 정리한다."""
    cleaned = _XML_ILLEGAL.sub("", value)
    return "'" + cleaned if cleaned.startswith(_FORMULA_PREFIX) else cleaned


def render_governance_docx(data: GovernanceData) -> bytes:
    from docx import Document as DocxDocument

    doc = DocxDocument()
    doc.add_heading("AI 기본법 대응 근거 자료 (운영 데이터 요약)", level=0)
    doc.add_paragraph(
        f"대상 기간: {data.start:%Y-%m-%d %H:%M} ~ {data.end:%Y-%m-%d %H:%M} (UTC)\n"
        f"생성: {data.generated_at:%Y-%m-%d %H:%M} (UTC), {data.generated_by}"
    )
    doc.add_paragraph(DISCLAIMER)

    for section in SECTIONS:
        doc.add_heading(section.title, level=1)
        doc.add_paragraph(section.purpose)
        rows = section.rows(data)
        table = doc.add_table(rows=len(rows), cols=2)
        table.style = "Table Grid"
        for i, (label, value) in enumerate(rows):
            table.cell(i, 0).text = _safe_cell(label)
            table.cell(i, 1).text = _safe_cell(value)
        doc.add_paragraph("담당자 작성란")
        for name in section.manual_fields:
            doc.add_paragraph(f"{name}: ({LEGAL_REVIEW})", style="List Bullet")

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
