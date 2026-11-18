import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models import AuditLog, Organization, User
from app.schemas import LoginIn, RefreshIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _tokens(user: User) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


_FAILURES: dict[tuple[str, str], list[float]] = {}
WINDOW = 15 * 60


def _authenticate(db: Session, email: str, password: str, ip: str = "") -> User:
    key = (ip, email.lower())
    now = time.monotonic()
    recent = [t for t in _FAILURES.get(key, []) if now - t < WINDOW]
    if len(recent) >= settings.login_max_failures:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts. Try again in 15 minutes.")
    user = db.scalar(select(User).where(User.email == email.lower()))
    if not user or not verify_password(password, user.password_hash) or not user.is_active:
        _FAILURES[key] = recent + [now]
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    _FAILURES.pop(key, None)
    return user


@router.post("/register", response_model=TokenOut, status_code=201)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    email = data.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
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
    user_id = decode_token(data.refresh_token, "refresh")
    user = db.get(User, user_id) if user_id else None
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    return _tokens(user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
