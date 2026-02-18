from redis import Redis
from rq import Worker

from app.config import settings
from app.db import Base, engine
from app.schema import ensure_schema_compatibility


def main() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_schema_compatibility()

    redis_connection = Redis.from_url(settings.redis_url)
    worker = Worker(["imports"], connection=redis_connection)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
