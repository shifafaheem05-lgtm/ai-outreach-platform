from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.emails import draft_out, followup_for, _check_tone
from app.api.v1.leads import get_lead_or_404
from app.core.deps import get_current_user, get_db
from app.models import User
from app.services.followups import due_followups

router = APIRouter(prefix="/followups", tags=["followups"])


class GenerateIn(BaseModel):
    lead_id: int
    tone: str = "professional"


@router.get("/due")
def due(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return due_followups(db, user.org_id)


@router.post("/generate")
def generate(data: GenerateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create a context-aware follow-up DRAFT. Nothing is sent until you approve it (POST /emails/drafts/{id}/send)."""
    _check_tone(data.tone)
    return draft_out(followup_for(db, user, get_lead_or_404(db, user, data.lead_id), data.tone))
