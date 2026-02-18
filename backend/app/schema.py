from sqlalchemy import inspect, text

from .db import engine


def ensure_schema_compatibility() -> None:
    inspector = inspect(engine)
    try:
        columns = {column["name"] for column in inspector.get_columns("statement_imports")}
    except Exception:  # noqa: BLE001
        return

    ddl = []
    if "queue_job_id" not in columns:
        ddl.append("ALTER TABLE statement_imports ADD COLUMN queue_job_id VARCHAR(64)")
    if "processing_started_at" not in columns:
        ddl.append("ALTER TABLE statement_imports ADD COLUMN processing_started_at TIMESTAMP")
    if "finished_at" not in columns:
        ddl.append("ALTER TABLE statement_imports ADD COLUMN finished_at TIMESTAMP")

    if not ddl:
        return

    with engine.begin() as connection:
        for statement in ddl:
            connection.execute(text(statement))
