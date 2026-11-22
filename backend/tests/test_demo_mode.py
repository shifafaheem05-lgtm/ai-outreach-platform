"""DEMO_MODE: a public demo that visitors can use safely (demo login + own workspace, but no real mail)."""
import itertools

import pytest

from app.api.v1 import auth as auth_api
from app.core.config import Settings, production_problems, settings
from app.core.demo import DEMO_EMAIL, DEMO_PASSWORD
from app.db.session import SessionLocal
from app.services import campaigns as camp_svc

STRONG = "x" * 48
_n = itertools.count(1)


@pytest.fixture()
def demo(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)


def _login(client, email=DEMO_EMAIL, password=DEMO_PASSWORD):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def _visitor(client):
    n = next(_n)
    r = client.post("/api/v1/auth/register", json={"email": f"visitor{n}@demo-visitor.com", "name": "Visitor", "password": "Password123", "organization_name": f"VisitorOrg{n}"})
    assert r.status_code == 201, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


MAILBOX = {"label": "x", "smtp_host": "smtp.gmail.com", "smtp_port": 465, "username": "a@b.com", "password": "secret", "security": "ssl"}


# ---------------------------------------------------------------- configuration guards
def test_demo_mode_is_off_by_default():
    assert Settings(_env_file=None).demo_mode is False


def test_demo_mode_needs_a_strong_secret_even_in_development():
    weak = Settings(_env_file=None, demo_mode=True, app_env="development", secret_key="dev-secret-change-me-not-for-production")
    assert any("SECRET_KEY" in p for p in production_problems(weak))
    ok = Settings(_env_file=None, demo_mode=True, app_env="development", secret_key=STRONG)
    assert production_problems(ok) == []


def test_demo_mode_cannot_run_as_production():
    cfg = Settings(_env_file=None, demo_mode=True, app_env="production", secret_key=STRONG)
    assert any("DEMO_MODE" in p for p in production_problems(cfg))


def test_normal_development_config_is_still_accepted():
    assert production_problems(Settings(_env_file=None, app_env="development")) == []


# ---------------------------------------------------------------- public config / login page
def test_auth_config_hides_demo_credentials_when_off(client):
    body = client.get("/api/v1/auth/config").json()
    assert body["demo_mode"] is False and "demo_password" not in body


def test_auth_config_offers_demo_login_when_on(client, demo):
    body = client.get("/api/v1/auth/config").json()
    assert body["demo_mode"] is True
    assert body["demo_email"] == DEMO_EMAIL and body["demo_password"] == DEMO_PASSWORD
    assert body["allow_registration"] is True


# ---------------------------------------------------------------- visitors can use it
def test_demo_login_shows_sample_data(client, demo):
    h = _login(client)
    assert client.get("/api/v1/leads", headers=h).json()["total"] > 0


def test_visitor_can_create_own_workspace_and_add_a_lead(client, demo):
    h = _visitor(client)
    r = client.post("/api/v1/leads", headers=h, json={"company_name": "Visitor Co", "email": "hi@visitor-co.com", "website": "visitor-co.com"})
    assert r.status_code == 201, r.text


# ---------------------------------------------------------------- protections
def test_shared_demo_account_cannot_be_locked(client, demo):
    h = _login(client)
    r = client.post("/api/v1/auth/change-password", headers=h, json={"current_password": DEMO_PASSWORD, "new_password": "Another1234"})
    assert r.status_code == 403
    assert client.post("/api/v1/settings/users", headers=h, json={"email": "x@y-demo.com", "name": "X", "password": "Password123", "role": "member"}).status_code == 403
    users = client.get("/api/v1/settings/users", headers=h).json()
    assert client.patch(f"/api/v1/settings/users/{users[0]['id']}", headers=h, json={"is_active": False}).status_code == 403
    _login(client)  # still works


def test_visitor_can_still_change_own_password(client, demo):
    h = _visitor(client)
    r = client.post("/api/v1/auth/change-password", headers=h, json={"current_password": "Password123", "new_password": "NewPassword456"})
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("who", ["demo", "visitor"])
def test_mailboxes_cannot_be_connected_in_demo(client, demo, who):
    h = _login(client) if who == "demo" else _visitor(client)
    assert client.post("/api/v1/integrations", headers=h, json=MAILBOX).status_code == 403
    assert client.post("/api/v1/integrations/1/test", headers=h).status_code == 403
    assert client.post("/api/v1/integrations/1/send-test", headers=h).status_code == 403


def test_mailbox_connection_still_works_outside_demo(client):
    h = _visitor(client)
    assert client.post("/api/v1/integrations", headers=h, json=MAILBOX).status_code == 201


def test_demo_never_sends_mail(demo):
    with SessionLocal() as db:
        assert camp_svc.process_due(db) == {"sent": 0, "bounced": 0, "blocked": 0, "waiting": 0}


def test_signups_are_capped_in_demo(client, demo, monkeypatch):
    monkeypatch.setattr(auth_api, "MAX_DEMO_USERS", 1)
    n = next(_n)
    r = client.post("/api/v1/auth/register", json={"email": f"capped{n}@demo-visitor.com", "name": "C", "password": "Password123", "organization_name": f"Cap{n}"})
    assert r.status_code == 403 and "limit" in r.json()["detail"]
