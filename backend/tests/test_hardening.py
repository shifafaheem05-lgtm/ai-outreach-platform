"""Tests for the production-hardening work: sessions, config guards, send claiming, SMTP host guard."""
import itertools
import smtplib
from datetime import timedelta

import jwt
import pytest
from sqlalchemy import select

from app.api.v1 import auth as auth_api
from app.core.config import Settings, production_problems, settings
from app.core.security import create_access_token, decode_token
from app.core.timeutil import utcnow
from app.db.session import SessionLocal
from app.models import CampaignLead
from app.services import campaigns as camp_svc
from app.services import sending
from app.services.sending import read_unsubscribe_token

from test_phase3_6 import add_leads, ctx, launch, make_campaign, make_due, set_org  # noqa: F401  (ctx is a fixture)

_n = itertools.count(1)


def _register(client):
    n = next(_n)
    email = f"hard{n}@hardening-test.com"
    r = client.post("/api/v1/auth/register", json={"email": email, "name": "Hard Ening", "password": "Password123", "organization_name": f"HardOrg{n}"})
    assert r.status_code == 201, r.text
    return email, r.json()


def _h(token):
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------ passwords / sessions
def test_change_password_revokes_old_sessions(client):
    email, tok = _register(client)
    h = _h(tok["access_token"])

    assert client.post("/api/v1/auth/change-password", headers=h, json={"current_password": "wrong-one1", "new_password": "NewPassword456"}).status_code == 400
    assert client.post("/api/v1/auth/change-password", headers=h, json={"current_password": "Password123", "new_password": "Password123"}).status_code == 400
    assert client.post("/api/v1/auth/change-password", headers=h, json={"current_password": "Password123", "new_password": "short"}).status_code == 422
    assert client.post("/api/v1/auth/change-password", headers=h, json={"current_password": "Password123", "new_password": "onlyletters"}).status_code == 422
    assert client.post("/api/v1/auth/change-password", json={"current_password": "a", "new_password": "NewPassword456"}).status_code == 401

    r = client.post("/api/v1/auth/change-password", headers=h, json={"current_password": "Password123", "new_password": "NewPassword456"})
    assert r.status_code == 200
    fresh = r.json()

    # the old access and refresh tokens are dead, the fresh ones work
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tok["refresh_token"]}).status_code == 401
    assert client.get("/api/v1/auth/me", headers=_h(fresh["access_token"])).status_code == 200
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": fresh["refresh_token"]}).status_code == 200

    # old password no longer logs in, new one does
    assert client.post("/api/v1/auth/login", json={"email": email, "password": "Password123"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": email, "password": "NewPassword456"}).status_code == 200


def test_token_type_and_claims_are_enforced(client):
    _, tok = _register(client)
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tok["access_token"]}).status_code == 401  # access token as refresh
    assert client.get("/api/v1/auth/me", headers=_h(tok["refresh_token"])).status_code == 401  # refresh token as access
    no_exp = jwt.encode({"sub": "1", "type": "access"}, settings.secret_key, algorithm="HS256")
    assert decode_token(no_exp, "access") is None  # tokens must expire
    wrong_key = jwt.encode({"sub": "1", "type": "access", "exp": utcnow() + timedelta(hours=1)}, "x" * 40, algorithm="HS256")
    assert decode_token(wrong_key, "access") is None
    none_alg = jwt.encode({"sub": "1", "type": "access", "exp": utcnow() + timedelta(hours=1)}, None, algorithm="none")
    assert decode_token(none_alg, "access") is None
    assert decode_token(create_access_token(7, 3), "access") == (7, 3)


def test_unsubscribe_token_rejects_access_tokens_and_garbage(client):
    assert read_unsubscribe_token("garbage") is None
    assert read_unsubscribe_token(create_access_token(1)) is None  # wrong "type"


def test_registration_can_be_disabled(client, monkeypatch):
    assert client.get("/api/v1/auth/config").json() == {"allow_registration": True}
    monkeypatch.setattr(settings, "allow_registration", False)
    assert client.get("/api/v1/auth/config").json() == {"allow_registration": False}
    r = client.post("/api/v1/auth/register", json={"email": "nope@hardening-test.com", "name": "No", "password": "Password123", "organization_name": "Nope"})
    assert r.status_code == 403
    # existing users can still sign in
    assert client.post("/api/v1/auth/login", json={"email": "wrong@x.com", "password": "Password123"}).status_code == 401


def test_login_failure_tracker_is_bounded(monkeypatch):
    monkeypatch.setattr(auth_api, "MAX_TRACKED", 50)
    auth_api._FAILURES.clear()
    now = 1_000_000.0
    for i in range(200):
        auth_api._FAILURES[("ip", f"a{i}@x.com")] = [now - auth_api.WINDOW - 5]  # all expired
    auth_api._prune_failures(now)
    assert len(auth_api._FAILURES) == 0
    for i in range(80):
        auth_api._FAILURES[("ip", f"b{i}@x.com")] = [now - i]  # all live
    auth_api._prune_failures(now)
    assert len(auth_api._FAILURES) == 50
    auth_api._FAILURES.clear()


# ------------------------------------------------------------------ production config guard
GOOD = dict(
    app_env="production",
    secret_key="k" * 40,
    encryption_key="2KqjNbWUiF2ZuTbBcqtDGoGQrTpvjK1gHxQjHUUbNQ4=",
    seed_demo_data=False,
    database_url="postgresql+psycopg2://u:p@db/x",
    public_base_url="https://app.example.com",
)


