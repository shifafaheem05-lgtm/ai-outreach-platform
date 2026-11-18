import pytest

from app.db.seed import DEMO_EMAIL, DEMO_PASSWORD


def _login(client, email=DEMO_EMAIL, password=DEMO_PASSWORD):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return r


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_login_and_me(client):
    r = _login(client)
    assert r.status_code == 200
    token = r.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == DEMO_EMAIL
    assert me.json()["role"] == "admin"


def test_bad_password_rejected(client):
    assert _login(client, password="wrong-password").status_code == 401


def test_dashboard_requires_auth(client):
    assert client.get("/api/v1/dashboard/summary").status_code == 401


def test_dashboard_summary(client):
    token = _login(client).json()["access_token"]
    r = client.get("/api/v1/dashboard/summary", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()
    assert data["total_leads"] == 48
    assert data["emails_sent"] > 0
    assert 0 <= data["reply_rate"] <= 100
    assert len(data["activity"]) == 14
    assert sum(data["leads_by_tier"].values()) == 48
    assert len(data["campaigns"]) == 3


def test_register_creates_isolated_org(client):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "new@example.com", "name": "New", "password": "Password123", "organization_name": "NewCo"},
    )
    assert r.status_code == 201
    token = r.json()["access_token"]
    summary = client.get("/api/v1/dashboard/summary", headers={"Authorization": f"Bearer {token}"}).json()
    assert summary["total_leads"] == 0  # no leakage from the demo org
    dup = client.post(
        "/api/v1/auth/register",
        json={"email": "new@example.com", "name": "New", "password": "Password123", "organization_name": "NewCo"},
    )
    assert dup.status_code == 409


def test_refresh_token(client):
    tokens = _login(client).json()
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    # An access token must not be accepted as a refresh token
    bad = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert bad.status_code == 401
