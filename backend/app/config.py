from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Expense Tracker API"
    app_env: str = "development"
    api_prefix: str = "/api"
    cors_allow_origins: str = "*"

    database_url: str = "sqlite:///./data/app.db"
    redis_url: str = "redis://localhost:6379/0"
    import_stale_minutes: int = 15
    openai_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()


def cors_origins() -> list[str]:
    parsed = [origin.strip() for origin in settings.cors_allow_origins.split(",") if origin.strip()]
    return parsed or ["*"]
