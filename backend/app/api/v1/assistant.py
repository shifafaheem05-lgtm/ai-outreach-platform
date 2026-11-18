from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models import AssistantRun, AuditLog, User
from app.services.assistant import HELP, run_command

router = APIRouter(prefix="/assistant", tags=["assistant"])


class CommandIn(BaseModel):
    command: str = Field(min_length=2, max_length=500)


def _out(r: AssistantRun) -> dict:
    return {"id": r.id, "command": r.command, "status": r.status, "created_at": r.created_at.isoformat(), **(r.result or {})}


@router.post("/command")
def command(data: CommandIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run = AssistantRun(user_id=user.id, command=data.command.strip(), status="running")
    db.add(run)
    db.commit()
    try:
        result = run_command(db, user, data.command)
        run.status, run.result, run.plan = "done", result, {"intent": result.get("intent")}
    except Exception as exc:  # noqa: BLE001 - report to the user instead of a 500
        db.rollback()
        run.status, run.result = "failed", {"intent": "error", "message": f"That command failed ({exc.__class__.__name__}). Nothing was sent."}
    db.add(AuditLog(org_id=user.org_id, user_id=user.id, action="assistant.command", entity="assistant", meta={"intent": (run.result or {}).get("intent")}))
    db.commit()
    return _out(run)


@router.get("/runs")
def runs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(AssistantRun).where(AssistantRun.user_id == user.id).order_by(AssistantRun.id.desc()).limit(30))
    return [_out(r) for r in rows]


@router.get("/help")
def help_text(user: User = Depends(get_current_user)):
    return {"message": HELP}