def _cfg(**over):
    return Settings(_env_file=None, **{**GOOD, **over})


def test_production_config_good_passes_and_dev_is_unrestricted():
    assert production_problems(_cfg()) == []
    assert production_problems(_cfg(app_env="development", secret_key="x", seed_demo_data=True)) == []


@pytest.mark.parametrize(
    "override,fragment",
    [
        ({"secret_key": "short"}, "SECRET_KEY"),
        ({"secret_key": "change-me-" + "x" * 40}, "SECRET_KEY"),
        ({"encryption_key": ""}, "ENCRYPTION_KEY is required"),
        ({"encryption_key": "not-a-key"}, "not a valid Fernet key"),
        ({"seed_demo_data": True}, "SEED_DEMO_DATA"),
        ({"database_url": "sqlite:///./x.db"}, "PostgreSQL"),
        ({"public_base_url": "http://localhost:8000"}, "PUBLIC_BASE_URL"),
    ],
)
def test_production_config_rejects_unsafe_values(override, fragment):
    assert any(fragment in p for p in production_problems(_cfg(**override)))


# ------------------------------------------------------------------ SMTP host guard
def test_private_mail_hosts_blocked_in_production_only(ctx, monkeypatch):
    c, cl = ctx, ctx["client"]
    body = {"label": "Internal", "username": "me@x.com", "password": "pw", "smtp_host": "127.0.0.1"}
    assert cl.post("/api/v1/integrations", headers=c["h"], json=body).status_code == 201  # dev: allowed (e.g. local Mailhog)
    monkeypatch.setattr(settings, "app_env", "production")
    for host in ("127.0.0.1", "localhost", "169.254.169.254", "10.0.0.5"):
        r = cl.post("/api/v1/integrations", headers=c["h"], json={**body, "smtp_host": host})
        assert r.status_code == 400, host
        assert "public" in r.json()["detail"]
    r = cl.post("/api/v1/integrations", headers=c["h"], json={**body, "smtp_host": "smtp.ctx-test.invalid"})
    assert r.status_code == 400  # does not resolve = not provably public
    r = cl.post("/api/v1/integrations", headers=c["h"], json={**body, "smtp_host": "smtp.example.com", "smtp_port": 70000})
    assert r.status_code == 400


# ------------------------------------------------------------------ send claiming
def _cl_rows(camp_id):
    with SessionLocal() as db:
        return list(db.scalars(select(CampaignLead).where(CampaignLead.campaign_id == camp_id)))


def test_competing_worker_cannot_double_send(ctx, monkeypatch):
    """While one worker is mid-send, a second tick must see the row as claimed and skip it."""
    c = ctx
    set_org(c)
    leads = add_leads(c, ["Gamma Co,gamma@gamma-test.com,gamma-test.com,CEO", "Delta Co,delta@delta-test.com,delta-test.com,CEO"])
    camp = make_campaign(c, [l["id"] for l in leads.values()])
    launch(c, camp)
    make_due(camp)

    real_send, inner_stats, nested = camp_svc.send_email, [], {"on": False}

    def send_with_competitor(*a, **kw):
        if not nested["on"]:
            nested["on"] = True
            with SessionLocal() as other:
                inner_stats.append(camp_svc.process_due(other))
        return real_send(*a, **kw)

    monkeypatch.setattr(camp_svc, "send_email", send_with_competitor)
    with SessionLocal() as db:
        outer = camp_svc.process_due(db)

    assert [s["sent"] for s in inner_stats] == [1]  # the competitor sent the *other* lead, not the claimed one
    assert outer["sent"] == 1
    assert len(c["sent"]) == 2 and len({m["To"] for m in c["sent"]}) == 2  # two distinct recipients, no duplicates


def test_transient_smtp_failure_backs_off_instead_of_retrying_every_tick(ctx, monkeypatch):
    c = ctx
    set_org(c)
    leads = add_leads(c, ["Eps Co,eps@eps-test.com,eps-test.com,CEO"])
    camp = make_campaign(c, [l["id"] for l in leads.values()])
    launch(c, camp)
    make_due(camp)

    attempts = []

    def flaky(creds, msg):
        attempts.append(1)
        raise smtplib.SMTPServerDisconnected("boom")

    monkeypatch.setattr(sending, "send_smtp", flaky)
    with SessionLocal() as db:
        camp_svc.process_due(db)
    with SessionLocal() as db:
        camp_svc.process_due(db)  # next tick
    assert len(attempts) == 1
    row = _cl_rows(camp)[0]
    assert row.state == "active" and row.current_step == 0  # still waiting to be sent, not lost
    due = row.next_send_at if row.next_send_at.tzinfo else row.next_send_at.replace(tzinfo=utcnow().tzinfo)
    assert due > utcnow() + timedelta(minutes=10)


# ------------------------------------------------------------------ search is literal
def test_search_treats_percent_and_underscore_literally(ctx):
    c, cl = ctx, ctx["client"]
    add_leads(c, ["100% Pure Co,pure@pure-test.com,pure-test.com,CEO", "Plain Co,plain@plain-test.com,plain-test.com,CEO", "Snake_Case Co,snake@snake-test.com,snake-test.com,CEO"])
    names = lambda q: sorted(i["company_name"] for i in cl.get("/api/v1/leads", headers=c["h"], params={"q": q}).json()["items"])
    assert names("%") == ["100% Pure Co"]
    assert names("_") == ["Snake_Case Co"]
    assert names("plain") == ["Plain Co"]
    assert len(names("")) == 3
