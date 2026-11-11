"""AI 기본법 대응 근거 자료 내려받기(관리자) — v3 마일스톤 2.

기간을 받아 운영 데이터를 집계하고 docx로 돌려준다. 내려받은 사실은 감사 로그
(`governance.report_download`)에 남는다. 문서 내용은 `app/services/governance_report.py` 참고.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, require_admin
from app.db.models.user import User
from app.db.session import get_db
from app.services.audit import log_audit
from app.services.governance_report import collect_governance_data, render_governance_docx

router = APIRouter()

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_DEFAULT_PERIOD = timedelta(days=30)
_MAX_PERIOD = timedelta(days=366)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@router.get("/admin/governance/report")
async def download_governance_report(
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    end = _as_utc(to_date) if to_date else datetime.now(timezone.utc)
    start = _as_utc(from_date) if from_date else end - _DEFAULT_PERIOD
    if start > end:
        raise HTTPException(status_code=422, detail="시작일이 종료일보다 늦습니다")
    if end - start > _MAX_PERIOD:
        raise HTTPException(status_code=422, detail="기간은 최대 366일까지 지정할 수 있습니다")

    data = await collect_governance_data(db, start, end, current_user.username)
    content = render_governance_docx(data)
    log_audit(
        db, str(current_user.id), "governance.report_download", "governance_report", None,
        detail={"from": start.isoformat(), "to": end.isoformat()},
    )
    await db.commit()

    filename = f"ai-governance-report-{start:%Y%m%d}-{end:%Y%m%d}.docx"
    return Response(
        content=content,
        media_type=DOCX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
