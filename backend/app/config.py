from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    app_name: str = "Expense Tracker API"
    app_env: str = "development"
    api_prefix: str = "/api"
    cors_allow_origins: str = "*"

    database_url: str = "sqlite:///./data/app.db"
    redis_url: str = "redis://localhost:6379/0"
    import_stale_minutes: int = 15
    rules_config_path: str = "config/classification_rules.json"
    rate_limit_enabled: bool = True
    rate_limit_fail_open: bool = True
    rate_limit_key_prefix: str = "rl"
    rate_limit_read_per_minute: int = 240
    rate_limit_write_per_minute: int = 60
    rate_limit_strict_per_minute: int = 12
    clerk_enabled: bool = False
    clerk_require_auth: bool = True
    clerk_jwks_url: str = ""
    clerk_issuer: str = ""
    clerk_audience: str = ""
    admin_user_ids: str = ""
    log_level: str = "INFO"
    log_json: bool = True
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.0
    ops_metrics_enabled: bool = True
    ops_alert_queue_depth_threshold: int = 100
    ops_alert_failed_imports_threshold_24h: int = 5
    ops_alert_stale_processing_threshold: int = 3
    openai_api_key: str = ""

    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")


settings = Settings()


def cors_origins() -> list[str]:
    parsed = [origin.strip() for origin in settings.cors_allow_origins.split(",") if origin.strip()]
    return parsed or ["*"]
