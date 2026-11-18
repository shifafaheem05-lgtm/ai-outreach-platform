"""Campaign workflow: draft -> pending_approval -> approved -> running -> completed.

Nothing is sent until a manager approves the campaign AND someone starts it. The approval
covers the whole sequence (initial email + follow-ups), whose drafts the approver can read.
"""
import logging
import random
import time
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.timeutil import as_utc, utcnow
from app.models import (
    Approval, AuditLog, Campaign, CampaignLead, EmailDraft, Integration, Lead, Organization,
    ResearchReport, User,
)
from app.services import email_writer
from app.services.sending import (
    SendError, capacity, is_suppressed, org_problems, send_email,
)

log = logging.getLogger(__name__)
MAX_DRAFT_LEADS_PER_CALL = 50
MAX_SENDS_PER_TICK = 20
CLAIM_MINUTES = 15  # a claimed row is not retried for this long (covers crashes and transient SMTP errors)


class WorkflowError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def audit(db: Session, org_id: int, user_id: int | None, action: str, campaign_id: int | None = None, **meta) -> None:
    db.add(AuditLog(org_id=org_id, user_id=user_id, action=action, entity="campaign", entity_id=campaign_id, meta=meta))


def ineligible_reason(db: Session, org_id: int, lead: Lead) -> str | None:
    if not lead.email:
        return "no email address"
    if lead.email_status == "invalid":
        return "email marked invalid"
    if lead.status == "unsubscribed" or is_suppressed(db, org_id, lead.email):
        return "opted out / suppressed"
    return None


def add_leads(db: Session, campaign: Campaign, lead_ids: list[int]) -> dict:
    if campaign.status != "draft":
        raise WorkflowError("Leads can only be added while the campaign is a draft.", 409)
    existing = set(db.scalars(select(CampaignLead.lead_id).where(CampaignLead.campaign_id == campaign.id)))
    added, skipped = 0, []
    for lead in db.scalars(select(Lead).where(Lead.org_id == campaign.org_id, Lead.id.in_(lead_ids))):
        reason = "already in campaign" if lead.id in existing else ineligible_reason(db, campaign.org_id, lead)
        if reason:
            skipped.append({"lead_id": lead.id, "company": lead.company_name, "reason": reason})
            continue
        db.add(CampaignLead(campaign_id=campaign.id, lead_id=lead.id))
        added += 1
    db.commit()
    return {"added": added, "skipped": skipped}


def generate_drafts(db: Session, campaign: Campaign, org: Organization, variant: str, regenerate: bool = False) -> dict:
    if campaign.status != "draft":
        raise WorkflowError("Drafts can only be generated while the campaign is a draft.", 409)
    steps = campaign.max_followups + 1
    created_for = remaining = 0
    rows = list(db.scalars(select(CampaignLead).where(CampaignLead.campaign_id == campaign.id).order_by(CampaignLead.id)))
    for cl in rows:
        have = db.scalar(select(func.count()).select_from(EmailDraft).where(EmailDraft.campaign_lead_id == cl.id)) or 0
        if have >= steps and not regenerate:
            continue
        if created_for >= MAX_DRAFT_LEADS_PER_CALL:
            remaining += 1
            continue
        if have:
            for d in db.scalars(select(EmailDraft).where(EmailDraft.campaign_lead_id == cl.id)):
                db.delete(d)
        lead = db.get(Lead, cl.lead_id)
        report = db.scalar(select(ResearchReport).where(ResearchReport.lead_id == lead.id).order_by(ResearchReport.id.desc()).limit(1))
        for step, mail in enumerate(email_writer.generate_sequence(lead, report, campaign.tone, org, variant, campaign.max_followups)):
            db.add(EmailDraft(campaign_lead_id=cl.id, lead_id=lead.id, step=step, variant=variant, subject=mail["subject"], body=mail["body"]))
        created_for += 1
        db.flush()
    db.commit()
    return {"generated_for": created_for, "remaining": remaining}


