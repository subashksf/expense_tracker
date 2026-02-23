import logging

from redis import Redis
from rq import Worker

from app.config import settings
from app.db import Base, engine
from app.observability import configure_logging, init_sentry
from app.schema import ensure_schema_compatibility


def main() -> None:
    configure_logging("expense_tracker.worker")
    init_sentry("expense_tracker.worker")
    logger = logging.getLogger("expense_tracker.worker")

    Base.metadata.create_all(bind=engine)
    ensure_schema_compatibility()

    logger.info(
        "worker_starting",
        extra={
            "app_env": settings.app_env,
            "redis_url_present": bool(settings.redis_url),
        },
    )
    redis_connection = Redis.from_url(settings.redis_url)
    worker = Worker(["imports"], connection=redis_connection)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
