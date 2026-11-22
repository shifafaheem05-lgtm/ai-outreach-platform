from fastapi import APIRouter, Depends, HTTPException
from app.core.validation import check_password
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.demo import forbid_demo_account
from app.core.deps import get_current_user, get_db, require_role
from app.core.security import hash_password
from app.models import AuditLog, Integration, Organization, User
from app.services.sending import org_problems

router = APIRouter(prefix="/settings", tags=["settings"])


class OrgPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    physical_address: str | None = Field(default=None, max_length=500)
    sender_name: str | None = Field(default=None, max_length=200)
    daily_send_limit: int | None = Field(default=None, ge=1, le=500)
    hourly_send_limit: int | None = Field(default=None, ge=1, le=100)


class UserIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def _pw(cls, v: str) -> str:
        return check_password(v)
    role: str = "member"


class UserPatch(BaseModel):
    role: str | None = None
    is_active: bool | None = None


def org_out(o: Organization) -> dict:
    return {k: getattr(o, k) for k in ("id", "name", "physical_address", "sender_name", "daily_send_limit", "hourly_send_limit")}


@router.get("/org")
def get_org(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return org_out(db.get(Organization, user.org_id))


@router.patch("/org")
def patch_org(data: OrgPatch, user: User = Depends(require_role("manager")), db: Session = Depends(get_db)):
    org = db.get(Organization, user.org_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(org, k, v.strip() if isinstance(v, str) else v)
    db.add(AuditLog(org_id=org.id, user_id=user.id, action="settings.org", entity="organization", entity_id=org.id))
    db.commit()
    return org_out(org)


@router.get("/readiness")
def readiness(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """What still blocks sending. Shown as a checklist in the UI."""
    org = db.get(Organization, user.org_id)
    has_mailbox = bool(db.scalar(select(func.count()).select_from(Integration).where(Integration.org_id == org.id, Integration.provider == "smtp")))
    connected = bool(db.scalar(select(func.count()).select_from(Integration).where(Integration.org_id == org.id, Integration.status == "connected")))
    checks = [
        {"id": "address", "label": "Postal address set (required in every email)", "ok": bool((org.physical_address or "").strip())},
        {"id": "sender", "label": "Sender name set", "ok": bool((org.sender_name or "").strip())},
        {"id": "mailbox", "label": "Mailbox added", "ok": has_mailbox},
        {"id": "tested", "label": "Mailbox tested successfully", "ok": connected},
    ]
    return {"ready": all(c["ok"] for c in checks), "checks": checks, "problems": org_problems(org)}


@router.get("/users")
def list_users(user: User = Depends(require_role("manager")), db: Session = Depends(get_db)):
    rows = db.scalars(select(User).where(User.org_id == user.org_id).order_by(User.id))
    return [{"id": u.id, "email": u.email, "name": u.name, "role": u.role, "is_active": u.is_active} for u in rows]


@router.post("/users", status_code=201)
def create_user(data: UserIn, user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    forbid_demo_account(user, "Adding users")
    if data.role not in ("admin", "manager", "member"):
        raise HTTPException(400, "role must be admin, manager or member")
    if db.scalar(select(User.id).where(User.email == data.email.lower())):
        raise HTTPException(409, "Email already registered")
    u = User(org_id=user.org_id, email=data.email.lower(), name=data.name, password_hash=hash_password(data.password), role=data.role)
    db.add(u)
    db.add(AuditLog(org_id=user.org_id, user_id=user.id, action="user.create", entity="user", meta={"email": u.email, "role": u.role}))
    db.commit()
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "is_active": u.is_active}


@router.patch("/users/{user_id}")
def patch_user(user_id: int, data: UserPatch, user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    forbid_demo_account(user, "Editing users")
    target = db.get(User, user_id)
    if not target or target.org_id != user.org_id:
        raise HTTPException(404, "User not found")
    changes = data.model_dump(exclude_unset=True)
    if "role" in changes and changes["role"] not in ("admin", "manager", "member"):
        raise HTTPException(400, "role must be admin, manager or member")
    losing_admin = target.role == "admin" and (changes.get("role", "admin") != "admin" or changes.get("is_active") is False)
    if losing_admin:
        admins = db.scalar(select(func.count()).select_from(User).where(User.org_id == user.org_id, User.role == "admin", User.is_active.is_(True))) or 0
        if admins <= 1:
            raise HTTPException(409, "The organization needs at least one active admin")
    for k, v in changes.items():
        setattr(target, k, v)
    db.add(AuditLog(org_id=user.org_id, user_id=user.id, action="user.update", entity="user", entity_id=target.id, meta=changes))
    db.commit()
    return {"id": target.id, "email": target.email, "name": target.name, "role": target.role, "is_active": target.is_active}


@router.get("/audit")
def audit(user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).where(AuditLog.org_id == user.org_id).order_by(AuditLog.id.desc()).limit(100))
    return [{"id": a.id, "action": a.action, "entity": a.entity, "entity_id": a.entity_id, "user_id": a.user_id, "meta": a.meta, "at": a.created_at.isoformat()} for a in rows]
