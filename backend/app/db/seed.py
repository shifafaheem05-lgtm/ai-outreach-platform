"""Demo data. Entirely fictional companies and contacts, clearly marked source='demo'."""
import logging
import random
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import (
    Campaign,
    CampaignLead,
    Lead,
    Message,
    Organization,
    ReplyClassification,
    User,
    Video,
    utcnow,
)

log = logging.getLogger(__name__)

DEMO_EMAIL = "demo@aioutreach.pro"
DEMO_PASSWORD = "Demo1234!"

INDUSTRIES = ["Marketing Agency", "SaaS", "E-commerce", "Consulting", "Real Estate", "Healthcare IT"]
LOCATIONS = ["Austin, TX", "New York, NY", "Denver, CO", "Chicago, IL", "Seattle, WA", "Miami, FL"]
SIZES = ["1-10", "11-50", "51-200", "201-500"]
TITLES = ["Founder", "CEO", "Head of Growth", "VP Marketing", "Marketing Manager", "Operations Lead"]
FIRST = ["Alex", "Jordan", "Sam", "Taylor", "Riley", "Casey", "Morgan", "Jamie", "Avery", "Quinn"]
LAST = ["Rivera", "Chen", "Patel", "Nguyen", "Okafor", "Silva", "Kowalski", "Haddad", "Brooks", "Larsen"]
WORDS = ["Northwind", "Lumen", "Brightpath", "Cobalt", "Evergreen", "Skyline", "Pinnacle", "Harbor", "Vertex", "Summit"]
SUFFIX = ["Labs", "Studio", "Group", "Partners", "Digital", "Collective"]

REPLIES = [
    ("interested", "Thanks for reaching out - this looks relevant. Can you share a bit more?"),
    ("meeting_requested", "Happy to chat. Does Thursday at 2pm work for a quick call?"),
    ("not_interested", "Not a fit for us right now, please remove me from your list."),
    ("need_more_information", "What does pricing look like and who else have you worked with?"),
    ("follow_up_later", "Interesting, but we're mid-quarter. Ping me in January."),
    ("out_of_office", "I am out of the office until next week with limited email access."),
]


def _tier(score: int) -> str:
    return "hot" if score >= 70 else "warm" if score >= 40 else "cold"


def seed_demo(db: Session) -> None:
    if db.scalar(select(User).where(User.email == DEMO_EMAIL)):
        return
    rng = random.Random(42)
    now = utcnow()

    org = Organization(
        name="Demo Agency",
        sender_name="Demo Agency Team",
        physical_address="123 Example Street, Austin, TX 78701, USA",
    )
    db.add(org)
    db.flush()
    db.add(
        User(
            org_id=org.id,
            email=DEMO_EMAIL,
            name="Demo Admin",
            password_hash=hash_password(DEMO_PASSWORD),
            role="admin",
        )
    )

    leads: list[Lead] = []
    for i in range(48):
        company = f"{rng.choice(WORDS)} {rng.choice(SUFFIX)} {i + 1}"
        domain = company.lower().replace(" ", "") + ".example"
        first, last = rng.choice(FIRST), rng.choice(LAST)
        score = rng.randint(8, 98)
        lead = Lead(
            org_id=org.id,
            company_name=company,
            website=f"https://{domain}",
            industry=rng.choice(INDUSTRIES),
            location=rng.choice(LOCATIONS),
            company_size=rng.choice(SIZES),
            contact_name=f"{first} {last}",
            contact_title=rng.choice(TITLES),
            email=f"{first}.{last}@{domain}".lower(),
            email_status=rng.choice(["valid", "valid", "valid", "risky", "unverified"]),
            source="demo",
            score=score,
            tier=_tier(score),
            dedupe_key=domain,
            tags=["demo"],
            created_at=now - timedelta(days=rng.randint(0, 20)),
        )
        leads.append(lead)
    db.add_all(leads)
    db.flush()

    campaigns = []
    for name, status in [("Q4 Agency Outreach", "running"), ("SaaS Founders Intro", "running"), ("Real Estate Pilot", "completed")]:
        c = Campaign(org_id=org.id, name=name, status=status, tone="professional", created_at=now - timedelta(days=15))
        db.add(c)
        campaigns.append(c)
    db.flush()

    for idx, lead in enumerate(leads[:36]):
        camp = campaigns[idx % 3]
        replied = rng.random() < 0.22
        state = "replied" if replied else "active"
        db.add(CampaignLead(campaign_id=camp.id, lead_id=lead.id, state=state, current_step=1))
        sent_at = now - timedelta(days=rng.randint(0, 13), hours=rng.randint(0, 20))
        status = rng.choices(["delivered", "bounced", "sent"], weights=[85, 5, 10])[0]
        out = Message(
            org_id=org.id,
            lead_id=lead.id,
            campaign_id=camp.id,
            direction="out",
            subject=f"Idea for {lead.company_name}",
            body="(demo message)",
            status=status,
            sent_at=sent_at,
        )
        db.add(out)
        if status == "bounced":
            lead.email_status = "invalid"
        if replied and status != "bounced":
            label, text = rng.choice(REPLIES)
            reply = Message(
                org_id=org.id,
                lead_id=lead.id,
                campaign_id=camp.id,
                direction="in",
                subject=f"Re: Idea for {lead.company_name}",
                body=text,
                status="received",
                sent_at=sent_at + timedelta(hours=rng.randint(2, 40)),
            )
            db.add(reply)
            db.flush()
            db.add(ReplyClassification(message_id=reply.id, label=label, confidence=round(rng.uniform(0.7, 0.97), 2)))
            lead.status = "meeting" if label == "meeting_requested" else "replied"
        else:
            lead.status = "contacted"

    for lead in leads[:3]:
        db.add(
            Video(
                org_id=org.id,
                lead_id=lead.id,
                script="(demo script)",
                status="awaiting_recording",
            )
        )

    db.commit()
    log.info("Seeded demo data. Login: %s / %s", DEMO_EMAIL, DEMO_PASSWORD)