def submit_for_approval(db: Session, campaign: Campaign, org: Organization, user: User) -> Approval:
    if campaign.status != "draft":
        raise WorkflowError("Only draft campaigns can be submitted.", 409)
    problems = org_problems(org)
    integration = db.get(Integration, campaign.sender_integration_id) if campaign.sender_integration_id else None
    if not integration or integration.org_id != org.id:
        problems.append("Choose a connected sending mailbox for this campaign.")
    leads = list(db.scalars(select(CampaignLead).where(CampaignLead.campaign_id == campaign.id)))
    if not leads:
        problems.append("Add at least one lead.")
    steps = campaign.max_followups + 1
    for cl in leads:
        n = db.scalar(select(func.count()).select_from(EmailDraft).where(EmailDraft.campaign_lead_id == cl.id)) or 0
        if n < steps:
            problems.append("Generate drafts for every lead before submitting.")
            break
    if problems:
        raise WorkflowError(" ".join(dict.fromkeys(problems)))
    approval = Approval(org_id=org.id, entity_type="campaign", entity_id=campaign.id, requested_by=user.id)
    campaign.status = "pending_approval"
    db.add(approval)
    audit(db, org.id, user.id, "campaign.submit", campaign.id)
    db.commit()
    return approval


def decide(db: Session, campaign: Campaign, user: User, approve: bool) -> Campaign:
    approval = db.scalar(
        select(Approval).where(Approval.entity_type == "campaign", Approval.entity_id == campaign.id, Approval.status == "pending")
        .order_by(Approval.id.desc()).limit(1)
    )
    if campaign.status != "pending_approval" or not approval:
        raise WorkflowError("This campaign is not waiting for approval.", 409)
    approval.status, approval.approved_by, approval.decided_at = ("approved" if approve else "rejected"), user.id, utcnow()
    cl_ids = list(db.scalars(select(CampaignLead.id).where(CampaignLead.campaign_id == campaign.id)))
    drafts = db.scalars(select(EmailDraft).where(EmailDraft.campaign_lead_id.in_(cl_ids))) if cl_ids else []
    for d in drafts:
        if d.status != "sent":
            d.status, d.approved_by, d.approved_at = ("approved", user.id, utcnow()) if approve else ("draft", None, None)
    campaign.status = "approved" if approve else "draft"
    audit(db, campaign.org_id, user.id, "campaign.approve" if approve else "campaign.reject", campaign.id)
    db.commit()
    return campaign


def revert_to_draft(db: Session, campaign: Campaign, user: User) -> None:
    if campaign.status not in ("pending_approval", "approved", "paused"):
        raise WorkflowError("Pause a running campaign first, then revert it.", 409)
    cl_ids = list(db.scalars(select(CampaignLead.id).where(CampaignLead.campaign_id == campaign.id)))
    for d in db.scalars(select(EmailDraft).where(EmailDraft.campaign_lead_id.in_(cl_ids))) if cl_ids else []:
        if d.status == "approved":
            d.status, d.approved_by, d.approved_at = "draft", None, None
    for a in db.scalars(select(Approval).where(Approval.entity_type == "campaign", Approval.entity_id == campaign.id, Approval.status == "pending")):
        a.status, a.decided_at = "rejected", utcnow()
    campaign.status = "draft"
    audit(db, campaign.org_id, user.id, "campaign.revert", campaign.id)
    db.commit()


def start(db: Session, campaign: Campaign, user: User) -> None:
    if campaign.status not in ("approved", "paused"):
        raise WorkflowError("A campaign must be approved before it can start.", 409)
    start_at = utcnow()
    raw = (campaign.schedule or {}).get("start_at")
    if raw:
        from datetime import datetime

        try:
            start_at = max(start_at, as_utc(datetime.fromisoformat(raw.replace("Z", "+00:00"))))
        except ValueError:
            pass
    for cl in db.scalars(select(CampaignLead).where(CampaignLead.campaign_id == campaign.id, CampaignLead.state == "pending")):
        cl.state, cl.next_send_at = "active", start_at
    campaign.status = "running"
    audit(db, campaign.org_id, user.id, "campaign.start", campaign.id)
    db.commit()


def pause(db: Session, campaign: Campaign, user: User) -> None:
    if campaign.status != "running":
        raise WorkflowError("Only running campaigns can be paused.", 409)
    campaign.status = "paused"
    audit(db, campaign.org_id, user.id, "campaign.pause", campaign.id)
    db.commit()


def in_send_window(schedule: dict, now) -> bool:
    schedule = schedule or {}
    local = now + timedelta(hours=float(schedule.get("utc_offset_hours", 0)))
    if schedule.get("weekdays_only") and local.weekday() >= 5:
        return False
    start_h, end_h = schedule.get("window_start"), schedule.get("window_end")
    if start_h is None or end_h is None:
        return True
    return int(start_h) <= local.hour < int(end_h)


