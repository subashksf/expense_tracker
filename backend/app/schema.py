from sqlalchemy import inspect, text

from .db import engine


def ensure_schema_compatibility() -> None:
    inspector = inspect(engine)
    ddl: list[str] = []

    def add_if_missing(table_name: str, column_name: str, column_ddl: str) -> None:
        try:
            columns = {column["name"] for column in inspector.get_columns(table_name)}
        except Exception:  # noqa: BLE001
            return
        if column_name not in columns:
            ddl.append(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_ddl}")

    add_if_missing("statement_imports", "queue_job_id", "VARCHAR(64)")
    add_if_missing("statement_imports", "processing_started_at", "TIMESTAMP")
    add_if_missing("statement_imports", "finished_at", "TIMESTAMP")
    add_if_missing("statement_imports", "user_id", "VARCHAR(128)")
    add_if_missing("transactions", "user_id", "VARCHAR(128)")
    add_if_missing("insight_reports", "user_id", "VARCHAR(128)")
    add_if_missing("duplicate_reviews", "user_id", "VARCHAR(128)")

    if ddl:
        with engine.begin() as connection:
            for statement in ddl:
                connection.execute(text(statement))
