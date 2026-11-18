import atexit
import os
import tempfile
import uuid
from pathlib import Path

# Must be set before the app (and its cached settings) is imported.
# Every run gets its OWN throw-away SQLite file in the system temp folder, so a leftover or locked
# file from an earlier run (common on Windows) can never collide with this run's fixed test emails.
# Set TEST_DATABASE_URL to run the suite against an EMPTY PostgreSQL database instead.
_db_file = Path(tempfile.gettempdir()) / f"aop_test_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_file.as_posix()}"
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["ENABLE_SCHEDULER"] = "false"
os.environ["SEND_DELAY_MIN"] = "0"
os.environ["SEND_DELAY_MAX"] = "0"
os.environ["OPENAI_API_KEY"] = ""
os.environ["OPENAI_BASE_URL"] = "https://api.example.invalid/v1"

import pytest
from fastapi.testclient import TestClient


def _cleanup() -> None:
    try:
        from app.db.session import engine

        engine.dispose()  # release the file so Windows can delete it
    except Exception:  # noqa: BLE001
        pass
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(str(_db_file) + suffix)
        except OSError:
            pass  # best effort: the name is unique, so a leftover file is harmless


atexit.register(_cleanup)


@pytest.fixture(scope="session")
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c
