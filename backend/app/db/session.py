from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

IS_SQLITE = settings.database_url.startswith("sqlite")
connect_args = {"check_same_thread": False} if IS_SQLITE else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


if IS_SQLITE:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - exercised via tests/test_local_dev.py
        """Make SQLite behave like the production database for local development."""
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")  # enforce relationships like PostgreSQL does
        cur.execute("PRAGMA journal_mode=WAL")  # readers do not block the background sender's writes
        cur.execute("PRAGMA busy_timeout=5000")  # wait up to 5 s instead of failing with "database is locked"
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


def check_schema_ready(bind: Engine) -> None:
    """Fail early with a clear instruction when the tables have not been created yet."""
    if "users" not in inspect(bind).get_table_names():
        raise RuntimeError(
            "The database has no tables yet. From the backend folder run:  alembic upgrade head\n"
            "(or set AUTO_CREATE_TABLES=true to let the app create them on start-up in development)."
        )
