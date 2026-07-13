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
    "app.pipeline.tasks.ingest",
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
    "tasks.ingest_document": {"queue": "high"},
    "tasks.process_document": {"queue": "high"},
}
