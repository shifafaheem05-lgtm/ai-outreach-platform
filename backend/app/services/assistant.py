"""Command assistant. Rule-based (works with no AI and no cost) and deliberately limited:

- It runs INTERNAL work immediately (search, research, scoring, drafting, scripts).
- It can never send anything. Sending always goes through the campaign approval flow.
- It says plainly what it cannot do (for example, discover new businesses without a licensed data source).
"""
import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import utcnow
from app.models import Campaign, CampaignLead, EmailDraft, Lead, Message, Organization, ResearchReport, User, Video
from app.services import analytics, email_writer, scoring
from app.services import video_scripts as vs
from app.services.campaigns import ineligible_reason
from app.services.research import run_research
from app.services.sending import default_integration

HELP = (
    "I can run these (examples): \"Research my top 3 leads\", \"Generate personalized cold emails for my top 10 leads\", "
    "\"Create Loom video scripts for my top 20 leads\", \"Score my leads\", \"Prepare a follow-up campaign\", "
    "\"Show my best-performing campaign\", \"Find marketing agencies in Texas\" (searches the leads you already have)."
)
STOP = {"find", "search", "show", "list", "me", "my", "the", "in", "of", "for", "leads", "lead", "companies", "company", "usa", "us", "united", "states", "a", "an", "all", "top", "get", "and"}


def _n(text: str, default: int, cap: int) -> int:
    m = re.search(r"\b(\d{1,4})\b", text)
    return min(int(m.group(1)), cap) if m else default


def _top_leads(db: Session, org_id: int, limit: int, need_email=False, need_site=False) -> list[Lead]:
    q = select(Lead).where(Lead.org_id == org_id, Lead.status != "unsubscribed").order_by(Lead.score.desc(), Lead.id)
    if need_email:
        q = q.where(Lead.email != "", Lead.email_status != "invalid")
    if need_site:
        q = q.where(Lead.website != "")
    return list(db.scalars(q.limit(limit)))


def _latest_report(db: Session, lead_id: int):
    return db.scalar(select(ResearchReport).where(ResearchReport.lead_id == lead_id).order_by(ResearchReport.id.desc()).limit(1))


