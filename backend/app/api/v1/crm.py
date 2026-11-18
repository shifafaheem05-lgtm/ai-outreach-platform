from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.leads import get_lead_or_404, lead_out
from app.api.v1.research import report_out
from app.api.v1.videos import video_out
from app.core.deps import get_current_user, get_db
from app.models import LeadScoreEvent, Message, Note, ReplyClassification, ResearchReport, User, Video
from app.services import exports

router = APIRouter(prefix="/crm", tags=["crm"])


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


@router.get("/export")
def export(format: str = "csv", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if format == "xlsx":
        return Response(
            exports.report_xlsx(db, user.org_id),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="ai-outreach-report.xlsx"'},
        )
    if format != "csv":
        raise HTTPException(400, "format must be csv or xlsx")
    return Response(exports.leads_csv(db, user.org_id), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="leads.csv"'})


@router.get("/leads/{lead_id}")
def profile(lead_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lead = get_lead_or_404(db, user, lead_id)
    messages = db.execute(
        select(Message, ReplyClassification).outerjoin(ReplyClassification, ReplyClassification.message_id == Message.id)
        .where(Message.lead_id == lead.id).order_by(Message.sent_at, Message.id)
    ).all()
    report = db.scalar(select(ResearchReport).where(ResearchReport.lead_id == lead.id).order_by(ResearchReport.id.desc()).limit(1))
    notes = db.scalars(select(Note).where(Note.lead_id == lead.id).order_by(Note.id.desc()))
    scores = db.scalars(select(LeadScoreEvent).where(LeadScoreEvent.lead_id == lead.id).order_by(LeadScoreEvent.id.desc()).limit(1))
    return {
        "lead": lead_out(lead, bool(report)),
        "conversation": [
            {"id": m.id, "direction": m.direction, "subject": m.subject, "body": m.body, "status": m.status, "at": m.sent_at.isoformat() if m.sent_at else None, "label": c.label if c else None}
            for m, c in messages
        ],
        "research": report_out(report) if report else None,
        "videos": [video_out(v, lead) for v in db.scalars(select(Video).where(Video.lead_id == lead.id).order_by(Video.id.desc()))],
        "notes": [{"id": n.id, "body": n.body, "at": n.created_at.isoformat()} for n in notes],
        "score_breakdown": next(({"score": s.score, "features": s.features, "model": s.model_version} for s in scores), None),
    }


@router.post("/leads/{lead_id}/notes", status_code=201)
def add_note(lead_id: int, data: NoteIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lead = get_lead_or_404(db, user, lead_id)
    note = Note(lead_id=lead.id, user_id=user.id, body=data.body.strip())
    db.add(note)
    db.commit()
    return {"id": note.id, "body": note.body, "at": note.created_at.isoformat()}


@router.delete("/leads/{lead_id}/notes/{note_id}", status_code=204)
def delete_note(lead_id: int, note_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_lead_or_404(db, user, lead_id)
    note = db.get(Note, note_id)
    if not note or note.lead_id != lead_id:
        raise HTTPException(404, "Note not found")
    db.delete(note)
    db.commit()
