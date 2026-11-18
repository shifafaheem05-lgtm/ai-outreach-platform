"""Regression tests for bugs found during the independent QA pass."""
import itertools

import pytest

_n = itertools.count(1)


@pytest.fixture()
def acct(client):
    n = next(_n)
    r = client.post("/api/v1/auth/register", json={"email": f"qa{n}@qa-reg.com", "name": "QA", "password": "Password123", "organization_name": f"QA{n}"})
    return client, {"Authorization": f"Bearer {r.json()['access_token']}"}, n


@pytest.mark.parametrize("pw", ["12345678", "        ", "abcdefgh", "Abcdef12 "])
def test_weak_passwords_rejected(client, pw):
    r = client.post("/api/v1/auth/register", json={"email": f"w{abs(hash(pw))}@qa-reg.com", "name": "A", "password": pw, "organization_name": "O"})
    assert r.status_code == 422


@pytest.mark.parametrize("body", [
    {"company_name": "   "},
    {"company_name": "X", "website": "javascript:alert(1)"},
    {"company_name": "X", "website": "ftp://x.com"},
    {"company_name": "X", "website": "not a site"},
    {"company_name": "X", "email": "bad"},
])
def test_invalid_lead_rejected(acct, body):
    c, h, _ = acct
    assert c.post("/api/v1/leads", headers=h, json=body).status_code == 422


def test_null_bytes_stripped(acct):
    c, h, _ = acct
    r = c.post("/api/v1/leads", headers=h, json={"company_name": "a\u0000b"})
    assert r.status_code == 201 and r.json()["company_name"] == "ab"


def test_partial_update_does_not_wipe_fields(acct):
    c, h, n = acct
    lead = c.post("/api/v1/leads", headers=h, json={"company_name": "Keep Co", "website": f"keep{n}.com", "email": f"hi@keep{n}.com"}).json()
    r = c.patch(f"/api/v1/leads/{lead['id']}", headers=h, json={"industry": "SaaS"})
    assert r.status_code == 200
    assert r.json()["industry"] == "SaaS"
    assert r.json()["email"] == f"hi@keep{n}.com" and r.json()["website"] == f"https://keep{n}.com"


def test_patch_rejects_bad_values(acct):
    c, h, n = acct
    lead = c.post("/api/v1/leads", headers=h, json={"company_name": "P Co"}).json()
    for body in ({"email": "nope"}, {"website": "javascript:1"}, {"company_name": " "}):
        assert c.patch(f"/api/v1/leads/{lead['id']}", headers=h, json=body).status_code == 422


def test_blank_campaign_name_rejected(acct):
    c, h, _ = acct
    assert c.post("/api/v1/campaigns", headers=h, json={"name": "   "}).status_code == 422
    cid = c.post("/api/v1/campaigns", headers=h, json={"name": "Ok"}).json()["id"]
    assert c.patch(f"/api/v1/campaigns/{cid}", headers=h, json={"name": " "}).status_code == 422


def test_csv_ignores_bad_website_and_keeps_row(acct):
    c, h, n = acct
    csv = f"company,email,website\nA{n},bad,javascript:x\n"
    r = c.post("/api/v1/leads/import-csv", headers=h, files={"file": ("a.csv", csv.encode(), "text/csv")})
    assert r.status_code == 200 and r.json()["created"] == 1
    assert len(r.json()["errors"]) == 2


def test_video_patch_keeps_company_name(acct):
    c, h, _ = acct
    lead = c.post("/api/v1/leads", headers=h, json={"company_name": "Vid Co"}).json()
    v = c.post("/api/v1/videos/script", headers=h, json={"lead_id": lead["id"]}).json()
    assert c.patch(f"/api/v1/videos/{v['id']}/views", headers=h, json={"views": 3}).json()["company_name"] == "Vid Co"
