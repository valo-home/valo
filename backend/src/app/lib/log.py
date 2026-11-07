import logging
import sys

import structlog

from app.lib import errlog
from app.lib.settings import settings


def setup(process: str) -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    render = structlog.processors.JSONRenderer() if settings.log_json else structlog.dev.ConsoleRenderer(colors=False)
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                render,
            ],
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler, errlog.Handler(process)]
    root.setLevel(level)
    for name in ("aiormq", "aio_pika", "httpx", "socketio", "engineio", "granian.access"):
        logging.getLogger(name).setLevel(max(level, logging.WARNING))
    structlog.contextvars.bind_contextvars(process=process)


def get(name: str):
    return structlog.get_logger(name)
