"""Local development mode (SQLite, no Docker) must work, and production rules must stay strict."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from dotenv import dotenv_values
from sqlalchemy import create_engine, inspect, text

from app.core.config import BACKEND_DIR, Settings, anchor_sqlite_url, production_problems
from app.db.session import IS_SQLITE, check_schema_ready, engine

REPO = BACKEND_DIR.parent
needs_sqlite = pytest.mark.skipif(not IS_SQLITE, reason="SQLite-specific check")


def load_env_file(path: Path, **override) -> Settings:
    """Settings built from the FILE ONLY (the test process's own environment variables would otherwise win)."""
    values = {k.lower(): v for k, v in dotenv_values(path).items() if v is not None}
    return Settings(_env_file=None, **{**values, **override})


# ------------------------------------------------------------------ database URL handling
def test_relative_sqlite_path_is_anchored_to_backend_folder():
    url = anchor_sqlite_url("sqlite:///./dev.db")
    assert url == f"sqlite:///{(BACKEND_DIR / 'dev.db').as_posix()}"
    assert anchor_sqlite_url("sqlite:///data/app.db") == f"sqlite:///{(BACKEND_DIR / 'data/app.db').as_posix()}"


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:////var/data/app.db",  # POSIX absolute
        "sqlite:///C:/Users/DELL/app.db",  # Windows absolute
        "sqlite:///C:\\Users\\DELL\\app.db",
        "sqlite://",  # in-memory
        "sqlite:///:memory:",
        "postgresql+psycopg2://u:p@db:5432/x",  # other databases are never touched
    ],
)
def test_absolute_memory_and_postgres_urls_are_unchanged(url):
    assert anchor_sqlite_url(url) == url


def test_settings_anchor_sqlite_but_keep_postgres():
    assert Settings(_env_file=None, database_url="sqlite:///./dev.db").database_url.startswith("sqlite:///" + BACKEND_DIR.as_posix())
    pg = "postgresql+psycopg2://u:p@db:5432/x"
    assert Settings(_env_file=None, database_url=pg).database_url == pg


def test_sqlite_path_with_spaces_works(tmp_path):
    folder = tmp_path / "ai outreach pro" / "backend"  # the user's real folder name has spaces
    folder.mkdir(parents=True)
    url = f"sqlite:///{(folder / 'dev.db').as_posix()}"
    eng = create_engine(anchor_sqlite_url(url))
    with eng.begin() as c:
        c.execute(text("create table t (id integer primary key)"))
    eng.dispose()
    assert (folder / "dev.db").exists()


def test_production_still_rejects_sqlite_even_when_anchored():
    base = dict(
        app_env="production", secret_key="k" * 40, encryption_key=Fernet.generate_key().decode(),
        seed_demo_data=False, public_base_url="https://app.example.com",
    )
    assert any("PostgreSQL" in p for p in production_problems(Settings(_env_file=None, database_url="sqlite:///./dev.db", **base)))
    assert any("PostgreSQL" in p for p in production_problems(Settings(_env_file=None, database_url="sqlite:///C:/x/dev.db", **base)))
    assert production_problems(Settings(_env_file=None, database_url="postgresql+psycopg2://u:p@db/x", **base)) == []


# ------------------------------------------------------------------ env templates
def test_backend_env_example_is_a_valid_local_dev_config():
    cfg = load_env_file(BACKEND_DIR / ".env.example")
    assert cfg.app_env == "development"
    assert cfg.database_url.startswith("sqlite:///")
    assert cfg.auto_create_tables is False and cfg.seed_demo_data is True
    assert production_problems(cfg) == []  # nothing to complain about in development
    # secrets are never shipped in the template
    assert cfg.encryption_key == ""
    text_ = (BACKEND_DIR / ".env.example").read_text()
    assert "SECRET_KEY=\n" in text_ and "ENCRYPTION_KEY=\n" in text_


def test_the_dev_template_is_refused_in_production():
    cfg = load_env_file(BACKEND_DIR / ".env.example", app_env="production")
    problems = " | ".join(production_problems(cfg))
    for must in ("SECRET_KEY", "ENCRYPTION_KEY", "SEED_DEMO_DATA", "PostgreSQL", "PUBLIC_BASE_URL"):
        assert must in problems


def test_production_template_uses_postgres_and_no_real_credentials():
    cfg = load_env_file(REPO / ".env.production.example")
    assert cfg.app_env == "production" and cfg.database_url.startswith("postgresql")
    assert cfg.secret_key == "" and cfg.encryption_key == ""  # no key is shipped
    assert cfg.seed_demo_data is False and cfg.auto_create_tables is False
    assert production_problems(cfg)  # unusable until the operator fills in real values
    assert "DB_PASSWORD" in (REPO / ".env.production.example").read_text()  # placeholder, not a credential


# ------------------------------------------------------------------ make_env.py
def _run_make_env(*args):
    return subprocess.run([sys.executable, str(BACKEND_DIR / "scripts" / "make_env.py"), *args], capture_output=True, text=True)


def test_make_env_generates_fresh_valid_secrets_and_never_overwrites(tmp_path):
    out = tmp_path / "my .env"
    r = _run_make_env("--out", str(out))
    assert r.returncode == 0 and out.exists(), r.stderr
    cfg = load_env_file(out)
    assert len(cfg.secret_key) >= 32 and not cfg.secret_key.startswith(("change-me", "dev-secret"))
    Fernet(cfg.encryption_key.encode())  # valid key or this raises
    assert cfg.database_url.startswith("sqlite:///") and cfg.app_env == "development"

    first = out.read_text()
    r2 = _run_make_env("--out", str(out))  # second run keeps the keys
    assert r2.returncode == 0 and "already exists" in r2.stdout and out.read_text() == first

    r3 = _run_make_env("--out", str(out), "--force")  # explicit --force makes new keys
    assert r3.returncode == 0 and out.read_text() != first


