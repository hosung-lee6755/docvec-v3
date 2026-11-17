"""모니터링 지표(전체 점검 2-8, 2026-11-16).

Prometheus 텍스트 형식으로 내보낸다. 수집기를 붙이지 않아도 curl로 읽을 수 있다. 값은 요청할 때마다
DB와 Redis에서 바로 센다. 지표는 운영자가 가장 먼저 묻는 네 가지를 답한다.

- 문서가 어느 상태에 몇 건 있는가(실패와 검토 대기가 쌓이는가)
- 작업 큐가 밀리고 있는가
- 최근 24시간 답변이 몇 건이고 얼마나 걸렸는가
- 파일 서버 연결의 마지막 동기화가 실패했는가
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.db.models.answer_trace import AnswerTrace
from app.db.models.document import Document
from app.db.models.source_connector import SourceConnector
from app.db.models.workflow_run import WorkflowRun

logger = logging.getLogger(__name__)

QUEUE_NAMES = ("critical", "high", "normal", "low", "embed", "llm", "extract")
ANSWER_WINDOW = timedelta(hours=24)
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@dataclass(frozen=True)
class Metric:
    name: str
    help: str
    samples: tuple[tuple[dict[str, str], float], ...]


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render(metrics: list[Metric]) -> str:
    lines: list[str] = []
    for metric in metrics:
        lines.append(f"# HELP {metric.name} {metric.help}")
        lines.append(f"# TYPE {metric.name} gauge")
        for labels, value in metric.samples:
            label_text = ",".join(f'{key}="{_escape(str(val))}"' for key, val in sorted(labels.items()))
            number = int(value) if float(value).is_integer() else round(float(value), 3)
            lines.append(f"{metric.name}{{{label_text}}} {number}" if label_text else f"{metric.name} {number}")
    return "\n".join(lines) + "\n"


async def _counts_by(db: AsyncSession, column, label: str, *where) -> tuple[tuple[dict[str, str], float], ...]:
    rows = (await db.execute(select(column, func.count()).where(*where).group_by(column))).all()
    return tuple(({label: str(value) if value is not None else "none"}, float(count)) for value, count in rows)


def _queue_lengths() -> dict[str, int] | None:
    """Celery 큐에 쌓인 작업 수. Redis에 닿지 못하면 None을 돌려 지표에 그 사실을 남긴다."""
    from app.core.rate_limit import _get_client

    try:
        client = _get_client()
        return {name: int(client.llen(name)) for name in QUEUE_NAMES}
    except Exception as exc:
        logger.warning("metrics: queue length unavailable: %s", exc)
        return None


async def collect(db: AsyncSession, now: datetime | None = None) -> list[Metric]:
    since = (now or datetime.utcnow()) - ANSWER_WINDOW
    answers = await _counts_by(db, AnswerTrace.status, "status", AnswerTrace.created_at >= since)
    latency = (
        await db.execute(select(func.avg(AnswerTrace.latency_ms)).where(AnswerTrace.created_at >= since))
    ).scalar()
    queues = await run_in_threadpool(_queue_lengths)
    metrics = [
        Metric("docvec_documents", "상태별 문서 수", await _counts_by(db, Document.status, "status")),
        Metric("docvec_workflow_runs", "상태별 워크플로우 실행 수", await _counts_by(db, WorkflowRun.status, "status")),
        Metric("docvec_answers_24h", "최근 24시간 답변 수(상태별)", answers),
        Metric(
            "docvec_answer_latency_ms_avg_24h", "최근 24시간 답변 평균 소요 시간(ms)",
            (({}, float(latency)),) if latency is not None else (),
        ),
        Metric(
            "docvec_connectors", "마지막 동기화 상태별 파일 서버 연결 수",
            await _counts_by(db, SourceConnector.last_status, "last_status", SourceConnector.enabled.is_(True)),
        ),
        Metric("docvec_queue_up", "작업 큐(Redis)에 닿는가(1/0)", (({}, 1.0 if queues is not None else 0.0),)),
    ]
    if queues is not None:
        metrics.append(Metric(
            "docvec_queue_length", "작업 큐에 쌓인 작업 수",
            tuple(({"queue": name}, float(length)) for name, length in queues.items()),
        ))
    return metrics
