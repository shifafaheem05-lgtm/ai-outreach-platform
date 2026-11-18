"""Transparent rules-based lead scoring (0-100). Every point is explained in `features`.

A learned model is not used yet: it needs labelled outcomes (replies/meetings) that a new
workspace does not have. Rules are the honest cold-start; training comes with real data.
"""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Lead, LeadScoreEvent, ResearchReport

MODEL_VERSION = "rules-v1"


def tier_for(score: int) -> str:
    return "hot" if score >= 70 else "warm" if score >= 40 else "cold"


def _seniority(title: str) -> int:
    t = (title or "").lower()
    if not t:
        return 0
    if re.search(r"founder|owner|ceo|president|chief|\bc[a-z]o\b|managing director|partner", t):
        return 25
    if re.search(r"\bvp\b|vice president|head of|director", t):
        return 20
    if re.search(r"manager|lead", t):
        return 12
    return 6


def _size_fit(size: str) -> int:
    s = (size or "").replace(" ", "")
    if s in ("11-50", "51-200"):
        return 15
    if s in ("1-10", "201-500"):
        return 10
    return 5


EMAIL_POINTS = {"valid": 20, "risky": 8, "unverified": 4, "invalid": 0}


def score_lead(lead: Lead, has_research: bool, target_industries: list[str] | None = None) -> tuple[int, dict]:
    targets = [t.strip().lower() for t in (target_industries or []) if t.strip()]
    if targets:
        industry = 15 if any(t in (lead.industry or "").lower() for t in targets) else 0
    else:
        industry = 8  # neutral until the user says which industries they target
    features = {
        "title_seniority": _seniority(lead.contact_title),
        "email_quality": EMAIL_POINTS.get(lead.email_status, 4),
        "company_size_fit": _size_fit(lead.company_size),
        "industry_match": industry,
        "has_website": 10 if lead.website else 0,
        "research_done": 10 if has_research else 0,
        "engagement": 15 if lead.status in ("replied", "meeting") else 0,
    }
    return min(100, sum(features.values())), features


def run_scoring(db: Session, org_id: int, lead_ids: list[int] | None = None, targets: list[str] | None = None) -> dict:
    q = select(Lead).where(Lead.org_id == org_id)
    if lead_ids:
        q = q.where(Lead.id.in_(lead_ids))
    leads = list(db.scalars(q.limit(5000)))
    researched: set[int] = set()
    if leads:
        rows = db.execute(
            select(ResearchReport.lead_id, ResearchReport.sources).where(ResearchReport.lead_id.in_([l.id for l in leads]))
        )
        researched = {lead_id for lead_id, sources in rows if sources}  # only reports built from real pages
    counts = {"hot": 0, "warm": 0, "cold": 0}
    for lead in leads:
        score, features = score_lead(lead, lead.id in researched, targets)
        lead.score, lead.tier = score, tier_for(score)
        counts[lead.tier] += 1
        db.add(LeadScoreEvent(lead_id=lead.id, score=score, tier=lead.tier, features=features, model_version=MODEL_VERSION))
    db.commit()
    return {"scored": len(leads), **counts}
