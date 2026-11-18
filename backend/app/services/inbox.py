"""Inbox sync over IMAP (free: works with Gmail/Outlook app passwords).

- Read-only (BODY.PEEK, readonly select): the mailbox is never modified.
- Only mail from known leads is stored; everything else is ignored for privacy.
- A real reply stops the lead's follow-up sequence. Out-of-office auto-replies do not.
- Delivery-failure notices (bounces) mark the address invalid and add it to the suppression list.
"""
import imaplib
import logging
import re
from datetime import timedelta
from email import message_from_bytes, policy
from email.utils import parseaddr, parsedate_to_datetime

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import as_utc, utcnow
from app.models import CampaignLead, Lead, Message, Organization, ReplyClassification
from app.services import reply_classifier
from app.services.sending import SendError, get_credentials, suppress

log = logging.getLogger(__name__)
MAX_MESSAGES = 200
LOOKBACK_DAYS = 14
QUOTE_START = re.compile(r"^(on .{5,120} wrote:|-{2,}\s*original message\s*-{2,}|from:\s.+|>.*)$", re.I)
FINAL_RECIPIENT = re.compile(r"(?:final|original)-recipient:\s*(?:rfc822;)?\s*<?([^\s<>;]+@[^\s<>;]+)", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def extract_text(msg) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except Exception:  # noqa: BLE001
        return ""
    if part.get_content_type() == "text/html":
        content = BeautifulSoup(content, "html.parser").get_text("\n", strip=True)
    return content


def strip_quoted(text: str) -> str:
    kept: list[str] = []
    for line in text.splitlines():
        if QUOTE_START.match(line.strip()):
            break
        kept.append(line)
    return "\n".join(kept).strip()[:4000]


def is_bounce(msg, from_addr: str) -> bool:
    if any(w in from_addr for w in ("mailer-daemon", "postmaster")):
        return True
    return msg.get_content_type() == "multipart/report" and "delivery-status" in (msg.get_param("report-type") or "")


def _handle_bounce(db: Session, org: Organization, msg) -> bool:
    blob = ""
    for part in msg.walk():
        if part.get_content_type() in ("message/delivery-status", "text/plain", "text/rfc822-headers"):
            try:
                blob += str(part.get_content()) if part.get_content_type() != "message/delivery-status" else str(part.as_string())
            except Exception:  # noqa: BLE001
                continue
    candidates = [m.group(1).lower() for m in FINAL_RECIPIENT.finditer(blob)] or [e.lower() for e in EMAIL_RE.findall(blob)]
    for email in dict.fromkeys(candidates):
        lead = db.scalar(select(Lead).where(Lead.org_id == org.id, Lead.email == email))
        if not lead:
            continue
        lead.email_status = "invalid"
        suppress(db, org.id, email, "bounced")
        last = db.scalar(select(Message).where(Message.lead_id == lead.id, Message.direction == "out").order_by(Message.id.desc()).limit(1))
        if last and last.status != "bounced":
            last.status = "bounced"
        for cl in db.scalars(select(CampaignLead).where(CampaignLead.lead_id == lead.id, CampaignLead.state.in_(("pending", "active")))):
            cl.state, cl.next_send_at = "bounced", None
        return True
    return False


def process_raw(db: Session, org: Organization, raw: bytes) -> dict | None:
    """Handle one RFC822 message. Returns a small result dict, or None if it was ignored."""
    msg = message_from_bytes(raw, policy=policy.default)
    msgid = (msg["Message-ID"] or "").strip()
    if msgid and db.scalar(select(Message.id).where(Message.org_id == org.id, Message.provider_message_id == msgid, Message.direction == "in")):
        return None
    from_addr = parseaddr(str(msg["From"] or ""))[1].lower()
    if is_bounce(msg, from_addr):
        return {"type": "bounce"} if _handle_bounce(db, org, msg) else None
    lead = db.scalar(select(Lead).where(Lead.org_id == org.id, Lead.email == from_addr)) if from_addr else None
    if not lead:
        return None

    body = strip_quoted(extract_text(msg))
    subject = str(msg["Subject"] or "")
    auto = (str(msg["Auto-Submitted"] or "no").lower() != "no") or bool(msg["X-Autoreply"]) or str(msg["Precedence"] or "").lower() in ("auto_reply", "bulk", "junk")
    try:
        sent_at = as_utc(parsedate_to_datetime(str(msg["Date"]))) if msg["Date"] else utcnow()
    except (TypeError, ValueError):
        sent_at = utcnow()
    last_out = db.scalar(select(Message).where(Message.lead_id == lead.id, Message.direction == "out").order_by(Message.id.desc()).limit(1))
    record = Message(
        org_id=org.id, lead_id=lead.id, campaign_id=last_out.campaign_id if last_out else None, direction="in", subject=subject,
        body=body, provider_message_id=msgid, thread_id=str(msg["In-Reply-To"] or ""), status="received", sent_at=sent_at,
    )
    db.add(record)
    db.flush()

    result = reply_classifier.classify(subject, body, auto)
    label, opt_out = result["label"], result["opt_out"]
    db.add(ReplyClassification(
        message_id=record.id, label=label, confidence=result["confidence"],
        suggested_response=reply_classifier.suggested_response(label, lead, org, opt_out),
    ))

    if opt_out:
        suppress(db, org.id, lead.email, "unsubscribed")
        lead.status = "unsubscribed"
    if label != "out_of_office":  # a real person answered: stop the sequence
        for cl in db.scalars(select(CampaignLead).where(CampaignLead.lead_id == lead.id, CampaignLead.state.in_(("pending", "active")))):
            cl.state, cl.next_send_at = ("opted_out" if opt_out else "replied"), None
        if not opt_out:
            lead.status = "meeting" if label == "meeting_requested" else ("replied" if lead.status in ("new", "contacted", "replied") else lead.status)
    return {"type": "reply", "label": label, "opt_out": opt_out, "message_id": record.id}


def sync_inbox(db: Session, org: Organization, integration) -> dict:
    creds = get_credentials(integration)
    if not creds.get("imap_host"):
        raise SendError("This mailbox has no IMAP server configured, so replies cannot be read.", "blocked")
    counts = {"checked": 0, "replies": 0, "bounces": 0, "opt_outs": 0}
    try:
        box = imaplib.IMAP4_SSL(creds["imap_host"], int(creds.get("imap_port", 993)), timeout=30)
        box.login(creds["username"], creds["password"])
    except imaplib.IMAP4.error as exc:
        raise SendError("Mail login failed. For Gmail use an App Password and enable IMAP.", "auth") from exc
    except OSError as exc:
        raise SendError(f"Could not reach the mail server ({exc.__class__.__name__}).", "smtp") from exc
    try:
        box.select("INBOX", readonly=True)
        since = (utcnow() - timedelta(days=LOOKBACK_DAYS)).strftime("%d-%b-%Y")
        _, data = box.search(None, "SINCE", since)
        for num in data[0].split()[-MAX_MESSAGES:]:
            _, parts = box.fetch(num, "(BODY.PEEK[])")
            if not parts or not parts[0] or not isinstance(parts[0], tuple):
                continue
            counts["checked"] += 1
            res = process_raw(db, org, parts[0][1])
            if res and res["type"] == "reply":
                counts["replies"] += 1
                counts["opt_outs"] += int(res["opt_out"])
            elif res:
                counts["bounces"] += 1
    finally:
        try:
            box.logout()
        except Exception:  # noqa: BLE001
            pass
    db.commit()
    return counts
