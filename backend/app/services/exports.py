"""CSV / Excel exports. Cells that start with = + - @ are prefixed with ' to block spreadsheet formula injection."""
import csv
import io

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Lead
from app.services.analytics import campaign_stats

LEAD_COLUMNS = ["company_name", "website", "industry", "location", "company_size", "contact_name", "contact_title", "email", "email_status", "score", "tier", "status", "category", "source", "region_flag"]


def safe(value):
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _lead_rows(db: Session, org_id: int) -> list[list]:
    leads = db.scalars(select(Lead).where(Lead.org_id == org_id).order_by(Lead.score.desc(), Lead.id))
    return [[safe(getattr(l, c)) for c in LEAD_COLUMNS] + [safe(", ".join(l.tags or []))] for l in leads]


def leads_csv(db: Session, org_id: int) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(LEAD_COLUMNS + ["tags"])
    w.writerows(_lead_rows(db, org_id))
    return buf.getvalue().encode("utf-8-sig")  # BOM so Excel opens UTF-8 correctly


def report_xlsx(db: Session, org_id: int) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Leads"
    ws.append(LEAD_COLUMNS + ["tags"])
    for row in _lead_rows(db, org_id):
        ws.append(row)
    cs = wb.create_sheet("Campaigns")
    cols = ["name", "status", "leads", "sent", "bounced", "replied", "reply_rate", "bounce_rate", "positive", "meetings"]
    cs.append(cols)
    for c in campaign_stats(db, org_id):
        cs.append([safe(c[k]) for k in cols])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
