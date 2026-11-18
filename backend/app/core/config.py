from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    secret_key: str = "dev-secret-change-me"
    encryption_key: str = ""
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 14
    cors_origins: str = "http://localhost:5173"
    database_url: str = "sqlite:///./dev.db"
    redis_url: str = "redis://localhost:6379/0"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    agency_services: str = ""  # what your agency sells; used to frame research opportunities
    public_base_url: str = "http://localhost:8000"
    seed_demo_data: bool = True
    auto_create_tables: bool = True  # set false when using `alembic upgrade head`
    enable_scheduler: bool = True  # in-process sender tick (single process; no Redis needed)
    send_delay_min: float = 20.0  # randomised spacing between sends, seconds
    send_delay_max: float = 60.0
    login_max_failures: int = 5  # per IP+email per 15 minutes

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
