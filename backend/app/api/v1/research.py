from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.leads import get_lead_or_404
from app.core.deps import get_current_user, get_db
from app.models import ResearchReport, User
from app.services.research import run_research

router = APIRouter(prefix="/leads", tags=["research"])


def report_out(r: ResearchReport) -> dict:
    return {
        "id": r.id,
        "lead_id": r.lead_id,
        "summary": r.summary,
        "products_services": r.products_services,
        "pain_points": r.pain_points,
        "opportunities": r.opportunities,
        "sources": r.sources or [],
        "model": r.model,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.post("/{lead_id}/research")
def research_lead(lead_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lead = get_lead_or_404(db, user, lead_id)
    if not lead.website:
        raise HTTPException(400, "This lead has no website to research")
    return report_out(run_research(db, lead, user.id))


@router.get("/{lead_id}/research")
def latest_research(lead_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_lead_or_404(db, user, lead_id)
    report = db.scalar(
        select(ResearchReport).where(ResearchReport.lead_id == lead_id).order_by(ResearchReport.id.desc()).limit(1)
    )
    if not report:
        raise HTTPException(404, "No research yet")
    return report_out(report)
