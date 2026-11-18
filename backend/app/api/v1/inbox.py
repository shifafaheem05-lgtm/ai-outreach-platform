import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.core.timeutil import utcnow
from app.models import Approval, Integration, Lead, Message, Organization, ReplyClassification, User
from app.services import inbox as inbox_svc
from app.services import reply_classifier
from app.services.sending import SendError, default_integration, send_email

router = APIRouter(prefix="/inbox", tags=["inbox"])
PLACEHOLDER = re.compile(r"\[[A-Z][A-Z ]{2,}[:\]]")


class SyncIn(BaseModel):
    integration_id: int | None = None


class ClassifyIn(BaseModel):
    label: str | None = None


class ReplyIn(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=10000)
    confirm: bool = False


def _msg(db: Session, user: User, message_id: int) -> Message:
    m = db.get(Message, message_id)
    if not m or m.org_id != user.org_id or m.direction != "in":
        raise HTTPException(404, "Message not found")
    return m


def _out(m: Message, c: ReplyClassification | None, lead: Lead) -> dict:
    return {
        "id": m.id, "lead_id": lead.id, "company_name": lead.company_name, "contact_name": lead.contact_name, "email": lead.email,
        "subject": m.subject, "body": m.body, "received_at": m.sent_at.isoformat() if m.sent_at else None,
        "label": c.label if c else None, "confidence": c.confidence if c else None,
        "suggested_response": c.suggested_response if c else "", "reviewed": c.reviewed if c else False,
    }


@router.get("")
def list_inbox(label: str = "", reviewed: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = (
        select(Message, ReplyClassification, Lead)
        .join(Lead, Lead.id == Message.lead_id)
        .outerjoin(ReplyClassification, ReplyClassification.message_id == Message.id)
        .where(Message.org_id == user.org_id, Message.direction == "in")
        .order_by(Message.id.desc()).limit(200)
    )
    if label:
        q = q.where(ReplyClassification.label == label)
    if reviewed in ("true", "false"):
        q = q.where(ReplyClassification.reviewed == (reviewed == "true"))
    return [_out(m, c, l) for m, c, l in db.execute(q).all()]


@router.post("/sync")
def sync(data: SyncIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    org = db.get(Organization, user.org_id)
    integ = db.get(Integration, data.integration_id) if data.integration_id else default_integration(db, user.org_id)
    if not integ or integ.org_id != user.org_id:
        raise HTTPException(400, "Connect a mailbox in Integrations first")
    try:
        return inbox_svc.sync_inbox(db, org, integ)
    except SendError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{message_id}/classify")
def classify(message_id: int, data: ClassifyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = _msg(db, user, message_id)
    lead = db.get(Lead, m.lead_id)
    org = db.get(Organization, user.org_id)
    c = db.scalar(select(ReplyClassification).where(ReplyClassification.message_id == m.id))
    if data.label:
        if data.label not in reply_classifier.LABELS:
            raise HTTPException(400, f"label must be one of {', '.join(reply_classifier.LABELS)}")
        label, confidence, opt_out = data.label, 1.0, False  # a human decision
    else:
        r = reply_classifier.classify(m.subject, m.body)
        label, confidence, opt_out = r["label"], r["confidence"], r["opt_out"]
    if not c:
        c = ReplyClassification(message_id=m.id, label=label)
        db.add(c)
    c.label, c.confidence = label, confidence
    c.suggested_response = reply_classifier.suggested_response(label, lead, org, opt_out)
    if label == "meeting_requested":
        lead.status = "meeting"
    db.commit()
    return _out(m, c, lead)


@router.post("/{message_id}/reviewed")
def mark_reviewed(message_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = _msg(db, user, message_id)
    c = db.scalar(select(ReplyClassification).where(ReplyClassification.message_id == m.id))
    if c:
        c.reviewed = True
        db.commit()
    return {"ok": True}


@router.post("/{message_id}/reply")
def reply(message_id: int, data: ReplyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Send a reply. The explicit confirm is stored as an approval; AI/template suggestions are never sent automatically."""
    m = _msg(db, user, message_id)
    if not data.confirm:
        raise HTTPException(400, "Confirm that you reviewed this reply and want it sent")
    if PLACEHOLDER.search(data.body):
        raise HTTPException(400, "Replace the [BRACKETED] placeholders before sending")
    lead = db.get(Lead, m.lead_id)
    org = db.get(Organization, user.org_id)
    integ = default_integration(db, user.org_id)
    if not integ:
        raise HTTPException(400, "Connect a mailbox in Integrations first")
    try:
        sent = send_email(db, org, lead, integ, data.subject, data.body, m.campaign_id, in_reply_to=m.provider_message_id, references=m.provider_message_id, thread_id=m.thread_id)
    except SendError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.add(Approval(org_id=user.org_id, entity_type="reply", entity_id=m.id, requested_by=user.id, approved_by=user.id, status="approved", decided_at=utcnow()))
    c = db.scalar(select(ReplyClassification).where(ReplyClassification.message_id == m.id))
    if c:
        c.reviewed = True
    db.commit()
    return {"status": sent.status, "message_id": sent.id}
