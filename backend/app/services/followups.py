"""Follow-up detection and timing suggestions (rule-based, no AI needed)."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import as_utc, utcnow
from app.models import Campaign, CampaignLead, Lead, Message

UNANSWERED_AFTER_DAYS = 5
DEFAULT_GAP_DAYS = 4


def suggest_send_time(last_sent, gap_days: int = DEFAULT_GAP_DAYS):
    """Last email + gap, moved to the next Tuesday-Thursday (cold email usually does best mid-week), 10:00 UTC."""
    when = as_utc(last_sent) + timedelta(days=gap_days)
    while when.weekday() not in (1, 2, 3):
        when += timedelta(days=1)
    return when.replace(hour=10, minute=0, second=0, microsecond=0)


def due_followups(db: Session, org_id: int) -> dict:
    now = utcnow()
    scheduled = []
    rows = db.execute(
        select(CampaignLead, Campaign, Lead)
        .join(Campaign, Campaign.id == CampaignLead.campaign_id)
        .join(Lead, Lead.id == CampaignLead.lead_id)
        .where(Campaign.org_id == org_id, Campaign.status.in_(("running", "paused")), CampaignLead.state == "active", CampaignLead.current_step >= 1)
        .order_by(CampaignLead.next_send_at)
        .limit(200)
    ).all()
    for cl, camp, lead in rows:
        nxt = as_utc(cl.next_send_at)
        scheduled.append({
            "campaign_id": camp.id, "campaign": camp.name, "campaign_status": camp.status, "lead_id": lead.id, "company_name": lead.company_name,
            "contact_name": lead.contact_name, "step": cl.current_step, "of": camp.max_followups,
            "next_send_at": nxt.isoformat() if nxt else None, "overdue": bool(nxt and nxt <= now),
        })

    needs = []
    for lead in db.scalars(select(Lead).where(Lead.org_id == org_id, Lead.status == "contacted").limit(500)):
        in_sequence = db.scalar(select(CampaignLead.id).where(CampaignLead.lead_id == lead.id, CampaignLead.state == "active"))
        if in_sequence:
            continue
        last_out = db.scalar(select(Message).where(Message.lead_id == lead.id, Message.direction == "out", Message.status == "sent").order_by(Message.id.desc()).limit(1))
        replied = db.scalar(select(Message.id).where(Message.lead_id == lead.id, Message.direction == "in"))
        if not last_out or replied or not last_out.sent_at:
            continue
        days = (now - as_utc(last_out.sent_at)).days
        if days >= UNANSWERED_AFTER_DAYS:
            needs.append({
                "lead_id": lead.id, "company_name": lead.company_name, "contact_name": lead.contact_name, "email": lead.email,
                "last_sent_at": as_utc(last_out.sent_at).isoformat(), "days_waiting": days,
                "emails_sent": db.query(Message).filter(Message.lead_id == lead.id, Message.direction == "out").count(),
                "suggested_send_at": suggest_send_time(last_out.sent_at).isoformat(),
            })
    needs.sort(key=lambda x: -x["days_waiting"])
    return {"scheduled": scheduled, "needs_followup": needs, "rule": f"Unanswered for {UNANSWERED_AFTER_DAYS}+ days with no sequence running; suggested Tue to Thu, 10:00 UTC."}