def process_due(db: Session, org_id: int | None = None) -> dict:
    """Send everything that is due. Safe to call repeatedly (scheduler tick or manual)."""
    stats = {"sent": 0, "bounced": 0, "blocked": 0, "waiting": 0}
    now = utcnow()
    q = select(Campaign).where(Campaign.status == "running")
    if org_id:
        q = q.where(Campaign.org_id == org_id)
    total_sent = 0
    for campaign in list(db.scalars(q)):
        org = db.get(Organization, campaign.org_id)
        integration = db.get(Integration, campaign.sender_integration_id) if campaign.sender_integration_id else None
        if not integration or not in_send_window(campaign.schedule, now):
            stats["waiting"] += 1
            continue
        due = db.scalars(
            select(CampaignLead).where(CampaignLead.campaign_id == campaign.id, CampaignLead.state == "active", CampaignLead.next_send_at <= now)
            .order_by(CampaignLead.next_send_at, CampaignLead.id)
        )
        for cl in list(due):
            if total_sent >= MAX_SENDS_PER_TICK:
                break
            hour_left, day_left = capacity(db, org)
            if hour_left <= 0 or day_left <= 0:
                stats["waiting"] += 1
                break
            # Atomic claim. "Is it due?" is tested inside the UPDATE itself, so when two workers/ticks
            # race (or this loop holds a stale row another worker already advanced) exactly one wins
            # and nobody sends twice or sends a follow-up early.
            original_due = cl.next_send_at
            claimed = db.execute(
                update(CampaignLead)
                .where(CampaignLead.id == cl.id, CampaignLead.state == "active", CampaignLead.next_send_at <= now)
                .values(next_send_at=utcnow() + timedelta(minutes=CLAIM_MINUTES))
                .execution_options(synchronize_session=False)  # evaluated by the DB; cl is refreshed below
            ).rowcount
            db.commit()
            if claimed != 1:
                continue
            db.refresh(cl)
            lead = db.get(Lead, cl.lead_id)
            draft = db.scalar(select(EmailDraft).where(EmailDraft.campaign_lead_id == cl.id, EmailDraft.step == cl.current_step))
            if not draft or draft.status != "approved":
                cl.next_send_at = original_due  # nothing to send yet: release the claim
                db.commit()
                stats["blocked"] += 1
                continue
            prev = db.scalar(
                select(EmailDraft).where(EmailDraft.campaign_lead_id == cl.id, EmailDraft.status == "sent").order_by(EmailDraft.step.desc()).limit(1)
            )
            thread = ""
            if prev:
                from app.models import Message

                last = db.scalar(select(Message).where(Message.lead_id == lead.id, Message.campaign_id == campaign.id, Message.direction == "out").order_by(Message.id.desc()).limit(1))
                thread = last.provider_message_id if last else ""
            try:
                msg = send_email(db, org, lead, integration, draft.subject, draft.body, campaign.id, in_reply_to=thread, references=thread, thread_id=thread)
            except SendError as exc:
                if exc.kind == "blocked":
                    cl.state = "opted_out" if "opted out" in str(exc).lower() or "suppression" in str(exc).lower() else "blocked"
                    stats["blocked"] += 1
                    db.commit()
                    continue
                if exc.kind in ("auth", "limit"):
                    cl.next_send_at = original_due  # nothing was sent: release the claim
                    db.commit()
                if exc.kind == "auth":
                    campaign.status = "paused"
                    audit(db, org.id, None, "campaign.auto_pause", campaign.id, reason=str(exc))
                    db.commit()
                    break
                if exc.kind == "limit":
                    break
                log.warning("Send failed for lead %s: %s", lead.id, exc)
                continue
            if msg.status == "bounced":
                cl.state, cl.next_send_at = "bounced", None
                stats["bounced"] += 1
            else:
                draft.status = "sent"
                cl.current_step += 1
                if lead.status == "new":
                    lead.status = "contacted"
                intervals = campaign.followup_intervals or []
                if cl.current_step > campaign.max_followups:
                    cl.state, cl.next_send_at = "completed", None
                else:
                    days = intervals[min(cl.current_step - 1, len(intervals) - 1)] if intervals else 3
                    cl.next_send_at = utcnow() + timedelta(days=days)
                stats["sent"] += 1
                total_sent += 1
            db.commit()
            delay = random.uniform(settings.send_delay_min, settings.send_delay_max)
            if delay > 0:
                time.sleep(delay)
        remaining = db.scalar(
            select(func.count()).select_from(CampaignLead).where(CampaignLead.campaign_id == campaign.id, CampaignLead.state.in_(("pending", "active")))
        )
        if not remaining and campaign.status == "running":
            campaign.status = "completed"
            db.commit()
    return stats
