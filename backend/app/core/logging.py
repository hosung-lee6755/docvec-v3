import logging
import sys

import structlog

from app.core.config import settings


def configure_logging() -> None:
    """Route stdlib logging (ours, uvicorn's, celery's) through structlog so every
    log line shares one structured, timestamped shape instead of each library's
    own default formatter — previously there was no logging configuration at all,
    so exceptions in Celery tasks left no trace beyond a truncated string in the DB.
    """
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer = (
        structlog.processors.JSONRenderer()
        if settings.is_production
        else structlog.dev.ConsoleRenderer()
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(logging.INFO)

    # uvicorn/celery configure their own handlers on first use; clearing them and
    # letting the record propagate to root keeps every line in the same JSON shape.
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "celery", "celery.task"):
        lib_logger = logging.getLogger(name)
        lib_logger.handlers = []
        lib_logger.propagate = True
