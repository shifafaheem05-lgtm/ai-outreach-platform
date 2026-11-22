import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.demo import DEMO_EMAIL, DEMO_PASSWORD, MAX_DEMO_USERS, forbid_demo_account
from app.core.deps import get_current_user, get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models import AuditLog, Organization, User
from app.schemas import ChangePasswordIn, LoginIn, RefreshIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _tokens(user: User) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user.id, user.token_version),
        refresh_token=create_refresh_token(user.id, user.token_version),
    )


_FAILURES: dict[tuple[str, str], list[float]] = {}
WINDOW = 15 * 60
MAX_TRACKED = 10_000  # bound memory: a flood of distinct emails cannot grow this forever


def _prune_failures(now: float) -> None:
    for k in [k for k, ts in _FAILURES.items() if not any(now - t < WINDOW for t in ts)]:
        del _FAILURES[k]
    if len(_FAILURES) > MAX_TRACKED:  # still too many live entries: drop the oldest
        for k in sorted(_FAILURES, key=lambda k: max(_FAILURES[k]))[: len(_FAILURES) - MAX_TRACKED]:
            del _FAILURES[k]


def _authenticate(db: Session, email: str, password: str, ip: str = "") -> User:
    key = (ip, email.lower())
    now = time.monotonic()
    recent = [t for t in _FAILURES.get(key, []) if now - t < WINDOW]
    if len(recent) >= settings.login_max_failures:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts. Try again in 15 minutes.")
    user = db.scalar(select(User).where(User.email == email.lower()))
    if not user or not verify_password(password, user.password_hash) or not user.is_active:
        _FAILURES[key] = recent + [now]
        if len(_FAILURES) > MAX_TRACKED:
            _prune_failures(now)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    _FAILURES.pop(key, None)
    return user


@router.get("/config")
def public_config():
    """Public, non-sensitive switches the login page needs."""
    out = {"allow_registration": settings.allow_registration, "demo_mode": settings.demo_mode}
    if settings.demo_mode:  # the demo login is public by design
        out["demo_email"], out["demo_password"] = DEMO_EMAIL, DEMO_PASSWORD
    return out


@router.post("/register", response_model=TokenOut, status_code=201)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    if not settings.allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is disabled. Ask an administrator for an account.")
    email = data.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    if settings.demo_mode and (db.scalar(select(func.count()).select_from(User)) or 0) >= MAX_DEMO_USERS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The demo has reached its sign-up limit. Please use the shared demo login.")
    org = Organization(name=data.organization_name, sender_name=data.name)
    db.add(org)
    db.flush()
    user = User(
        org_id=org.id,
        email=email,
        name=data.name,
        password_hash=hash_password(data.password),
        role="admin",  # first user of a new organization is its admin
    )
    db.add(user)
    db.flush()
    db.add(AuditLog(org_id=org.id, user_id=user.id, action="user.register", entity="user", entity_id=user.id))
    db.commit()
    return _tokens(user)


@router.post("/login", response_model=TokenOut)
def login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    return _tokens(_authenticate(db, data.email, data.password, request.client.host if request.client else ""))


@router.post("/login/form", response_model=TokenOut, include_in_schema=False)
def login_form(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """OAuth2 form login so the Swagger UI 'Authorize' button works."""
    return _tokens(_authenticate(db, form.username, form.password, request.client.host if request.client else ""))


@router.post("/refresh", response_model=TokenOut)
def refresh(data: RefreshIn, db: Session = Depends(get_db)):
    decoded = decode_token(data.refresh_token, "refresh")
    user = db.get(User, decoded[0]) if decoded else None
    if not user or not user.is_active or user.token_version != decoded[1]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    return _tokens(user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/change-password", response_model=TokenOut)
def change_password(data: ChangePasswordIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Change the signed-in user's password. Every other session is signed out; this one gets fresh tokens."""
    forbid_demo_account(user, "Changing the password")
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    if data.new_password == data.current_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a password different from the current one")
    user.password_hash = hash_password(data.new_password)
    user.token_version += 1
    db.add(AuditLog(org_id=user.org_id, user_id=user.id, action="user.change_password", entity="user", entity_id=user.id))
    db.commit()
    return _tokens(user)
