from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_role
from app.models import (
    AuditLog,
    CampaignLead,
    Lead,
    LeadScoreEvent,
    Message,
    Note,
    ResearchReport,
    User,
    Video,
)
from app.core.validation import check_email, check_website
from app.services import llm
from app.services.leads import clean_lead_fields, import_csv, make_dedupe_key, region_flag
from app.services.verification import verify_email

router = APIRouter(prefix="/leads", tags=["leads"])

EDITABLE = (
    "company_name website industry location company_size niche contact_name contact_title "
    "email status category tags"
).split()


class LeadIn(BaseModel):
    company_name: str = Field(min_length=1, max_length=255)
    website: str = Field(default="", max_length=500)
    industry: str = Field(default="", max_length=120)
    location: str = Field(default="", max_length=200)
    company_size: str = Field(default="", max_length=50)
    niche: str = Field(default="", max_length=200)
    contact_name: str = Field(default="", max_length=200)
    contact_title: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=255)


class LeadPatch(BaseModel):
    company_name: str | None = Field(default=None, min_length=1, max_length=255)
    website: str | None = None
    industry: str | None = None
    location: str | None = None
    company_size: str | None = None
    niche: str | None = None
    contact_name: str | None = None
    contact_title: str | None = None
    email: str | None = None
    status: str | None = None
    category: str | None = None
    tags: list[str] | None = None


class VerifyIn(BaseModel):
    lead_ids: list[int] | None = None
    only_unverified: bool = True


def lead_out(lead: Lead, researched: bool = False) -> dict:
    return {
        "id": lead.id,
        "company_name": lead.company_name,
        "website": lead.website,
        "industry": lead.industry,
        "location": lead.location,
        "company_size": lead.company_size,
        "niche": lead.niche,
        "contact_name": lead.contact_name,
        "contact_title": lead.contact_title,
        "email": lead.email,
        "email_status": lead.email_status,
        "source": lead.source,
        "score": lead.score,
        "tier": lead.tier,
        "status": lead.status,
        "category": lead.category,
        "tags": lead.tags or [],
        "region_flag": lead.region_flag,
        "researched": researched,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
    }


def get_lead_or_404(db: Session, user: User, lead_id: int) -> Lead:
    lead = db.get(Lead, lead_id)
    if not lead or lead.org_id != user.org_id:
        raise HTTPException(404, "Lead not found")
    return lead


def _researched_ids(db: Session, ids: list[int]) -> set[int]:
    if not ids:
        return set()
    return set(db.scalars(select(ResearchReport.lead_id).where(ResearchReport.lead_id.in_(ids))))


def _audit(db: Session, user: User, action: str, entity_id: int | None = None, **meta) -> None:
    db.add(AuditLog(org_id=user.org_id, user_id=user.id, action=action, entity="lead", entity_id=entity_id, meta=meta))


# NOTE: static routes are declared before /{lead_id} so they are not captured by it.
@router.get("/capabilities")
def capabilities(user: User = Depends(get_current_user)):
    from app.core.config import settings

    return {
        "lead_sources": [
            {"id": "csv", "label": "CSV import", "available": True},
            {"id": "manual", "label": "Manual entry", "available": True},
        ],
        "email_verification": {
            "method": "syntax + DNS (MX) check",
            "confirms_mailbox": False,
            "note": "Confirms the domain can receive email, not that the mailbox exists.",
        },
        "llm": {"configured": llm.is_configured(), "model": settings.openai_model if llm.is_configured() else None},
    }