def run_command(db: Session, user: User, command: str) -> dict:
    text = command.lower().strip()
    org = db.get(Organization, user.org_id)
    steps: list[str] = []

    if re.search(r"\bsend\b", text):
        return {"intent": "send_blocked", "message": (
            "I never send email myself. I can prepare a campaign with drafts; you review it, submit it for approval in Email Campaigns, "
            "and a manager approves and starts it. Try: \"Prepare a follow-up campaign\"."), "steps": steps}

    if "best" in text and "campaign" in text:
        stats = [c for c in analytics.campaign_stats(db, user.org_id) if c["sent"] > 0]
        if not stats:
            return {"intent": "best_campaign", "message": "No campaign has sent emails yet, so there is nothing to rank.", "steps": steps}
        best = max(stats, key=lambda c: (c["reply_rate"], c["positive"]))
        return {"intent": "best_campaign", "message": f"Best so far: \"{best['name']}\" with a {best['reply_rate']}% reply rate ({best['replied']} replies from {best['leads']} leads, {best['meetings']} meeting requests).", "data": best, "steps": steps}

    if "follow" in text and "campaign" in text:
        leads = []
        for l in db.scalars(select(Lead).where(Lead.org_id == user.org_id, Lead.status == "contacted").limit(200)):
            replied = db.scalar(select(Message.id).where(Message.lead_id == l.id, Message.direction == "in"))
            if not replied and not ineligible_reason(db, user.org_id, l):
                leads.append(l)
        if not leads:
            return {"intent": "followup_campaign", "message": "No contacted-but-unanswered leads to follow up with.", "steps": steps}
        integ = default_integration(db, user.org_id)
        camp = Campaign(org_id=user.org_id, name=f"Follow-up {utcnow():%Y-%m-%d %H:%M}", tone="professional", status="draft",
                        sender_integration_id=integ.id if integ else None, followup_intervals=[], max_followups=0, created_by=user.id)
        db.add(camp)
        db.flush()
        for l in leads:
            cl = CampaignLead(campaign_id=camp.id, lead_id=l.id)
            db.add(cl)
            db.flush()
            prev = [{"subject": m.subject, "body": m.body} for m in db.scalars(select(Message).where(Message.lead_id == l.id, Message.direction == "out").order_by(Message.id))]
            mail = email_writer.generate_followup(l, _latest_report(db, l.id), "professional", org, prev, max(1, len(prev)))
            db.add(EmailDraft(campaign_lead_id=cl.id, lead_id=l.id, step=0, variant="followup", subject=mail["subject"], body=mail["body"]))
        db.commit()
        note = "" if integ else " Add a mailbox in Integrations and pick it in the campaign before submitting."
        return {"intent": "followup_campaign", "message": f"Created draft campaign \"{camp.name}\" with {len(leads)} lead(s) and a follow-up draft for each. Nothing is sent. Review it in Email Campaigns, then submit for approval.{note}", "data": {"campaign_id": camp.id}, "steps": steps}

    if "loom" in text or "video" in text:
        n = _n(text, 20, 20)
        made = 0
        for l in _top_leads(db, user.org_id, n):
            out = vs.generate(l, _latest_report(db, l.id), org)
            db.add(Video(org_id=user.org_id, lead_id=l.id, script=out["script"], intro=out["intro"], description=out["description"], status="awaiting_recording"))
            made += 1
        db.commit()
        return {"intent": "video_scripts", "message": f"Created {made} video script(s) for your top leads. Open Loom Video Studio to review them and record each one yourself; I can't record or upload Loom videos.", "steps": steps}

    if re.search(r"(email|cold)", text) and re.search(r"(generate|write|draft|create|personali)", text):
        n = _n(text, 10, 25)
        made = 0
        for l in _top_leads(db, user.org_id, n * 3, need_email=True)[:n]:
            v = email_writer.generate_initial(l, _latest_report(db, l.id), "professional", org, ["medium"])[0]
            db.add(EmailDraft(lead_id=l.id, step=0, variant="medium", subject=v["subject"], body=v["body"]))
            made += 1
        db.commit()
        return {"intent": "email_drafts", "message": f"Drafted {made} personalized email(s) for your top leads with valid-looking addresses. They are saved as drafts in AI Email Writer; nothing was sent.", "steps": steps}

    if "research" in text:
        cap = 3  # each research run reads a live website politely, so keep a command quick
        n = _n(text, cap, cap)
        todo = [l for l in _top_leads(db, user.org_id, 200, need_site=True) if not _latest_report(db, l.id)][:n]
        for l in todo:
            run_research(db, l, user.id)
            steps.append(f"Researched {l.company_name}")
        msg = f"Researched {len(todo)} lead(s) (max {cap} per command to keep it quick). Run it again for more." if todo else "Every top lead with a website already has a report."
        return {"intent": "research", "message": msg, "steps": steps}

    if "score" in text or "scoring" in text or "rank" in text:
        r = scoring.run_scoring(db, user.org_id)
        return {"intent": "score", "message": f"Scored {r['scored']} leads: {r['hot']} hot, {r['warm']} warm, {r['cold']} cold.", "steps": steps}

    if re.search(r"\b(find|search|show|list|get)\b", text):
        words = [w for w in re.findall(r"[a-z0-9-]{3,}", text) if w not in STOP and not w.isdigit()]
        q = select(Lead).where(Lead.org_id == user.org_id)
        for w in words:
            stem = w[:-3] + "y" if w.endswith("ies") else (w[:-1] if w.endswith("s") and not w.endswith("ss") else w)
            like = f"%{stem}%"
            q = q.where(Lead.company_name.ilike(like) | Lead.industry.ilike(like) | Lead.location.ilike(like) | Lead.niche.ilike(like))
        rows = list(db.scalars(q.order_by(Lead.score.desc()).limit(_n(text, 25, 100))))
        found = [{"id": l.id, "company": l.company_name, "industry": l.industry, "location": l.location, "score": l.score, "tier": l.tier} for l in rows]
        return {"intent": "search", "message": (
            f"Found {len(found)} matching lead(s) among the leads you already have. I can't discover new businesses on my own: "
            "that needs a licensed data source. Import a CSV in Lead Discovery to add more."), "data": found, "steps": steps}

    return {"intent": "help", "message": HELP, "steps": steps}
