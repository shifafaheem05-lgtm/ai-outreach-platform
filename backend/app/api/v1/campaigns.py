from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_role
from app.models import Campaign, CampaignLead, EmailDraft, Integration, Lead, Organization, User
from app.services import campaigns as svc
from app.services.email_writer import TONES, VARIANTS

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    tone: str = "professional"
    sender_integration_id: int | None = None
    followup_intervals: list[int] = Field(default_factory=lambda: [3, 7], max_length=5)
    schedule: dict = Field(default_factory=dict)


class CampaignPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"\S")
    tone: str | None = None
    sender_integration_id: int | None = None
    followup_intervals: list[int] | None = Field(default=None, max_length=5)
    schedule: dict | None = None


class LeadIdsIn(BaseModel):
    lead_ids: list[int] = Field(min_length=1, max_length=500)


class GenerateIn(BaseModel):
    variant: str = "medium"
    regenerate: bool = False


def _check(data: dict, db: Session, org_id: int) -> None:
    if "tone" in data and data["tone"] not in TONES:
        raise HTTPException(400, f"tone must be one of {', '.join(TONES)}")
    if data.get("followup_intervals") is not None and not all(1 <= d <= 60 for d in data["followup_intervals"]):
        raise HTTPException(400, "Follow-up intervals must be between 1 and 60 days")
    sid = data.get("sender_integration_id")
    if sid:
        integ = db.get(Integration, sid)
        if not integ or integ.org_id != org_id:
            raise HTTPException(400, "Unknown sending mailbox")


def get_campaign(db: Session, user: User, campaign_id: int) -> Campaign:
    c = db.get(Campaign, campaign_id)
    if not c or c.org_id != user.org_id:
        raise HTTPException(404, "Campaign not found")
    return c


def campaign_out(db: Session, c: Campaign) -> dict:
    states = dict(db.execute(select(CampaignLead.state, func.count()).where(CampaignLead.campaign_id == c.id).group_by(CampaignLead.state)).all())
    return {
        "id": c.id, "name": c.name, "tone": c.tone, "status": c.status, "sender_integration_id": c.sender_integration_id,
        "followup_intervals": c.followup_intervals or [], "max_followups": c.max_followups, "schedule": c.schedule or {},
        "lead_counts": states, "total_leads": sum(states.values()), "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _wrap(fn, *args):
    try:
        return fn(*args)
    except svc.WorkflowError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get("")
def list_campaigns(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Campaign).where(Campaign.org_id == user.org_id).order_by(Campaign.id.desc()))
    return [campaign_out(db, c) for c in rows]


