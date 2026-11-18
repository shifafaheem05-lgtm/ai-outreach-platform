"""Aggregate metrics used by the dashboard (and later the analytics page)."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Campaign,
    CampaignLead,
    Lead,
    Message,
    ReplyClassification,
    Video,
)

POSITIVE_LABELS = ("interested", "meeting_requested", "need_more_information")


def _rate(numerator: int, denominator: int) -> float:
    return round(100 * numerator / denominator, 1) if denominator else 0.0


def dashboard_summary(db: Session, org_id: int) -> dict:
    total_leads = db.scalar(select(func.count()).select_from(Lead).where(Lead.org_id == org_id)) or 0
    qualified = (
        db.scalar(
            select(func.count()).select_from(Lead).where(Lead.org_id == org_id, Lead.tier.in_(("hot", "warm")))
        )
        or 0
    )
    tiers = dict(
        db.execute(select(Lead.tier, func.count()).where(Lead.org_id == org_id).group_by(Lead.tier)).all()
    )

    sent_statuses = ("sent", "delivered", "bounced")
    sent = (
        db.scalar(
            select(func.count()).select_from(Message).where(
                Message.org_id == org_id, Message.direction == "out", Message.status.in_(sent_statuses)
            )
        )
        or 0
    )
    delivered = (
        db.scalar(
            select(func.count()).select_from(Message).where(
                # SMTP only tells us "accepted"; treat sent/delivered as delivered unless a bounce comes back
                Message.org_id == org_id, Message.direction == "out", Message.status.in_(("sent", "delivered"))
            )
        )
        or 0
    )
    bounced = (
        db.scalar(
            select(func.count()).select_from(Message).where(
                Message.org_id == org_id, Message.direction == "out", Message.status == "bounced"
            )
        )
        or 0
    )
    # Distinct leads that replied
    replied_leads = (
        db.scalar(
            select(func.count(func.distinct(Message.lead_id))).where(
                Message.org_id == org_id, Message.direction == "in"
            )
        )
        or 0
    )
    contacted_leads = (
        db.scalar(
            select(func.count(func.distinct(Message.lead_id))).where(
                Message.org_id == org_id, Message.direction == "out", Message.status.in_(sent_statuses)
            )
        )
        or 0
    )
    positive = (
        db.scalar(
            select(func.count())
            .select_from(ReplyClassification)
            .join(Message, Message.id == ReplyClassification.message_id)
            .where(Message.org_id == org_id, ReplyClassification.label.in_(POSITIVE_LABELS))
        )
        or 0
    )
    meetings = (
        db.scalar(
            select(func.count())
            .select_from(ReplyClassification)
            .join(Message, Message.id == ReplyClassification.message_id)
            .where(Message.org_id == org_id, ReplyClassification.label == "meeting_requested")
        )
        or 0
    )

    # Emails sent per day, last 14 days
    since = datetime.now(timezone.utc) - timedelta(days=13)
    since = since.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = db.execute(
        select(Message.sent_at, Message.direction).where(
            Message.org_id == org_id, Message.sent_at.is_not(None), Message.sent_at >= since
        )
    ).all()
    buckets: dict[str, dict[str, int]] = {}
    for i in range(14):
        day = (since + timedelta(days=i)).strftime("%Y-%m-%d")
        buckets[day] = {"sent": 0, "replies": 0}
    for sent_at, direction in rows:
        key = sent_at.strftime("%Y-%m-%d")
        if key in buckets:
            buckets[key]["sent" if direction == "out" else "replies"] += 1
    activity = [{"date": d, **v} for d, v in buckets.items()]

    # Campaign progress
    campaigns = []
    for c in db.scalars(select(Campaign).where(Campaign.org_id == org_id).order_by(Campaign.created_at.desc()).limit(6)):
        total = db.scalar(select(func.count()).select_from(CampaignLead).where(CampaignLead.campaign_id == c.id)) or 0
        done = (
            db.scalar(
                select(func.count()).select_from(CampaignLead).where(
                    CampaignLead.campaign_id == c.id, CampaignLead.state != "pending"
                )
            )
            or 0
        )
        c_replied = (
            db.scalar(
                select(func.count(func.distinct(Message.lead_id))).where(
                    Message.campaign_id == c.id, Message.direction == "in"
                )
            )
            or 0
        )
        campaigns.append(
            {
                "id": c.id,
                "name": c.name,
                "status": c.status,
                "total_leads": total,
                "progress": _rate(done, total),
                "reply_rate": _rate(c_replied, total),
            }
        )

    # Video engagement is only reported where view counts exist
    video_total = db.scalar(select(func.count()).select_from(Video).where(Video.org_id == org_id)) or 0
    video_views = db.scalar(
        select(func.sum(Video.views)).where(Video.org_id == org_id, Video.views.is_not(None))
    )

    return {
        "total_leads": total_leads,
        "qualified_leads": qualified,
        "leads_by_tier": {t: tiers.get(t, 0) for t in ("hot", "warm", "cold")},
        "emails_sent": sent,
        "delivery_rate": _rate(delivered, sent),
        "bounce_rate": _rate(bounced, sent),
        "reply_rate": _rate(replied_leads, contacted_leads),
        "positive_response_rate": _rate(positive, replied_leads),
        "meetings_generated": meetings,
        "video_engagement": {
            "videos": video_total,
            "views": int(video_views) if video_views is not None else None,
            "available": video_views is not None,
        },
        "activity": activity,
        "campaigns": campaigns,
    }


def replies_by_label(db: Session, org_id: int) -> dict:
    rows = db.execute(
        select(ReplyClassification.label, func.count())
        .join(Message, Message.id == ReplyClassification.message_id)
        .where(Message.org_id == org_id)
        .group_by(ReplyClassification.label)
    ).all()
    return {label: n for label, n in rows}


def campaign_stats(db: Session, org_id: int) -> list[dict]:
    out = []
    for c in db.scalars(select(Campaign).where(Campaign.org_id == org_id).order_by(Campaign.id.desc())):
        def count(*cond):
            return db.scalar(select(func.count()).select_from(Message).where(Message.campaign_id == c.id, *cond)) or 0

        leads = db.scalar(select(func.count()).select_from(CampaignLead).where(CampaignLead.campaign_id == c.id)) or 0
        sent = count(Message.direction == "out", Message.status.in_(("sent", "delivered", "bounced")))
        bounced = count(Message.direction == "out", Message.status == "bounced")
        replied = db.scalar(
            select(func.count(func.distinct(Message.lead_id))).where(Message.campaign_id == c.id, Message.direction == "in")
        ) or 0

        def labelled(*labels):
            return db.scalar(
                select(func.count()).select_from(ReplyClassification).join(Message, Message.id == ReplyClassification.message_id)
                .where(Message.campaign_id == c.id, ReplyClassification.label.in_(labels))
            ) or 0

        out.append({
            "id": c.id, "name": c.name, "status": c.status, "leads": leads, "sent": sent, "bounced": bounced,
            "replied": replied, "reply_rate": _rate(replied, leads), "bounce_rate": _rate(bounced, sent),
            "positive": labelled(*POSITIVE_LABELS), "meetings": labelled("meeting_requested"),
        })
    return out


def overview(db: Session, org_id: int) -> dict:
    data = dashboard_summary(db, org_id)
    data["replies_by_label"] = replies_by_label(db, org_id)
    data["notes"] = [
        "Delivery rate counts emails the mail server accepted that did not bounce; true inbox placement cannot be measured.",
        "Opens and clicks are not tracked (tracking pixels are unreliable and privacy-invasive). Replies are the engagement signal.",
    ]
    return data
