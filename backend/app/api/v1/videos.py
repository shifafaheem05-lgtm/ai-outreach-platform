from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.emails import latest_report
from app.api.v1.leads import get_lead_or_404
from app.core.deps import get_current_user, get_db
from app.models import AuditLog, Lead, Organization, User, Video
from app.services import video_scripts as vs

router = APIRouter(prefix="/videos", tags=["videos"])


class ScriptIn(BaseModel):
    lead_id: int
    campaign_id: int | None = None
    tone: str = "friendly"


class VideoPatch(BaseModel):
    script: str | None = Field(default=None, max_length=8000)
    description: str | None = Field(default=None, max_length=2000)


class LinkIn(BaseModel):
    loom_url: str


class ViewsIn(BaseModel):
    views: int = Field(ge=0, le=10_000_000)


def video_out(v: Video, lead: Lead | None = None) -> dict:
    spoken_words = vs.word_count(__import__("re").sub(r"\[[^\]]*\]", "", v.script or ""))
    return {
        "id": v.id, "lead_id": v.lead_id, "company_name": lead.company_name if lead else None, "campaign_id": v.campaign_id,
        "script": v.script, "intro": v.intro, "description": v.description, "loom_url": v.loom_url, "source": v.source,
        "status": v.status, "views": v.views, "word_count": spoken_words, "est_seconds": round(spoken_words / vs.WPM * 60),
        "has_cover": True, "created_at": v.created_at.isoformat() if v.created_at else None,
    }


def get_video(db: Session, user: User, video_id: int) -> Video:
    v = db.get(Video, video_id)
    if not v or v.org_id != user.org_id:
        raise HTTPException(404, "Video not found")
    return v


@router.get("/capabilities")
def capabilities(user: User = Depends(get_current_user)):
    return {
        "loom_api_upload": False,
        "loom_view_analytics": False,
        "ai_voiceover": False,
        "notes": [
            "Loom has no public API for creating or uploading videos, so you record in Loom and paste the share link here.",
            "Loom does not expose viewer analytics to this app; view counts are optional and entered by you.",
            "AI voiceover is not implemented. Use your own voice; if you ever add synthetic voice, disclose it and get the recipient's consent where required.",
        ],
        "workflow": ["Generate script", "Record in Loom (you)", "Paste Loom link", "Insert into email draft", "Approve and send"],
    }


@router.post("/script", status_code=201)
def create_script(data: ScriptIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lead = get_lead_or_404(db, user, data.lead_id)
    org = db.get(Organization, user.org_id)
    out = vs.generate(lead, latest_report(db, lead.id), org, data.tone)
    v = Video(
        org_id=user.org_id, lead_id=lead.id, campaign_id=data.campaign_id, script=out["script"], intro=out["intro"],
        description=out["description"], thumbnail_url="", source="loom_manual", status="awaiting_recording",
    )
    db.add(v)
    db.add(AuditLog(org_id=user.org_id, user_id=user.id, action="video.script", entity="video", meta={"lead_id": lead.id}))
    db.commit()
    return {**video_out(v, lead), "checklist": out["checklist"], "warnings": out["warnings"], "thumbnail_text": out["thumbnail_text"]}


@router.get("")
def list_videos(lead_id: int | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = select(Video, Lead).join(Lead, Lead.id == Video.lead_id).where(Video.org_id == user.org_id).order_by(Video.id.desc()).limit(100)
    if lead_id:
        q = q.where(Video.lead_id == lead_id)
    return [video_out(v, l) for v, l in db.execute(q).all()]


@router.patch("/{video_id}")
def patch_video(video_id: int, data: VideoPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    v = get_video(db, user, video_id)
    for k, val in data.model_dump(exclude_unset=True).items():
        setattr(v, k, val)
    db.commit()
    return video_out(v, db.get(Lead, v.lead_id))


@router.patch("/{video_id}/link")
def set_link(video_id: int, data: LinkIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    v = get_video(db, user, video_id)
    url = vs.normalize_loom_url(data.loom_url)
    if not url:
        raise HTTPException(400, "That is not a Loom share link. It should look like https://www.loom.com/share/<32 characters>")
    v.loom_url, v.status = url, "published"
    db.commit()
    return video_out(v, db.get(Lead, v.lead_id))


@router.patch("/{video_id}/views")
def set_views(video_id: int, data: ViewsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    v = get_video(db, user, video_id)
    v.views = data.views
    db.commit()
    return video_out(v, db.get(Lead, v.lead_id))


@router.delete("/{video_id}", status_code=204)
def delete_video(video_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(get_video(db, user, video_id))
    db.commit()


@router.get("/{video_id}/cover.svg")
def cover(video_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    v = get_video(db, user, video_id)
    lead = db.get(Lead, v.lead_id)
    org = db.get(Organization, user.org_id)
    svg = vs.thumbnail_svg(lead.company_name, f"A quick idea for {lead.company_name}", vs.sender_name(org))
    return Response(svg, media_type="image/svg+xml", headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})
