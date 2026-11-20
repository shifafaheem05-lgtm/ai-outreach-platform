from functools import lru_cache
from pathlib import Path, PurePosixPath, PureWindowsPath

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]  # the folder that contains app/, alembic/ and .env


def anchor_sqlite_url(url: str) -> str:
    """Make a relative SQLite file path independent of the folder the command was started from.

    sqlite:///./dev.db  ->  sqlite:///<backend folder>/dev.db
    Absolute paths (POSIX or Windows) and in-memory databases are left unchanged. Other databases are untouched.
    """
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return url
    path = url[len(prefix):]
    if not path or path.startswith(":memory:") or path.startswith("file:"):
        return url
    if PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute():
        return url
    return prefix + (BACKEND_DIR / path).resolve().as_posix()


class Settings(BaseSettings):
    # Absolute path: `.env` is found no matter which folder uvicorn/alembic/pytest is started from.
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    app_env: str = "development"
    secret_key: str = "dev-secret-change-me-not-for-production"
    encryption_key: str = ""
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 14
    cors_origins: str = "http://localhost:5173"
    database_url: str = "sqlite:///./dev.db"
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
    allow_registration: bool = True  # set false on private deployments; admins then add users in Settings

    @field_validator("database_url")
    @classmethod
    def _anchor_sqlite(cls, v: str) -> str:
        return anchor_sqlite_url(v)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


def production_problems(cfg: "Settings") -> list[str]:
    """Misconfigurations that must stop the app from starting with APP_ENV=production."""
    if cfg.app_env != "production":
        return []
    problems = []
    if cfg.secret_key.startswith(("change-me", "dev-secret")) or len(cfg.secret_key) < 32:
        problems.append("SECRET_KEY must be a long random string (32+ characters)")
    if not cfg.encryption_key:
        problems.append("ENCRYPTION_KEY is required (stored mailbox passwords are encrypted with it)")
    else:
        try:
            from cryptography.fernet import Fernet

            Fernet(cfg.encryption_key.encode())
        except Exception:  # noqa: BLE001
            problems.append("ENCRYPTION_KEY is not a valid Fernet key")
    if cfg.seed_demo_data:
        problems.append("SEED_DEMO_DATA must be false (the demo account has a publicly known password)")
    if cfg.database_url.startswith("sqlite"):
        problems.append("DATABASE_URL must point to PostgreSQL, not SQLite")
    if cfg.public_base_url.startswith("http://localhost") or cfg.public_base_url.startswith("http://127."):
        problems.append("PUBLIC_BASE_URL must be a public https URL (unsubscribe links are built from it)")
    return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
