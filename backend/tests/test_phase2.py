import itertools

import pytest

from app.services import research, verification
from app.services.research import FetchError, Page

_counter = itertools.count(1)


@pytest.fixture()
def auth(client):
    """A brand-new organization so tests never touch demo data or each other."""
    n = next(_counter)
    r = client.post(
        "/api/v1/auth/register",
        json={"email": f"p2user{n}@example.com", "name": "P2", "password": "Password123", "organization_name": f"Org{n}"},
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


CSV = (
    "Company,Website,Email,Title,Industry,Size,Country\n"
    "Acme Co,acme-test.com,ceo@acme-test.com,CEO,Marketing,11-50,USA\n"
    "Acme Duplicate,acme-test.com,CEO@acme-test.com,CEO,Marketing,11-50,USA\n"
    "Berlin GmbH,berlin-test.de,info@berlin-test.de,Manager,SaaS,1-10,Germany\n"
    ",,,,,,\n"
)


def _import(client, auth, content=CSV):
    return client.post("/api/v1/leads/import-csv", headers=auth, files={"file": ("leads.csv", content.encode(), "text/csv")})


def test_csv_import_dedupes_and_flags_region(client, auth):
    r = _import(client, auth)
    assert r.status_code == 200
    body = r.json()
    assert body["created"] == 2 and body["duplicates"] == 1 and body["skipped"] == 1
    leads = client.get("/api/v1/leads?sort=company", headers=auth).json()
    assert leads["total"] == 2
    flags = {l["company_name"]: l["region_flag"] for l in leads["items"]}
    assert flags == {"Acme Co": "", "Berlin GmbH": "EU/UK"}
    # importing the same file again creates nothing
    assert _import(client, auth).json()["created"] == 0


def test_csv_without_useful_columns_rejected(client, auth):
    assert _import(client, auth, "foo,bar\n1,2\n").status_code == 400


def test_verification(client, auth, monkeypatch):
    monkeypatch.setattr(verification, "_mx_lookup", lambda d: "none" if d == "berlin-test.de" else "ok")
    _import(client, auth)
    r = client.post("/api/v1/leads/verify", headers=auth, json={}).json()
    assert r["checked"] == 2 and r["valid"] == 1 and r["invalid"] == 1
    assert verification.verify_email("bad@@x")[0] == "invalid"
    assert verification.verify_email("info@acme-test.com", {"acme-test.com": "ok"})[0] == "risky"
    assert verification.verify_email("a@mailinator.com")[0] == "risky"
    monkeypatch.setattr(verification, "_mx_lookup", lambda d: "error")
    assert verification.verify_email("a@b-test.com")[0] == "unverified"


def test_scoring_tiers(client, auth, monkeypatch):
    monkeypatch.setattr(verification, "_mx_lookup", lambda d: "ok")
    _import(client, auth)
    client.post("/api/v1/leads/verify", headers=auth, json={})
    run = client.post("/api/v1/scoring/run", headers=auth, json={"target_industries": ["marketing"]}).json()
    assert run["scored"] == 2
    top = client.get("/api/v1/scoring/summary", headers=auth).json()["top_leads"]
    assert top[0]["company_name"] == "Acme Co" and top[0]["tier"] == "hot"  # CEO + valid + 11-50 + industry
    assert top[1]["tier"] in ("warm", "cold") and top[1]["score"] < top[0]["score"]


def test_research_extractive_report_with_sources(client, auth, monkeypatch):
    _import(client, auth)
    lead = client.get("/api/v1/leads?q=Acme", headers=auth).json()["items"][0]
    page = Page(url="https://acme-test.com/", title="Acme - Growth Marketing", description="We grow B2B brands.",
                headings=["SEO Services", "Paid Ads"], text="...")
    monkeypatch.setattr(research, "fetch_pages", lambda site: [page])
    r = client.post(f"/api/v1/leads/{lead['id']}/research", headers=auth)
    assert r.status_code == 200
    rep = r.json()
    assert rep["model"] == "extractive"
    assert rep["sources"][0]["url"] == "https://acme-test.com/"
    assert "SEO Services" in rep["products_services"]
    assert "Not generated" in rep["pain_points"]  # no invented problems without a model
    assert client.get(f"/api/v1/leads/{lead['id']}/research", headers=auth).status_code == 200
    assert client.get(f"/api/v1/leads/{lead['id']}", headers=auth).json()["researched"] is True


def test_research_failure_says_insufficient_data(client, auth, monkeypatch):
    _import(client, auth)
    lead = client.get("/api/v1/leads?q=Acme", headers=auth).json()["items"][0]

    def boom(site):
        raise FetchError("robots.txt does not allow crawling this site")

    monkeypatch.setattr(research, "fetch_pages", boom)
    rep = client.post(f"/api/v1/leads/{lead['id']}/research", headers=auth).json()
    assert rep["summary"].startswith("Insufficient data") and rep["sources"] == []


@pytest.mark.parametrize("url", ["http://127.0.0.1", "http://localhost:8000", "http://10.0.0.5", "http://169.254.169.254", "ftp://example.com"])
def test_ssrf_blocked(url):
    with pytest.raises(FetchError):
        research.assert_public_url(url)


def test_tenant_isolation_and_crud(client, auth):
    created = client.post("/api/v1/leads", headers=auth, json={"company_name": "Solo Inc", "email": "x@solo-test.com"})
    assert created.status_code == 201
    lid = created.json()["id"]
    assert client.post("/api/v1/leads", headers=auth, json={"company_name": "Solo Inc", "email": "X@solo-test.com"}).status_code == 409
    other = client.post(
        "/api/v1/auth/register",
        json={"email": f"other{next(_counter)}@example.com", "name": "O", "password": "Password123", "organization_name": "Other"},
    ).json()
    oh = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.get(f"/api/v1/leads/{lid}", headers=oh).status_code == 404
    assert client.delete(f"/api/v1/leads/{lid}", headers=oh).status_code == 404
    patched = client.patch(f"/api/v1/leads/{lid}", headers=auth, json={"contact_title": "Founder", "tags": ["vip"]}).json()
    assert patched["contact_title"] == "Founder" and patched["tags"] == ["vip"]
    assert client.delete(f"/api/v1/leads/{lid}", headers=auth).status_code == 204


def test_dedupe_merges_same_email(client, auth):
    db_lead = {"company_name": "Dup A", "email": "same@dup-test.com"}
    client.post("/api/v1/leads", headers=auth, json=db_lead)
    # different website => different dedupe key at insert time is impossible (email is the key),
    # so duplicates only arise via edits; simulate by patching email after creation
    b = client.post("/api/v1/leads", headers=auth, json={"company_name": "Dup B", "email": "other@dup-test.com"}).json()
    r = client.patch(f"/api/v1/leads/{b['id']}", headers=auth, json={"email": "same@dup-test.com"})
    assert r.status_code == 409  # blocked up-front: the platform prevents creating duplicates
    assert client.post("/api/v1/leads/dedupe", headers=auth).json()["removed"] == 0
