from dataclasses import dataclass

from redis import Redis
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job

from .config import settings
from .tasks import process_import_job


@dataclass
class QueueJobState:
    status: str
    error: str | None = None


def enqueue_import(import_id: str) -> str | None:
    try:
        redis_connection = Redis.from_url(settings.redis_url)
        redis_connection.ping()
        queue = Queue("imports", connection=redis_connection)
        job = queue.enqueue(process_import_job, import_id, job_timeout=600)
        return job.id
    except Exception:  # noqa: BLE001
        # Fallback makes local development possible without Redis.
        process_import_job(import_id)
        return None


def read_job_state(job_id: str) -> QueueJobState | None:
    try:
        redis_connection = Redis.from_url(settings.redis_url)
        redis_connection.ping()
        job = Job.fetch(job_id, connection=redis_connection)
        status = job.get_status(refresh=True)
        error = None
        if status == "failed" and job.exc_info:
            error = _summarize_exception(job.exc_info)
        return QueueJobState(status=status, error=error)
    except NoSuchJobError:
        return QueueJobState(status="missing", error="Queue job not found")
    except Exception:  # noqa: BLE001
        return None


def _summarize_exception(exc_info: str) -> str:
    lines = [line.strip() for line in exc_info.splitlines() if line.strip()]
    if not lines:
        return "Queue job failed."

    error_lines = [
        line
        for line in lines
        if (
            "sqlalchemy.exc." in line
            or "psycopg.errors." in line
            or line.startswith("IntegrityError")
            or line.startswith("OperationalError")
            or line.startswith("ProgrammingError")
            or line.startswith("ValueError")
            or line.startswith("KeyError")
        )
    ]
    if error_lines:
        return " | ".join(error_lines[:2])[:1000]

    # Fallback to last non-background line.
    for line in reversed(lines):
        if "Background on this error" not in line:
            return line[:1000]
    return lines[-1][:1000]
