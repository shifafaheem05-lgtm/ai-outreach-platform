from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models import User
from app.services import analytics

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview")
def overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return analytics.overview(db, user.org_id)


@router.get("/campaigns")
def campaigns(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return analytics.campaign_stats(db, user.org_id)
