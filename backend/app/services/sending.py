"""Sending engine: compliance checks, limits, message building, SMTP delivery.

Every outbound email passes through `send_email`, which re-checks suppression, opt-out,
address validity, required org details and sending limits AT SEND TIME (not just when queued).
"""
import json
import logging
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

import jwt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decrypt_secret
from app.core.timeutil import utcnow
from app.models import Integration, Lead, Message, Organization, Suppression, Video

log = logging.getLogger(__name__)
SENT_STATES = ("sent", "delivered", "bounced")


class SendError(Exception):
    def __init__(self, message: str, kind: str = "blocked"):
        super().__init__(message)
        self.kind = kind  # blocked | limit | auth | smtp


# ---- unsubscribe tokens (stateless, signed) ---------------------------------
def make_unsubscribe_token(org_id: int, email: str) -> str:
    payload = {"org": org_id, "email": email.lower(), "type": "unsub", "exp": utcnow() + timedelta(days=365 * 3)}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def read_unsubscribe_token(token: str) -> tuple[int, str] | None:
    try:
        data = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if data.get("type") != "unsub":
        return None
    try:
        return int(data["org"]), str(data["email"])
    except (KeyError, ValueError, TypeError):
        return None


def unsubscribe_url(org_id: int, email: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}/unsubscribe/{make_unsubscribe_token(org_id, email)}"


# ---- credentials --------------------------------------------------------------
def get_credentials(integration: Integration) -> dict:
    return json.loads(decrypt_secret(integration.encrypted_credentials))


def default_integration(db: Session, org_id: int) -> Integration | None:
    rows = db.scalars(select(Integration).where(Integration.org_id == org_id, Integration.provider == "smtp").order_by(Integration.id))
    rows = list(rows)
    return next((i for i in rows if i.status == "connected"), rows[0] if rows else None)


# ---- compliance & capacity ----------------------------------------------------
def is_suppressed(db: Session, org_id: int, email: str) -> bool:
    return bool(db.scalar(select(Suppression.id).where(Suppression.org_id == org_id, Suppression.email == email.lower())))


def suppress(db: Session, org_id: int, email: str, reason: str) -> None:
    if email and not is_suppressed(db, org_id, email):
        db.add(Suppression(org_id=org_id, email=email.lower(), reason=reason))


def org_problems(org: Organization) -> list[str]:
    problems = []
    if not (org.physical_address or "").strip():
        problems.append("Add your organization's postal address in Settings (required in every email by CAN-SPAM).")
    if not (org.sender_name or "").strip():
        problems.append("Add a sender name in Settings.")
    return problems


def compliance_problems(db: Session, org: Organization, lead: Lead) -> list[str]:
    problems = org_problems(org)
    if not lead.email:
        problems.append("Lead has no email address.")
    elif lead.email_status == "invalid":
        problems.append("Lead's email address is marked invalid.")
    if lead.email and is_suppressed(db, org.id, lead.email):
        problems.append("Address is on the suppression list (unsubscribed, bounced or blocked).")
    if lead.status == "unsubscribed":
        problems.append("Lead has opted out.")
    return problems


def capacity(db: Session, org: Organization) -> tuple[int, int]:
    """(remaining this rolling hour, remaining this rolling 24h)."""
    now = utcnow()

    def sent_since(delta: timedelta) -> int:
        return db.scalar(
            select(func.count()).select_from(Message).where(
                Message.org_id == org.id, Message.direction == "out", Message.status.in_(SENT_STATES), Message.sent_at >= now - delta
            )
        ) or 0

    return (
        max(0, org.hourly_send_limit - sent_since(timedelta(hours=1))),
        max(0, org.daily_send_limit - sent_since(timedelta(hours=24))),
    )


# ---- building & delivering ------------------------------------------------------
def render_body(db: Session, lead: Lead, body: str) -> str:
    first = (lead.contact_name or "").split()[0] if lead.contact_name else ""
    body = body.replace("{{first_name}}", first).replace("{{company}}", lead.company_name)
    if "{{video_link}}" in body:
        video = db.scalar(
            select(Video).where(Video.lead_id == lead.id, Video.loom_url != "").order_by(Video.id.desc()).limit(1)
        )
        if not video:
            raise SendError("Email contains {{video_link}} but no Loom link is saved for this lead.")
        body = body.replace("{{video_link}}", video.loom_url)
    return body


def build_message(org: Organization, lead: Lead, creds: dict, subject: str, body: str, in_reply_to: str = "", references: str = "") -> EmailMessage:
    from_email = creds["from_email"]
    url = unsubscribe_url(org.id, lead.email)
    msg = EmailMessage()
    msg["From"] = formataddr((org.sender_name, from_email))
    msg["To"] = formataddr((lead.contact_name or "", lead.email))
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=from_email.split("@")[-1])
    msg["List-Unsubscribe"] = f"<{url}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = (references + " " + in_reply_to).strip()
    footer = f"\n\n--\n{org.sender_name}\n{org.physical_address}\nNot relevant? Unsubscribe here: {url}"
    msg.set_content(body.rstrip() + footer)
    return msg


def send_smtp(creds: dict, msg: EmailMessage) -> None:
    host, port, security = creds["smtp_host"], int(creds["smtp_port"]), creds.get("security", "ssl")
    ctx = ssl.create_default_context()
    if security == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=30, context=ctx)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        server.ehlo()
        if security == "starttls":
            server.starttls(context=ctx)
            server.ehlo()
    try:
        server.login(creds["username"], creds["password"])
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:  # noqa: BLE001
            pass


def send_email(
    db: Session, org: Organization, lead: Lead, integration: Integration, subject: str, body: str,
    campaign_id: int | None = None, in_reply_to: str = "", references: str = "", thread_id: str = "",
) -> Message:
    problems = compliance_problems(db, org, lead)
    if problems:
        raise SendError(" ".join(problems), "blocked")
    hour_left, day_left = capacity(db, org)
    if hour_left <= 0 or day_left <= 0:
        raise SendError("Sending limit reached (see Settings). It resets as older emails leave the rolling window.", "limit")
    body = render_body(db, lead, body)
    creds = get_credentials(integration)
    msg = build_message(org, lead, creds, subject, body, in_reply_to, references)
    record = Message(
        org_id=org.id, lead_id=lead.id, campaign_id=campaign_id, direction="out", subject=subject, body=body,
        provider_message_id=msg["Message-ID"], thread_id=thread_id or in_reply_to or msg["Message-ID"], sent_at=utcnow(),
    )
    try:
        send_smtp(creds, msg)
        record.status = "sent"
    except smtplib.SMTPAuthenticationError as exc:
        raise SendError("Mail login failed. For Gmail use an App Password (2-Step Verification must be on).", "auth") from exc
    except smtplib.SMTPRecipientsRefused:
        record.status = "bounced"  # permanent refusal by the server = hard bounce
        suppress(db, org.id, lead.email, "bounced")
        lead.email_status = "invalid"
    except (smtplib.SMTPException, OSError) as exc:
        log.warning("SMTP send failed: %s", exc)
        raise SendError(f"Could not send: {exc.__class__.__name__}", "smtp") from exc
    db.add(record)
    db.flush()
    return record
