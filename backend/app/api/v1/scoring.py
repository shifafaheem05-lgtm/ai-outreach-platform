from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.leads import lead_out
from app.core.deps import get_current_user, get_db
from app.models import Lead, User
from app.services.scoring import MODEL_VERSION, run_scoring

router = APIRouter(prefix="/scoring", tags=["scoring"])


class ScoreIn(BaseModel):
    lead_ids: list[int] | None = None
    target_industries: list[str] = []


@router.post("/run")
def run(data: ScoreIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return run_scoring(db, user.org_id, data.lead_ids, data.target_industries)


@router.get("/summary")
def summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tiers = dict(db.execute(select(Lead.tier, func.count()).where(Lead.org_id == user.org_id).group_by(Lead.tier)).all())
    avg = db.scalar(select(func.avg(Lead.score)).where(Lead.org_id == user.org_id))
    top = db.scalars(select(Lead).where(Lead.org_id == user.org_id).order_by(Lead.score.desc(), Lead.id).limit(25))
    return {
        "model": MODEL_VERSION,
        "tiers": {t: tiers.get(t, 0) for t in ("hot", "warm", "cold")},
        "average_score": round(float(avg), 1) if avg is not None else 0,
        "top_leads": [lead_out(l) for l in top],
    }
