import imaplib
import json
import smtplib
import ssl

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_role
from app.core.security import encrypt_secret
from app.models import AuditLog, Campaign, Integration, User
from app.services.sending import get_credentials, send_smtp

router = APIRouter(prefix="/integrations", tags=["integrations"])

PRESETS = {
    "gmail": dict(smtp_host="smtp.gmail.com", smtp_port=465, security="ssl", imap_host="imap.gmail.com", imap_port=993),
    "outlook": dict(smtp_host="smtp.office365.com", smtp_port=587, security="starttls", imap_host="outlook.office365.com", imap_port=993),
}


class IntegrationIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    preset: str = "custom"  # gmail | outlook | custom
    username: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=255)
    from_email: str = ""
    smtp_host: str = ""
    smtp_port: int = 465
    security: str = "ssl"  # ssl | starttls | none
    imap_host: str = ""
    imap_port: int = 993


def integration_out(i: Integration) -> dict:
    try:
        creds = get_credentials(i)
    except Exception:  # noqa: BLE001
        creds = {}
    return {
        "id": i.id, "provider": i.provider, "label": i.label, "status": i.status, "capabilities": i.capabilities or {},
        "from_email": creds.get("from_email", ""), "smtp_host": creds.get("smtp_host", ""), "imap_host": creds.get("imap_host", ""),
    }


def _get(db: Session, user: User, integration_id: int) -> Integration:
    i = db.get(Integration, integration_id)
    if not i or i.org_id != user.org_id:
        raise HTTPException(404, "Integration not found")
    return i


@router.get("")
def list_integrations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [integration_out(i) for i in db.scalars(select(Integration).where(Integration.org_id == user.org_id).order_by(Integration.id))]


@router.post("", status_code=201)
def create_integration(data: IntegrationIn, user: User = Depends(require_role("manager")), db: Session = Depends(get_db)):
    cfg = {**data.model_dump(), **PRESETS.get(data.preset, {})}
    if not cfg["smtp_host"]:
        raise HTTPException(400, "SMTP host is required")
    if cfg["security"] not in ("ssl", "starttls", "none"):
        raise HTTPException(400, "security must be ssl, starttls or none")
    cfg["from_email"] = cfg["from_email"] or cfg["username"]
    cfg.pop("preset", None)
    cfg.pop("label", None)
    integ = Integration(
        org_id=user.org_id, provider="smtp", label=data.label, status="untested",
        encrypted_credentials=encrypt_secret(json.dumps(cfg)), capabilities={"send": True, "receive": bool(cfg["imap_host"])},
    )
    db.add(integ)
    db.add(AuditLog(org_id=user.org_id, user_id=user.id, action="integration.create", entity="integration", meta={"label": data.label}))
    db.commit()
    return integration_out(integ)


@router.post("/{integration_id}/test")
def test_integration(integration_id: int, user: User = Depends(require_role("manager")), db: Session = Depends(get_db)):
    integ = _get(db, user, integration_id)
    creds = get_credentials(integ)
    report: dict = {}
    try:
        ctx = ssl.create_default_context()
        if creds["security"] == "ssl":
            s = smtplib.SMTP_SSL(creds["smtp_host"], int(creds["smtp_port"]), timeout=20, context=ctx)
        else:
            s = smtplib.SMTP(creds["smtp_host"], int(creds["smtp_port"]), timeout=20)
            s.ehlo()
            if creds["security"] == "starttls":
                s.starttls(context=ctx)
                s.ehlo()
        s.login(creds["username"], creds["password"])
        s.quit()
        report["smtp"] = "ok"
    except smtplib.SMTPAuthenticationError:
        report["smtp"] = "Login failed. For Gmail use an App Password."
    except Exception as exc:  # noqa: BLE001
        report["smtp"] = f"Could not connect: {exc.__class__.__name__}"
    if creds.get("imap_host"):
        try:
            m = imaplib.IMAP4_SSL(creds["imap_host"], int(creds.get("imap_port", 993)), timeout=20)
            m.login(creds["username"], creds["password"])
            m.logout()
            report["imap"] = "ok"
        except Exception as exc:  # noqa: BLE001
            report["imap"] = f"Could not connect: {exc.__class__.__name__}"
    send_ok = report["smtp"] == "ok"
    integ.status = "connected" if send_ok else "error"
    integ.capabilities = {"send": send_ok, "receive": report.get("imap") == "ok"}
    db.commit()
    return {"status": integ.status, **report}


@router.post("/{integration_id}/send-test")
def send_test(integration_id: int, user: User = Depends(require_role("manager")), db: Session = Depends(get_db)):
    """Send a plain test message to the signed-in user's own address."""
    from email.message import EmailMessage

    integ = _get(db, user, integration_id)
    creds = get_credentials(integ)
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = creds["from_email"], user.email, "AI Outreach Pro test email"
    msg.set_content("Your mailbox is connected. This test was sent only to you.")
    try:
        send_smtp(creds, msg)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Test failed: {exc.__class__.__name__}") from exc
    return {"sent_to": user.email}


@router.delete("/{integration_id}", status_code=204)
def delete_integration(integration_id: int, user: User = Depends(require_role("manager")), db: Session = Depends(get_db)):
    integ = _get(db, user, integration_id)
    if db.scalar(select(Campaign.id).where(Campaign.sender_integration_id == integ.id)):
        raise HTTPException(409, "A campaign uses this mailbox")
    db.delete(integ)
    db.commit()
