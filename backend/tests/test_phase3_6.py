import itertools
from datetime import timedelta
from email.message import EmailMessage

import pytest
from sqlalchemy import select

from app.core.timeutil import utcnow
from app.db.session import SessionLocal
from app.models import CampaignLead, Lead, Message, Organization, Suppression
from app.services import inbox as inbox_svc
from app.services import reply_classifier, sending
from app.services import video_scripts as vs
from app.services.sending import make_unsubscribe_token

_n = itertools.count(1)
LOOM = "https://www.loom.com/share/" + "0123456789abcdef" * 2


@pytest.fixture()
def ctx(client, monkeypatch):
    """Fresh org + a (fake) mailbox. `sent` collects every email the app tries to send."""
    n = next(_n)
    r = client.post("/api/v1/auth/register", json={"email": f"u{n}@ctx-test.com", "name": "Sam Sender", "password": "Password123", "organization_name": f"CtxOrg{n}"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    sent: list[EmailMessage] = []
    monkeypatch.setattr(sending, "send_smtp", lambda creds, msg: sent.append(msg))
    integ = client.post("/api/v1/integrations", headers=h, json={"label": "Test box", "username": "me@ctx-test.com", "password": "x", "smtp_host": "smtp.ctx-test.invalid"}).json()
    return {"h": h, "sent": sent, "integ": integ["id"], "client": client, "n": n}


def set_org(c, **extra):
    body = {"physical_address": "1 Test Street, Lahore, Pakistan", "sender_name": "Sam Sender", **extra}
    assert c["client"].patch("/api/v1/settings/org", headers=c["h"], json=body).status_code == 200


def add_leads(c, rows):
    csv = "company,email,website,title\n" + "\n".join(rows) + "\n"
    r = c["client"].post("/api/v1/leads/import-csv", headers=c["h"], files={"file": ("l.csv", csv.encode(), "text/csv")})
    assert r.status_code == 200, r.text
    items = c["client"].get("/api/v1/leads?page_size=100&sort=company", headers=c["h"]).json()["items"]
    return {l["company_name"]: l for l in items}


def make_campaign(c, lead_ids, intervals=(3,)):
    cl = c["client"]
    camp = cl.post("/api/v1/campaigns", headers=c["h"], json={"name": "Test", "sender_integration_id": c["integ"], "followup_intervals": list(intervals)}).json()
    assert cl.post(f"/api/v1/campaigns/{camp['id']}/leads", headers=c["h"], json={"lead_ids": lead_ids}).json()["added"] == len(lead_ids)
    assert cl.post(f"/api/v1/campaigns/{camp['id']}/generate-drafts", headers=c["h"], json={}).status_code == 200
    return camp["id"]


def launch(c, camp_id):
    cl = c["client"]
    assert cl.post(f"/api/v1/campaigns/{camp_id}/submit-approval", headers=c["h"]).status_code == 200
    assert cl.post(f"/api/v1/campaigns/{camp_id}/approve", headers=c["h"]).status_code == 200
    assert cl.post(f"/api/v1/campaigns/{camp_id}/start", headers=c["h"]).status_code == 200


def make_due(camp_id):
    with SessionLocal() as db:
        for cl in db.scalars(select(CampaignLead).where(CampaignLead.campaign_id == camp_id, CampaignLead.state == "active")):
            cl.next_send_at = utcnow() - timedelta(minutes=1)
        db.commit()


def raw_reply(from_addr, body, subject="Re: hello", extra=None):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = from_addr, "me@ctx-test.com", subject, f"<{next(_n)}@r.test>"
    for k, v in (extra or {}).items():
        m[k] = v
    m.set_content(body)
    return bytes(m)


def ingest(c, raw):
    with SessionLocal() as db:
        org = db.scalar(select(Organization).where(Organization.name == f"CtxOrg{c['n']}"))
        res = inbox_svc.process_raw(db, org, raw)
        db.commit()
    return res


# ---------------------------------------------------------------- campaigns ---
def test_full_campaign_flow(ctx):
    c, cl = ctx, ctx["client"]
    leads = add_leads(c, ["Alpha Co,alpha@alpha-test.com,alpha-test.com,CEO", "Beta Co,beta@beta-test.com,beta-test.com,Founder"])
    camp = make_campaign(c, [l["id"] for l in leads.values()])
    drafts = cl.get(f"/api/v1/campaigns/{camp}/drafts", headers=c["h"]).json()
    assert len(drafts) == 4  # 2 leads x (initial + 1 follow-up)

    bad = cl.post(f"/api/v1/campaigns/{camp}/submit-approval", headers=c["h"])
    assert bad.status_code == 400 and "postal address" in bad.json()["detail"]
    set_org(c)
    assert cl.post(f"/api/v1/campaigns/{camp}/start", headers=c["h"]).status_code == 409  # not approved
    launch(c, camp)

    stats = cl.post("/api/v1/campaigns/process-now", headers=c["h"]).json()
    assert stats["sent"] == 2 and len(c["sent"]) == 2
    first = c["sent"][0]
    assert first["List-Unsubscribe"].startswith("<http") and first["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    body = first.get_content()
    assert "1 Test Street" in body and "/unsubscribe/" in body

    # alpha replies asking for a call -> its sequence stops, beta continues
    res = ingest(c, raw_reply("alpha@alpha-test.com", "Sounds interesting, can we schedule a call on Thursday?\n\nOn Mon, Sam wrote:\n> old"))
    assert res["label"] == "meeting_requested"
    make_due(camp)
    stats = cl.post("/api/v1/campaigns/process-now", headers=c["h"]).json()
    assert stats["sent"] == 1
    assert "beta@beta-test.com" in str(c["sent"][-1]["To"]) and c["sent"][-1]["Subject"].startswith("Following up")
    assert c["sent"][-1]["In-Reply-To"]  # threaded under the first email
    states = {l["company_name"]: l["state"] for l in cl.get(f"/api/v1/campaigns/{camp}", headers=c["h"]).json()["leads"]}
    assert states == {"Alpha Co": "replied", "Beta Co": "completed"}
    assert cl.get("/api/v1/leads?q=Alpha", headers=c["h"]).json()["items"][0]["status"] == "meeting"
    assert cl.get(f"/api/v1/campaigns/{camp}", headers=c["h"]).json()["status"] == "completed"


def test_unsubscribe_is_post_only_and_stops_sending(ctx):
    c, cl = ctx, ctx["client"]
    set_org(c)
    leads = add_leads(c, ["Gamma Co,gamma@gamma-test.com,,CEO"])
    camp = make_campaign(c, [leads["Gamma Co"]["id"]])
    launch(c, camp)
    with SessionLocal() as db:
        org_id = db.scalar(select(Organization.id).where(Organization.name == f"CtxOrg{c['n']}"))
    token = make_unsubscribe_token(org_id, "gamma@gamma-test.com")
    page = cl.get(f"/unsubscribe/{token}")  # scanners may prefetch this; it must not unsubscribe
    assert page.status_code == 200 and "gamma@gamma-test.com" in page.text
    assert cl.get("/api/v1/leads?q=Gamma", headers=c["h"]).json()["items"][0]["status"] == "new"
    assert cl.post(f"/unsubscribe/{token}").status_code == 200
    assert cl.get("/api/v1/leads?q=Gamma", headers=c["h"]).json()["items"][0]["status"] == "unsubscribed"
    cl.post("/api/v1/campaigns/process-now", headers=c["h"])
    assert c["sent"] == []
    assert cl.get("/unsubscribe/not-a-token").status_code == 400


def test_sending_limits_enforced(ctx):
    c, cl = ctx, ctx["client"]
    set_org(c, hourly_send_limit=1)
    leads = add_leads(c, ["L1 Co,l1@lim-test.com,,CEO", "L2 Co,l2@lim-test.com,,CEO", "L3 Co,l3@lim-test.com,,CEO"])
    camp = make_campaign(c, [l["id"] for l in leads.values()], intervals=())
    launch(c, camp)
    cl.post("/api/v1/campaigns/process-now", headers=c["h"])
    assert len(c["sent"]) == 1


def test_suppressed_lead_cannot_be_added_or_sent_manually(ctx):
    c, cl = ctx, ctx["client"]
    set_org(c)
    leads = add_leads(c, ["Blocked Co,blocked@blk-test.com,,CEO"])
    lid = leads["Blocked Co"]["id"]
    with SessionLocal() as db:
        oid = db.scalar(select(Organization.id).where(Organization.name == f"CtxOrg{c['n']}"))
        db.add(Suppression(org_id=oid, email="blocked@blk-test.com", reason="manual"))
        db.commit()
    camp = cl.post("/api/v1/campaigns", headers=c["h"], json={"name": "X"}).json()
    r = cl.post(f"/api/v1/campaigns/{camp['id']}/leads", headers=c["h"], json={"lead_ids": [lid]}).json()
    assert r["added"] == 0 and "suppressed" in r["skipped"][0]["reason"]
    d = cl.post("/api/v1/emails/generate", headers=c["h"], json={"lead_id": lid, "variants": ["short"]}).json()[0]
    assert cl.post(f"/api/v1/emails/drafts/{d['id']}/send", headers=c["h"], json={"confirm": True}).status_code == 400
    assert c["sent"] == []


def test_manual_send_needs_confirm_and_no_placeholders(ctx):
    c, cl = ctx, ctx["client"]
    set_org(c)
    lid = add_leads(c, ["Delta Co,delta@delta-test.com,,CEO"])["Delta Co"]["id"]
    d = cl.post("/api/v1/emails/generate", headers=c["h"], json={"lead_id": lid, "tone": "friendly"}).json()
    assert [x["variant"] for x in d] == ["short", "medium", "detailed"] and len({x["subject"] for x in d}) == 3
    did = d[1]["id"]
    assert cl.post(f"/api/v1/emails/drafts/{did}/send", headers=c["h"], json={}).status_code == 400
    cl.patch(f"/api/v1/emails/drafts/{did}", headers=c["h"], json={"body": "Hi,\n[ADD DETAILS: x]\nBest"})
    assert cl.post(f"/api/v1/emails/drafts/{did}/send", headers=c["h"], json={"confirm": True}).status_code == 400
    cl.patch(f"/api/v1/emails/drafts/{did}", headers=c["h"], json={"body": "Hi,\nQuick hello.\nBest"})
    assert cl.post(f"/api/v1/emails/drafts/{did}/send", headers=c["h"], json={"confirm": True}).status_code == 200
    assert len(c["sent"]) == 1
    assert cl.post(f"/api/v1/emails/drafts/{did}/send", headers=c["h"], json={"confirm": True}).status_code == 409  # no double send
    assert any(a["entity_type"] == "email" and a["status"] == "approved" for a in cl.get("/api/v1/approvals", headers=c["h"]).json())


def test_cannot_edit_approved_campaign_drafts(ctx):
    c, cl = ctx, ctx["client"]
    set_org(c)
    leads = add_leads(c, ["Eps Co,eps@eps-test.com,,CEO"])
    camp = make_campaign(c, [leads["Eps Co"]["id"]])
    launch(c, camp)
    did = cl.get(f"/api/v1/campaigns/{camp}/drafts", headers=c["h"]).json()[0]["id"]
    assert cl.patch(f"/api/v1/emails/drafts/{did}", headers=c["h"], json={"body": "changed"}).status_code == 409


# -------------------------------------------------------------------- videos ---
def test_video_workflow(ctx):
    c, cl = ctx, ctx["client"]
    set_org(c)
    lid = add_leads(c, ["Zed Co,zed@zed-test.com,zed-test.com,CEO"])["Zed Co"]["id"]
    caps = cl.get("/api/v1/videos/capabilities", headers=c["h"]).json()
    assert caps["loom_api_upload"] is False and caps["ai_voiceover"] is False
    v = cl.post("/api/v1/videos/script", headers=c["h"], json={"lead_id": lid}).json()
    assert v["status"] == "awaiting_recording" and v["checklist"] and all(s["requires_user"] for s in v["checklist"][:6])
    assert 100 <= v["word_count"] <= 260
    vid = v["id"]
    assert cl.patch(f"/api/v1/videos/{vid}/link", headers=c["h"], json={"loom_url": "https://evil.example/share/abc"}).status_code == 400
    ok = cl.patch(f"/api/v1/videos/{vid}/link", headers=c["h"], json={"loom_url": LOOM + "?sid=1"}).json()
    assert ok["loom_url"] == LOOM and ok["status"] == "published" and ok["views"] is None
    assert "svg" in cl.get(f"/api/v1/videos/{vid}/cover.svg", headers=c["h"]).headers["content-type"]
    d = cl.post("/api/v1/emails/generate", headers=c["h"], json={"lead_id": lid, "variants": ["short"]}).json()[0]
    assert "{{video_link}}" in cl.post(f"/api/v1/emails/drafts/{d['id']}/insert-video", headers=c["h"], json={"video_id": vid}).json()["body"]
    assert cl.post(f"/api/v1/emails/drafts/{d['id']}/send", headers=c["h"], json={"confirm": True}).status_code == 200
    assert LOOM in c["sent"][0].get_content()


def test_video_link_validation_unit():
    assert vs.normalize_loom_url("loom.com/share/abc") is None
    assert vs.normalize_loom_url(LOOM.upper().replace("HTTPS", "https")) == LOOM
    assert "&lt;" in vs.thumbnail_svg("A<b>", "x", "me")


# --------------------------------------------------------------------- inbox ---
@pytest.mark.parametrize("text,label", [
    ("Not interested, thanks.", "not_interested"),
    ("What is your pricing? Do you have case studies?", "need_more_information"),
    ("Let's schedule a call next Tuesday", "meeting_requested"),
    ("Please reach back out next quarter.", "follow_up_later"),
    ("I'm out of the office until Monday.", "out_of_office"),
    ("Yes, sounds great, I'm interested", "interested"),
])
def test_classifier_rules(text, label):
    assert reply_classifier.classify("Re: hi", text)["label"] == label


def test_opt_out_reply_suppresses_and_ooo_does_not_stop(ctx):
    c, cl = ctx, ctx["client"]
    set_org(c)
    leads = add_leads(c, ["Away Co,away@away-test.com,,CEO", "Quit Co,quit@quit-test.com,,CEO"])
    camp = make_campaign(c, [l["id"] for l in leads.values()])
    launch(c, camp)
    cl.post("/api/v1/campaigns/process-now", headers=c["h"])
    ooo = ingest(c, raw_reply("away@away-test.com", "I am away.", extra={"Auto-Submitted": "auto-replied"}))
    assert ooo["label"] == "out_of_office"
    out = ingest(c, raw_reply("quit@quit-test.com", "Please unsubscribe me and stop emailing."))
    assert out["opt_out"] is True
    states = {l["company_name"]: l["state"] for l in cl.get(f"/api/v1/campaigns/{camp}", headers=c["h"]).json()["leads"]}
    assert states == {"Away Co": "active", "Quit Co": "opted_out"}
    assert cl.get("/api/v1/leads?q=Quit", headers=c["h"]).json()["items"][0]["status"] == "unsubscribed"
    assert ingest(c, raw_reply("stranger@unknown-test.com", "hello")) is None  # unknown senders are ignored


def test_bounce_notice_marks_invalid_and_suppresses(ctx):
    c, cl = ctx, ctx["client"]
    add_leads(c, ["Gone Co,gone@gone-test.com,,CEO"])
    raw = raw_reply("MAILER-DAEMON@mail.test", "Delivery failed.\nFinal-Recipient: rfc822; gone@gone-test.com\nAction: failed", "Undelivered")
    assert ingest(c, raw) == {"type": "bounce"}
    lead = cl.get("/api/v1/leads?q=Gone", headers=c["h"]).json()["items"][0]
    assert lead["email_status"] == "invalid"
    with SessionLocal() as db:
        assert db.scalar(select(Suppression.id).where(Suppression.email == "gone@gone-test.com"))


def test_inbox_reply_requires_confirm(ctx):
    c, cl = ctx, ctx["client"]
    set_org(c)
    add_leads(c, ["Rep Co,rep@rep-test.com,,CEO"])
    ingest(c, raw_reply("rep@rep-test.com", "Interested, tell me more about pricing."))
    msg = cl.get("/api/v1/inbox", headers=c["h"]).json()[0]
    assert msg["label"] and msg["suggested_response"]
    url = f"/api/v1/inbox/{msg['id']}/reply"
    assert cl.post(url, headers=c["h"], json={"subject": "Re", "body": "Thanks"}).status_code == 400
    assert cl.post(url, headers=c["h"], json={"subject": "Re", "body": "Thanks [ADD WHEN]", "confirm": True}).status_code == 400
    assert c["sent"] == []
    assert cl.post(url, headers=c["h"], json={"subject": "Re: hi", "body": "Thanks, here is more.", "confirm": True}).status_code == 200
    assert len(c["sent"]) == 1
    assert any(a["entity_type"] == "reply" for a in cl.get("/api/v1/approvals", headers=c["h"]).json())


def test_followups_due_and_generate(ctx):
    c, cl = ctx, ctx["client"]
    set_org(c)
    lid = add_leads(c, ["Old Co,old@old-test.com,,CEO"])["Old Co"]["id"]
    with SessionLocal() as db:
        oid = db.scalar(select(Organization.id).where(Organization.name == f"CtxOrg{c['n']}"))
        db.add(Message(org_id=oid, lead_id=lid, direction="out", subject="Hello", body="Hi", status="sent", sent_at=utcnow() - timedelta(days=8), provider_message_id="<old@x>"))
        db.get(Lead, lid).status = "contacted"
        db.commit()
    due = cl.get("/api/v1/followups/due", headers=c["h"]).json()
    assert [x["company_name"] for x in due["needs_followup"]] == ["Old Co"] and due["needs_followup"][0]["days_waiting"] >= 8
    draft = cl.post("/api/v1/followups/generate", headers=c["h"], json={"lead_id": lid}).json()
    assert draft["subject"].startswith("Following up") and draft["status"] == "draft"
    assert c["sent"] == []  # generating never sends


# ------------------------------------------------------- CRM / analytics etc ---
def test_crm_notes_and_exports(ctx):
    c, cl = ctx, ctx["client"]
    add_leads(c, ['"=HYPERLINK(""http://x"")",evil@evil-test.com,,CEO'])
    lead = cl.get("/api/v1/leads", headers=c["h"]).json()["items"][0]
    note = cl.post(f"/api/v1/crm/leads/{lead['id']}/notes", headers=c["h"], json={"body": "Met at conference"}).json()
    prof = cl.get(f"/api/v1/crm/leads/{lead['id']}", headers=c["h"]).json()
    assert prof["notes"][0]["body"] == "Met at conference" and prof["conversation"] == []
    assert cl.delete(f"/api/v1/crm/leads/{lead['id']}/notes/{note['id']}", headers=c["h"]).status_code == 204
    csv = cl.get("/api/v1/crm/export?format=csv", headers=c["h"])
    assert csv.status_code == 200 and "'=HYPERLINK" in csv.text  # formula injection neutralised
    xlsx = cl.get("/api/v1/crm/export?format=xlsx", headers=c["h"])
    assert xlsx.content[:2] == b"PK" and "spreadsheetml" in xlsx.headers["content-type"]
    assert cl.get("/api/v1/crm/export?format=pdf", headers=c["h"]).status_code == 400


def test_analytics_endpoints(ctx):
    c, cl = ctx, ctx["client"]
    set_org(c)
    leads = add_leads(c, ["An Co,an@an-test.com,,CEO"])
    camp = make_campaign(c, [leads["An Co"]["id"]], intervals=())
    launch(c, camp)
    cl.post("/api/v1/campaigns/process-now", headers=c["h"])
    ingest(c, raw_reply("an@an-test.com", "Let's schedule a call"))
    row = cl.get("/api/v1/analytics/campaigns", headers=c["h"]).json()[0]
    assert (row["sent"], row["replied"], row["meetings"], row["reply_rate"]) == (1, 1, 1, 100.0)
    ov = cl.get("/api/v1/analytics/overview", headers=c["h"]).json()
    assert ov["replies_by_label"] == {"meeting_requested": 1} and ov["delivery_rate"] == 100.0 and ov["notes"]


def test_settings_roles_and_validation(ctx):
    c, cl = ctx, ctx["client"]
    assert cl.patch("/api/v1/settings/org", headers=c["h"], json={"daily_send_limit": 5000}).status_code == 422
    me = cl.get("/api/v1/auth/me", headers=c["h"]).json()
    m = cl.post("/api/v1/settings/users", headers=c["h"], json={"email": f"m{c['n']}@ctx-test.com", "name": "Mem", "password": "Password123", "role": "member"}).json()
    tok = cl.post("/api/v1/auth/login", json={"email": m["email"], "password": "Password123"}).json()["access_token"]
    mh = {"Authorization": f"Bearer {tok}"}
    assert cl.patch("/api/v1/settings/org", headers=mh, json={"name": "Hax"}).status_code == 403
    assert cl.post("/api/v1/campaigns/process-now", headers=mh).status_code == 403
    assert cl.get("/api/v1/settings/audit", headers=mh).status_code == 403
    assert cl.patch(f"/api/v1/settings/users/{me['id']}", headers=c["h"], json={"role": "member"}).status_code == 409  # last admin
    ready = cl.get("/api/v1/settings/readiness", headers=c["h"]).json()
    assert ready["ready"] is False and {x["id"]: x["ok"] for x in ready["checks"]}["address"] is False
    assert any(a["action"] == "user.create" for a in cl.get("/api/v1/settings/audit", headers=c["h"]).json())


def test_integration_secrets_never_returned(ctx):
    c, cl = ctx, ctx["client"]
    rows = cl.get("/api/v1/integrations", headers=c["h"]).json()
    assert rows and "password" not in str(rows) and rows[0]["from_email"] == "me@ctx-test.com"
    gm = cl.post("/api/v1/integrations", headers=c["h"], json={"label": "G", "preset": "gmail", "username": "a@gmail.com", "password": "app pw"}).json()
    assert gm["smtp_host"] == "smtp.gmail.com" and gm["imap_host"] == "imap.gmail.com" and gm["status"] == "untested"


def test_assistant(ctx):
    c, cl = ctx, ctx["client"]
    set_org(c)
    add_leads(c, ["Texas Marketing Agency,tx@txm-test.com,,CEO"])
    find = cl.post("/api/v1/assistant/command", headers=c["h"], json={"command": "Find 100 marketing agencies in the USA"}).json()
    assert find["intent"] == "search" and len(find["data"]) == 1 and "can't discover" in find["message"]
    blocked = cl.post("/api/v1/assistant/command", headers=c["h"], json={"command": "Send emails to all my leads now"}).json()
    assert blocked["intent"] == "send_blocked" and c["sent"] == []
    assert cl.post("/api/v1/assistant/command", headers=c["h"], json={"command": "Score my leads"}).json()["intent"] == "score"
    drafts = cl.post("/api/v1/assistant/command", headers=c["h"], json={"command": "Generate personalized cold emails for my top 5 leads"}).json()
    assert drafts["intent"] == "email_drafts" and "nothing was sent" in drafts["message"]
    scripts = cl.post("/api/v1/assistant/command", headers=c["h"], json={"command": "Create Loom video scripts for my top 20 leads"}).json()
    assert scripts["intent"] == "video_scripts"
    assert cl.post("/api/v1/assistant/command", headers=c["h"], json={"command": "Prepare a follow-up campaign"}).json()["intent"] == "followup_campaign"
    assert cl.post("/api/v1/assistant/command", headers=c["h"], json={"command": "Show my best-performing campaign"}).json()["intent"] == "best_campaign"
    assert cl.post("/api/v1/assistant/command", headers=c["h"], json={"command": "blah"}).json()["intent"] == "help"
    assert len(cl.get("/api/v1/assistant/runs", headers=c["h"]).json()) >= 7
    assert c["sent"] == []


# ------------------------------------------------------------------ security ---
def test_login_rate_limit_and_headers(client):
    for _ in range(5):
        assert client.post("/api/v1/auth/login", json={"email": "nobody@rl-test.com", "password": "wrongpass1"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "nobody@rl-test.com", "password": "wrongpass1"}).status_code == 429
    h = client.get("/api/health").headers
    assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff" and "default-src 'self'" in h["content-security-policy"]
