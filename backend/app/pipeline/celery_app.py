from celery import Celery
from celery.signals import setup_logging
from kombu import Exchange, Queue

from app.core.config import settings
from app.core.logging import configure_logging


@setup_logging.connect
def _configure_worker_logging(**kwargs):
    # Celery installs its own logging config on worker startup unless a
    # `setup_logging` receiver is registered — this replaces that with the same
    # structured setup the API uses, so task logs share one shape.
    configure_logging()


celery_app = Celery(
    "docvec",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.task_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.result_serializer = "json"
celery_app.conf.timezone = "UTC"
celery_app.conf.enable_utc = True

celery_app.conf.include = [
    "app.pipeline.tasks.process",
    "app.pipeline.tasks.chat",
    "app.pipeline.tasks.summary",
    "app.pipeline.tasks.chunks",
    "app.pipeline.tasks.reembed",
    "app.pipeline.tasks.workflow",
]

default_exchange = Exchange("celery", type="direct")
celery_app.conf.task_queues = (
    Queue("critical", exchange=default_exchange, routing_key="critical"),
    Queue("high", exchange=default_exchange, routing_key="high"),
    Queue("normal", exchange=default_exchange, routing_key="normal"),
    Queue("low", exchange=default_exchange, routing_key="low"),
    Queue("embed", exchange=default_exchange, routing_key="embed"),
)

celery_app.conf.task_routes = {
    "tasks.process_document": {"queue": "high"},
}

# 문서 상세 페이지를 열어야만 멈춘 run을 정리하던 지연 감지(reconcile_stuck_run)를
# 능동적으로 보완한다 — beat 컨테이너가 이 간격마다 sweep_stuck_workflow_runs를
# 실행해, 아무도 페이지를 열지 않아도 timeout+grace를 넘긴 run을 FAILED로 확정한다.
# 30초 = reprocess_service._TIMEOUT_GRACE_SECONDS와 동일한 간격 — 그보다 길면
# grace 기간 자체가 무의미해지고, 그보다 짧아도 최소 grace 이내에는 정리되지 않는다.
celery_app.conf.beat_schedule = {
    "sweep-stuck-workflow-runs": {
        "task": "tasks.sweep_stuck_workflow_runs",
        "schedule": 30.0,
    },
}
