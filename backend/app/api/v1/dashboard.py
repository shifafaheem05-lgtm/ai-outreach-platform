from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models import User
from app.services.analytics import dashboard_summary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return dashboard_summary(db, user.org_id)