@router.post("", status_code=201)
def create_campaign(data: CampaignIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check(data.model_dump(), db, user.org_id)
    c = Campaign(
        org_id=user.org_id, name=data.name, tone=data.tone, sender_integration_id=data.sender_integration_id,
        followup_intervals=data.followup_intervals, max_followups=len(data.followup_intervals), schedule=data.schedule, created_by=user.id,
    )
    db.add(c)
    db.commit()
    return campaign_out(db, c)


@router.post("/process-now")
def process_now(user: User = Depends(require_role("manager")), db: Session = Depends(get_db)):
    """Run the sender immediately for this organization (the scheduler also does this every minute)."""
    return svc.process_due(db, user.org_id)


@router.get("/{campaign_id}")
def get_one(campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = get_campaign(db, user, campaign_id)
    rows = db.execute(
        select(CampaignLead, Lead).join(Lead, Lead.id == CampaignLead.lead_id).where(CampaignLead.campaign_id == c.id).order_by(CampaignLead.id)
    ).all()
    leads = [
        {
            "id": cl.id, "lead_id": l.id, "company_name": l.company_name, "contact_name": l.contact_name, "email": l.email,
            "state": cl.state, "current_step": cl.current_step, "next_send_at": cl.next_send_at.isoformat() if cl.next_send_at else None,
            "drafts": db.scalar(select(func.count()).select_from(EmailDraft).where(EmailDraft.campaign_lead_id == cl.id)) or 0,
        }
        for cl, l in rows
    ]
    return {**campaign_out(db, c), "leads": leads}


@router.patch("/{campaign_id}")
def update_campaign(campaign_id: int, data: CampaignPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = get_campaign(db, user, campaign_id)
    if c.status != "draft":
        raise HTTPException(409, "Revert the campaign to draft to change its settings")
    changes = data.model_dump(exclude_unset=True)
    _check(changes, db, user.org_id)
    for k, v in changes.items():
        setattr(c, k, v)
    if "followup_intervals" in changes and changes["followup_intervals"] is not None:
        c.max_followups = len(changes["followup_intervals"])
    db.commit()
    return campaign_out(db, c)


@router.delete("/{campaign_id}", status_code=204)
def delete_campaign(campaign_id: int, user: User = Depends(require_role("manager")), db: Session = Depends(get_db)):
    c = get_campaign(db, user, campaign_id)
    if c.status != "draft":
        raise HTTPException(409, "Only draft campaigns can be deleted")
    for cl in db.scalars(select(CampaignLead).where(CampaignLead.campaign_id == c.id)):
        for d in db.scalars(select(EmailDraft).where(EmailDraft.campaign_lead_id == cl.id)):
            db.delete(d)
        db.delete(cl)
    db.delete(c)
    db.commit()


@router.post("/{campaign_id}/leads")
def add_leads(campaign_id: int, data: LeadIdsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _wrap(svc.add_leads, db, get_campaign(db, user, campaign_id), data.lead_ids)


@router.delete("/{campaign_id}/leads/{lead_id}", status_code=204)
def remove_lead(campaign_id: int, lead_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = get_campaign(db, user, campaign_id)
    if c.status != "draft":
        raise HTTPException(409, "Revert the campaign to draft first")
    cl = db.scalar(select(CampaignLead).where(CampaignLead.campaign_id == c.id, CampaignLead.lead_id == lead_id))
    if cl:
        for d in db.scalars(select(EmailDraft).where(EmailDraft.campaign_lead_id == cl.id)):
            db.delete(d)
        db.delete(cl)
        db.commit()


@router.post("/{campaign_id}/generate-drafts")
def generate(campaign_id: int, data: GenerateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if data.variant not in VARIANTS:
        raise HTTPException(400, f"variant must be one of {', '.join(VARIANTS)}")
    c = get_campaign(db, user, campaign_id)
    return _wrap(svc.generate_drafts, db, c, db.get(Organization, user.org_id), data.variant, data.regenerate)


@router.get("/{campaign_id}/drafts")
def drafts(campaign_id: int, lead_id: int | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = get_campaign(db, user, campaign_id)
    q = (
        select(EmailDraft, Lead).join(CampaignLead, CampaignLead.id == EmailDraft.campaign_lead_id).join(Lead, Lead.id == EmailDraft.lead_id)
        .where(CampaignLead.campaign_id == c.id).order_by(EmailDraft.lead_id, EmailDraft.step)
    )
    if lead_id:
        q = q.where(EmailDraft.lead_id == lead_id)
    return [
        {"id": d.id, "lead_id": l.id, "company_name": l.company_name, "contact_name": l.contact_name, "step": d.step, "variant": d.variant, "subject": d.subject, "body": d.body, "status": d.status}
        for d, l in db.execute(q.limit(500)).all()
    ]


@router.post("/{campaign_id}/submit-approval")
def submit(campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = get_campaign(db, user, campaign_id)
    _wrap(svc.submit_for_approval, db, c, db.get(Organization, user.org_id), user)
    return campaign_out(db, c)


@router.post("/{campaign_id}/approve")
def approve(campaign_id: int, user: User = Depends(require_role("manager")), db: Session = Depends(get_db)):
    return campaign_out(db, _wrap(svc.decide, db, get_campaign(db, user, campaign_id), user, True))


@router.post("/{campaign_id}/reject")
def reject(campaign_id: int, user: User = Depends(require_role("manager")), db: Session = Depends(get_db)):
    return campaign_out(db, _wrap(svc.decide, db, get_campaign(db, user, campaign_id), user, False))


@router.post("/{campaign_id}/revert")
def revert(campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = get_campaign(db, user, campaign_id)
    _wrap(svc.revert_to_draft, db, c, user)
    return campaign_out(db, c)


@router.post("/{campaign_id}/start")
def start(campaign_id: int, user: User = Depends(require_role("manager")), db: Session = Depends(get_db)):
    c = get_campaign(db, user, campaign_id)
    _wrap(svc.start, db, c, user)
    return campaign_out(db, c)


@router.post("/{campaign_id}/pause")
def pause(campaign_id: int, user: User = Depends(require_role("manager")), db: Session = Depends(get_db)):
    c = get_campaign(db, user, campaign_id)
    _wrap(svc.pause, db, c, user)
    return campaign_out(db, c)
