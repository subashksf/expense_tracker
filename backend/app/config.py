from pydantic_settings import BaseSettings, SettingsConfigDict


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
    openai_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()


def cors_origins() -> list[str]:
    parsed = [origin.strip() for origin in settings.cors_allow_origins.split(",") if origin.strip()]
    return parsed or ["*"]
