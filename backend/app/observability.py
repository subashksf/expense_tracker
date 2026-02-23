import json
import logging
import os
import sys
import time
from datetime import UTC, datetime
from typing import Any

from .config import settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        reserved = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "asctime",
        }
        for key, value in record.__dict__.items():
            if key in reserved or key.startswith("_"):
                continue
            payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging(service_name: str) -> None:
    level_name = (settings.log_level or "INFO").upper().strip()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    if settings.log_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(level)
    logging.captureWarnings(True)

    logging.getLogger(service_name).info(
        "logging_configured",
        extra={
            "service": service_name,
            "log_level": level_name,
            "log_json": settings.log_json,
            "pid": os.getpid(),
        },
    )


def init_sentry(service_name: str) -> None:
    dsn = settings.sentry_dsn.strip()
    if not dsn:
        return
    try:
        import sentry_sdk
    except Exception:  # noqa: BLE001
        logging.getLogger(service_name).warning(
            "sentry_sdk_unavailable",
            extra={"service": service_name},
        )
        return

    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=float(settings.sentry_traces_sample_rate),
        release=os.getenv("RELEASE_VERSION", ""),
        environment=settings.app_env,
    )
    logging.getLogger(service_name).info(
        "sentry_initialized",
        extra={
            "service": service_name,
            "traces_sample_rate": float(settings.sentry_traces_sample_rate),
        },
    )


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def monotonic_ms() -> float:
    return time.perf_counter() * 1000.0
