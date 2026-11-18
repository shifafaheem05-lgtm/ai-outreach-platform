from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.campaigns import campaign_out
from app.core.deps import get_current_user, get_db, require_role
from app.models import Approval, Campaign, User
from app.services import campaigns as svc

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _out(db: Session, a: Approval) -> dict:
    name = None
    if a.entity_type == "campaign" and (c := db.get(Campaign, a.entity_id)):
        name = c.name
    return {
        "id": a.id, "entity_type": a.entity_type, "entity_id": a.entity_id, "entity_name": name, "status": a.status,
        "requested_by": a.requested_by, "approved_by": a.approved_by,
        "created_at": a.created_at.isoformat() if a.created_at else None, "decided_at": a.decided_at.isoformat() if a.decided_at else None,
    }


@router.get("")
def list_approvals(status: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = select(Approval).where(Approval.org_id == user.org_id).order_by(Approval.id.desc()).limit(100)
    if status:
        q = q.where(Approval.status == status)
    return [_out(db, a) for a in db.scalars(q)]


def _decide(approval_id: int, approve: bool, user: User, db: Session) -> dict:
    a = db.get(Approval, approval_id)
    if not a or a.org_id != user.org_id:
        raise HTTPException(404, "Approval not found")
    if a.entity_type != "campaign":
        raise HTTPException(400, "Only campaign approvals are decided here")
    campaign = db.get(Campaign, a.entity_id)
    try:
        svc.decide(db, campaign, user, approve)
    except svc.WorkflowError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    return campaign_out(db, campaign)


@router.post("/{approval_id}/approve")
def approve(approval_id: int, user: User = Depends(require_role("manager")), db: Session = Depends(get_db)):
    return _decide(approval_id, True, user, db)


@router.post("/{approval_id}/reject")
def reject(approval_id: int, user: User = Depends(require_role("manager")), db: Session = Depends(get_db)):
    return _decide(approval_id, False, user, db)
