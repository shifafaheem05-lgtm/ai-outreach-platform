import os

# Must be set before the app (and its cached settings) is imported.
# Set TEST_DATABASE_URL to run the suite against an EMPTY PostgreSQL database instead of SQLite.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite:///./test_suite.db")
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["ENABLE_SCHEDULER"] = "false"
os.environ["SEND_DELAY_MIN"] = "0"
os.environ["SEND_DELAY_MAX"] = "0"
os.environ["OPENAI_API_KEY"] = ""
os.environ["OPENAI_BASE_URL"] = "https://api.example.invalid/v1"

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c
    if os.environ["DATABASE_URL"].startswith("sqlite"):
        try:
            os.remove("test_suite.db")
        except OSError:
            pass
