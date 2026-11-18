import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.leads import get_lead_or_404
from app.core.deps import get_current_user, get_db
from app.core.timeutil import utcnow
from app.models import Approval, Campaign, CampaignLead, EmailDraft, Integration, Lead, Message, Organization, ResearchReport, User, Video
from app.services import email_writer
from app.services.sending import SendError, default_integration, send_email

router = APIRouter(prefix="/emails", tags=["emails"])
PLACEHOLDER = re.compile(r"\[[A-Z][A-Z ]{2,}[:\]]")


class GenerateIn(BaseModel):
    lead_id: int
    tone: str = "professional"
    variants: list[str] = Field(default_factory=lambda: list(email_writer.VARIANTS))


class FollowupIn(BaseModel):
    lead_id: int
    tone: str = "professional"


class DraftPatch(BaseModel):
    subject: str | None = Field(default=None, min_length=1, max_length=300)
    body: str | None = Field(default=None, min_length=1, max_length=10000)


class InsertVideoIn(BaseModel):
    video_id: int


class SendIn(BaseModel):
    integration_id: int | None = None
    confirm: bool = False


def draft_out(d: EmailDraft) -> dict:
    return {"id": d.id, "lead_id": d.lead_id, "campaign_lead_id": d.campaign_lead_id, "step": d.step, "variant": d.variant, "subject": d.subject, "body": d.body, "status": d.status}


def get_draft(db: Session, user: User, draft_id: int) -> EmailDraft:
    d = db.get(EmailDraft, draft_id)
    lead = db.get(Lead, d.lead_id) if d else None
    if not d or not lead or lead.org_id != user.org_id:
        raise HTTPException(404, "Draft not found")
    return d


def latest_report(db: Session, lead_id: int) -> ResearchReport | None:
    return db.scalar(select(ResearchReport).where(ResearchReport.lead_id == lead_id).order_by(ResearchReport.id.desc()).limit(1))


def _check_tone(tone: str) -> None:
    if tone not in email_writer.TONES:
        raise HTTPException(400, f"tone must be one of {', '.join(email_writer.TONES)}")


@router.post("/generate")
def generate(data: GenerateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check_tone(data.tone)
    lead = get_lead_or_404(db, user, data.lead_id)
    org = db.get(Organization, user.org_id)
    out = []
    for v in email_writer.generate_initial(lead, latest_report(db, lead.id), data.tone, org, data.variants):
        d = EmailDraft(lead_id=lead.id, step=0, variant=v["variant"], subject=v["subject"], body=v["body"])
        db.add(d)
        db.flush()
        out.append({**draft_out(d), "ai": v.get("ai", False)})
    db.commit()
    return out


def followup_for(db: Session, user: User, lead: Lead, tone: str) -> EmailDraft:
    org = db.get(Organization, user.org_id)
    prev = list(db.scalars(select(Message).where(Message.lead_id == lead.id, Message.direction == "out").order_by(Message.id)))
    v = email_writer.generate_followup(lead, latest_report(db, lead.id), tone, org, [{"subject": m.subject, "body": m.body} for m in prev], max(1, len(prev)))
    d = EmailDraft(lead_id=lead.id, step=max(1, len(prev)), variant="followup", subject=v["subject"], body=v["body"])
    db.add(d)
    db.commit()
    return d


@router.post("/followups")
def followups(data: FollowupIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check_tone(data.tone)
    return draft_out(followup_for(db, user, get_lead_or_404(db, user, data.lead_id), data.tone))


@router.get("/drafts")
def list_drafts(lead_id: int | None = None, status: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = select(EmailDraft).join(Lead, Lead.id == EmailDraft.lead_id).where(Lead.org_id == user.org_id, EmailDraft.campaign_lead_id.is_(None))
    if lead_id:
        q = q.where(EmailDraft.lead_id == lead_id)
    if status:
        q = q.where(EmailDraft.status == status)
    return [draft_out(d) for d in db.scalars(q.order_by(EmailDraft.id.desc()).limit(100))]


def _guard_edit(db: Session, d: EmailDraft) -> None:
    if d.status == "sent":
        raise HTTPException(409, "This email was already sent")
    if d.campaign_lead_id:
        cl = db.get(CampaignLead, d.campaign_lead_id)
        camp = db.get(Campaign, cl.campaign_id)
        if camp.status != "draft":
            raise HTTPException(409, "Revert the campaign to draft before editing its emails")


@router.patch("/drafts/{draft_id}")
def patch_draft(draft_id: int, data: DraftPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    d = get_draft(db, user, draft_id)
    _guard_edit(db, d)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(d, k, v)
    db.commit()
    return draft_out(d)


@router.delete("/drafts/{draft_id}", status_code=204)
def delete_draft(draft_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    d = get_draft(db, user, draft_id)
    if d.campaign_lead_id:
        raise HTTPException(409, "Campaign emails are managed from the campaign")
    if d.status == "sent":
        raise HTTPException(409, "This email was already sent")
    db.delete(d)
    db.commit()


@router.post("/drafts/{draft_id}/insert-video")
def insert_video(draft_id: int, data: InsertVideoIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    d = get_draft(db, user, draft_id)
    _guard_edit(db, d)
    v = db.get(Video, data.video_id)
    if not v or v.lead_id != d.lead_id:
        raise HTTPException(404, "Video not found for this lead")
    if not v.loom_url:
        raise HTTPException(400, "Save the Loom link on the video first")
    block = f"I recorded a short video for you: {{{{video_link}}}}"
    if "{{video_link}}" not in d.body:
        lines = d.body.rstrip().rsplit("\n\n", 1)  # insert before the sign-off
        d.body = (lines[0] + "\n\n" + block + "\n\n" + lines[1]) if len(lines) == 2 else d.body.rstrip() + "\n\n" + block
    db.commit()
    return draft_out(d)


@router.post("/drafts/{draft_id}/send")
def send_draft(draft_id: int, data: SendIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """One-off send of a single draft. The explicit confirm is recorded as an approval."""
    d = get_draft(db, user, draft_id)
    if d.campaign_lead_id:
        raise HTTPException(409, "Campaign emails are sent by the campaign after approval")
    if d.status == "sent":
        raise HTTPException(409, "Already sent")
    if not data.confirm:
        raise HTTPException(400, "Confirm that you reviewed this email and want it sent")
    if PLACEHOLDER.search(d.body):
        raise HTTPException(400, "Replace the [BRACKETED] placeholders before sending")
    org = db.get(Organization, user.org_id)
    lead = db.get(Lead, d.lead_id)
    integ = db.get(Integration, data.integration_id) if data.integration_id else default_integration(db, user.org_id)
    if not integ or integ.org_id != user.org_id:
        raise HTTPException(400, "Connect a mailbox in Integrations first")
    prior = db.scalar(select(Message).where(Message.lead_id == lead.id, Message.direction == "out").order_by(Message.id.desc()).limit(1))
    try:
        msg = send_email(db, org, lead, integ, d.subject, d.body, None, in_reply_to=prior.provider_message_id if (prior and d.step > 0) else "")
    except SendError as exc:
        raise HTTPException(400, str(exc)) from exc
    d.status, d.approved_by, d.approved_at = "sent", user.id, utcnow()
    db.add(Approval(org_id=user.org_id, entity_type="email", entity_id=d.id, requested_by=user.id, approved_by=user.id, status="approved", decided_at=utcnow()))
    if lead.status == "new":
        lead.status = "contacted"
    db.commit()
    return {"status": msg.status, "message_id": msg.id}
