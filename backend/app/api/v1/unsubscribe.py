"""Public opt-out endpoints (no login). GET only shows a confirmation page so mail scanners that
pre-fetch links cannot unsubscribe people by accident; POST (button or RFC 8058 one-click) acts."""
import html

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.models import AuditLog, CampaignLead, Lead
from app.services.sending import read_unsubscribe_token, suppress

router = APIRouter(tags=["unsubscribe"])

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Unsubscribe</title><style>body{{font-family:system-ui,sans-serif;background:#f8fafc;color:#1e293b;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}}
.c{{background:#fff;padding:2rem;border-radius:1rem;box-shadow:0 4px 24px rgba(0,0,0,.08);max-width:26rem;text-align:center}}
button{{background:#7c3aed;color:#fff;border:0;border-radius:.75rem;padding:.7rem 1.4rem;font-size:1rem;cursor:pointer}}</style></head>
<body><div class="c">{body}</div></body></html>"""


def _page(body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(PAGE.format(body=body), status_code=status)


@router.get("/unsubscribe/{token}", response_class=HTMLResponse)
def confirm_page(token: str):
    parsed = read_unsubscribe_token(token)
    if not parsed:
        return _page("<h2>Link not valid</h2><p>This unsubscribe link is invalid or expired.</p>", 400)
    _, email = parsed
    return _page(
        f"<h2>Unsubscribe</h2><p>Stop all emails to <b>{html.escape(email)}</b>?</p>"
        f'<form method="post"><button type="submit">Yes, unsubscribe me</button></form>'
    )


@router.post("/unsubscribe/{token}", response_class=HTMLResponse)
def do_unsubscribe(token: str, db: Session = Depends(get_db)):
    parsed = read_unsubscribe_token(token)
    if not parsed:
        return _page("<h2>Link not valid</h2><p>This unsubscribe link is invalid or expired.</p>", 400)
    org_id, email = parsed
    suppress(db, org_id, email, "unsubscribed")
    for lead in db.scalars(select(Lead).where(Lead.org_id == org_id, Lead.email == email)):
        lead.status = "unsubscribed"
        for cl in db.scalars(select(CampaignLead).where(CampaignLead.lead_id == lead.id, CampaignLead.state.in_(("pending", "active")))):
            cl.state, cl.next_send_at = "opted_out", None
    db.add(AuditLog(org_id=org_id, action="recipient.unsubscribe", entity="lead", meta={"email": email}))
    db.commit()
    return _page(f"<h2>You're unsubscribed</h2><p>{html.escape(email)} will not receive further emails.</p>")