def test_make_env_keys_are_random_per_run(tmp_path):
    a, b = tmp_path / "a.env", tmp_path / "b.env"
    _run_make_env("--out", str(a))
    _run_make_env("--out", str(b))
    ka, kb = load_env_file(a), load_env_file(b)
    assert ka.secret_key != kb.secret_key and ka.encryption_key != kb.encryption_key


def test_generated_env_works_for_encrypting_credentials(tmp_path, monkeypatch):
    """The key make_env produces must round-trip the app's own credential encryption."""
    out = tmp_path / ".env"
    _run_make_env("--out", str(out))
    key = load_env_file(out).encryption_key
    from app.core import security

    monkeypatch.setattr(security.settings, "encryption_key", key)
    token = security.encrypt_secret("app-password-123")
    assert token != "app-password-123" and security.decrypt_secret(token) == "app-password-123"


# ------------------------------------------------------------------ SQLite behaves like production
@needs_sqlite
def test_sqlite_pragmas_are_applied():
    with engine.connect() as c:
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert c.exec_driver_sql("PRAGMA busy_timeout").scalar() >= 5000
        assert str(c.exec_driver_sql("PRAGMA journal_mode").scalar()).lower() == "wal"


@needs_sqlite
def test_foreign_keys_are_enforced(client):
    from sqlalchemy.exc import IntegrityError

    with engine.begin() as c:
        with pytest.raises(IntegrityError):
            c.execute(text("insert into users (org_id,email,name,password_hash,role,is_active,created_at,token_version) values (999999,'fk@x.co','x','x','member',1,'2026-01-01',0)"))


def test_missing_tables_give_an_actionable_error(tmp_path):
    empty = create_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        check_schema_ready(empty)
    empty.dispose()


# ------------------------------------------------------------------ migrations on SQLite
def _alembic(db_file: Path, *args):
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_file.as_posix()}", "AUTO_CREATE_TABLES": "false", "SEED_DEMO_DATA": "false"}
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR, env=env, capture_output=True, text=True)


def test_alembic_upgrade_downgrade_roundtrip_and_no_drift_on_sqlite(tmp_path):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    import app.models  # noqa: F401
    from app.db.session import Base

    db = tmp_path / "mig test.db"
    up = _alembic(db, "upgrade", "head")
    assert up.returncode == 0, up.stderr[-800:]
    eng = create_engine(f"sqlite:///{db.as_posix()}")
    assert set(inspect(eng).get_table_names()) >= {"users", "leads", "campaigns", "messages", "alembic_version"}
    with eng.connect() as c:
        assert compare_metadata(MigrationContext.configure(c, opts={"compare_type": False}), Base.metadata) == []
    eng.dispose()

    down = _alembic(db, "downgrade", "base")
    assert down.returncode == 0, down.stderr[-800:]
    again = _alembic(db, "upgrade", "head")
    assert again.returncode == 0, again.stderr[-800:]


def test_app_boots_registers_and_logs_in_on_a_migrated_sqlite_file(tmp_path):
    """The exact local flow from the README: migrate, start the app, seed demo data, register, log in, use an encrypted integration."""
    db = tmp_path / "fresh.db"
    assert _alembic(db, "upgrade", "head").returncode == 0
    code = r"""
import os, json
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as c:
    demo = c.post('/api/v1/auth/login', json={'email': 'demo@aioutreach.pro', 'password': 'Demo1234!'})
    r = c.post('/api/v1/auth/register', json={'email': 'local@dev-test.com', 'name': 'Local Dev', 'password': 'Password123', 'organization_name': 'Local Org'})
    h = {'Authorization': 'Bearer ' + r.json()['access_token']}
    me = c.get('/api/v1/auth/me', headers=h)
    integ = c.post('/api/v1/integrations', headers=h, json={'label': 'Mailbox', 'username': 'me@x.com', 'password': 'super-secret-pw', 'smtp_host': 'smtp.example.com'})
    listing = c.get('/api/v1/integrations', headers=h)
    print(json.dumps({'demo': demo.status_code, 'reg': r.status_code, 'me': me.status_code, 'integ': integ.status_code,
                      'leak': 'super-secret-pw' in listing.text + integ.text}))
"""
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db.as_posix()}", "AUTO_CREATE_TABLES": "false", "SEED_DEMO_DATA": "true",
           "ENABLE_SCHEDULER": "false", "ENCRYPTION_KEY": Fernet.generate_key().decode(), "APP_ENV": "development", "ALLOW_REGISTRATION": "true"}
    r = subprocess.run([sys.executable, "-c", code], cwd=BACKEND_DIR, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1500:]
    out = r.stdout.strip().splitlines()[-1]
    assert out == '{"demo": 200, "reg": 201, "me": 200, "integ": 201, "leak": false}', out


def test_app_without_migration_fails_with_clear_message(tmp_path):
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{(tmp_path / 'none.db').as_posix()}", "AUTO_CREATE_TABLES": "false",
           "SEED_DEMO_DATA": "true", "ENABLE_SCHEDULER": "false", "APP_ENV": "development"}
    code = "from fastapi.testclient import TestClient\nfrom app.main import app\nwith TestClient(app): pass"
    r = subprocess.run([sys.executable, "-c", code], cwd=BACKEND_DIR, env=env, capture_output=True, text=True)
    assert r.returncode != 0 and "alembic upgrade head" in r.stderr