@router.post("/import-csv")
async def import_csv_endpoint(
    file: UploadFile = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    raw = await file.read(2_000_001)
    try:
        result = import_csv(db, user.org_id, raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _audit(db, user, "leads.import_csv", filename=file.filename, **{k: result[k] for k in ("created", "duplicates", "skipped")})
    db.commit()
    return result


@router.post("/verify")
def verify_leads(data: VerifyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = select(Lead).where(Lead.org_id == user.org_id, Lead.email != "")
    if data.lead_ids:
        q = q.where(Lead.id.in_(data.lead_ids))
    elif data.only_unverified:
        q = q.where(Lead.email_status == "unverified")
    leads = list(db.scalars(q.limit(200)))  # bounded so one request stays quick
    cache: dict = {}
    counts = {"valid": 0, "risky": 0, "invalid": 0, "unverified": 0}
    for lead in leads:
        status, _reason = verify_email(lead.email, cache)
        lead.email_status = status
        counts[status] += 1
    _audit(db, user, "leads.verify", checked=len(leads))
    db.commit()
    return {"checked": len(leads), **counts}


@router.post("/dedupe")
def dedupe_leads(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Merge leads sharing an email address. Leads with outreach history are never deleted."""
    leads = list(db.scalars(select(Lead).where(Lead.org_id == user.org_id, Lead.email != "").order_by(Lead.id)))
    groups: dict[str, list[Lead]] = {}
    for lead in leads:
        groups.setdefault(lead.email.lower(), []).append(lead)

    removed = kept_with_history = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        keeper, *extras = group
        for dup in extras:
            if _has_history(db, dup.id):
                kept_with_history += 1
                continue
            for field in EDITABLE:  # fill blanks on the keeper from the duplicate
                if field not in ("tags",) and not getattr(keeper, field) and getattr(dup, field):
                    setattr(keeper, field, getattr(dup, field))
            _delete_lead_rows(db, dup.id)
            removed += 1
    _audit(db, user, "leads.dedupe", removed=removed)
    db.commit()
    return {"removed": removed, "kept_because_of_history": kept_with_history}


def _has_history(db: Session, lead_id: int) -> bool:
    for model in (Message, CampaignLead, Video):
        if db.scalar(select(func.count()).select_from(model).where(model.lead_id == lead_id)):
            return True
    return False


def _delete_lead_rows(db: Session, lead_id: int) -> None:
    for model in (ResearchReport, LeadScoreEvent, Note):
        db.execute(delete(model).where(model.lead_id == lead_id))
    db.execute(delete(Lead).where(Lead.id == lead_id))


@router.get("")
def list_leads(
    q: str = "",
    tier: str = "",
    status: str = "",
    email_status: str = "",
    sort: str = "created",
    page: int = 1,
    page_size: int = 25,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    page_size = max(1, min(page_size, 100))
    page = max(1, page)
    cond = [Lead.org_id == user.org_id]
    if q:
        like = f"%{q.strip()}%"
        cond.append(
            or_(
                Lead.company_name.ilike(like),
                Lead.contact_name.ilike(like),
                Lead.email.ilike(like),
                Lead.industry.ilike(like),
            )
        )
    if tier:
        cond.append(Lead.tier == tier)
    if status:
        cond.append(Lead.status == status)
    if email_status:
        cond.append(Lead.email_status == email_status)
    order = {"score": Lead.score.desc(), "company": Lead.company_name.asc()}.get(sort, Lead.created_at.desc())
    total = db.scalar(select(func.count()).select_from(Lead).where(*cond)) or 0
    rows = list(db.scalars(select(Lead).where(*cond).order_by(order, Lead.id).limit(page_size).offset((page - 1) * page_size)))
    researched = _researched_ids(db, [r.id for r in rows])
    return {
        "items": [lead_out(r, r.id in researched) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _validated(fields: dict) -> dict:
    """Reject blank names, malformed websites and malformed emails with a clear 422."""
    try:
        if "company_name" in fields and not fields["company_name"]:
            raise ValueError("Company name cannot be blank")
        if fields.get("website"):
            check_website(fields["website"])
        if fields.get("email"):
            check_email(fields["email"])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return fields


@router.post("", status_code=201)
def create_lead(data: LeadIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    fields = _validated(clean_lead_fields(data.model_dump()))
    key = make_dedupe_key(fields["company_name"], fields["website"], fields["email"])
    if db.scalar(select(Lead.id).where(Lead.org_id == user.org_id, Lead.dedupe_key == key)):
        raise HTTPException(409, "A lead with the same email/domain already exists")
    lead = Lead(
        org_id=user.org_id,
        source="manual",
        dedupe_key=key,
        region_flag=region_flag(fields["website"], fields["email"], fields["location"]),
        **fields,
    )
    db.add(lead)
    _audit(db, user, "lead.create")
    db.commit()
    return lead_out(lead)


@router.get("/{lead_id}")
def get_lead(lead_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lead = get_lead_or_404(db, user, lead_id)
    return lead_out(lead, lead.id in _researched_ids(db, [lead.id]))


@router.patch("/{lead_id}")
def update_lead(lead_id: int, data: LeadPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lead = get_lead_or_404(db, user, lead_id)
    changes = data.model_dump(exclude_unset=True)
    cleaned = _validated(clean_lead_fields({k: v for k, v in changes.items() if k != "tags"}))
    for key, value in cleaned.items():
        setattr(lead, key, value)
    if "tags" in changes and changes["tags"] is not None:
        lead.tags = [t.strip() for t in changes["tags"] if t.strip()]
    if {"email", "website", "company_name"} & changes.keys():
        new_key = make_dedupe_key(lead.company_name, lead.website, lead.email)
        clash = db.scalar(select(Lead.id).where(Lead.org_id == user.org_id, Lead.dedupe_key == new_key, Lead.id != lead.id))
        if clash:
            raise HTTPException(409, "Another lead already has that email/domain")
        lead.dedupe_key = new_key
        lead.region_flag = region_flag(lead.website, lead.email, lead.location)
        if "email" in changes:
            lead.email_status = "unverified"
    db.commit()
    return lead_out(lead, lead.id in _researched_ids(db, [lead.id]))


@router.delete("/{lead_id}", status_code=204)
def delete_lead(lead_id: int, user: User = Depends(require_role("manager")), db: Session = Depends(get_db)):
    lead = get_lead_or_404(db, user, lead_id)
    if _has_history(db, lead.id):
        raise HTTPException(409, "Lead has outreach history and cannot be deleted")
    _delete_lead_rows(db, lead.id)
    _audit(db, user, "lead.delete", lead_id)
    db.commit()
