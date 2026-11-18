import base64
import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
from cryptography.fernet import Fernet
from jose import JWTError, jwt

from app.core.config import settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def _create_token(subject: str, token_type: str, expires: timedelta) -> str:
    payload = {
        "sub": subject,
        "type": token_type,
        "exp": datetime.now(timezone.utc) + expires,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_access_token(user_id: int) -> str:
    return _create_token(
        str(user_id), "access", timedelta(minutes=settings.access_token_expire_minutes)
    )


def create_refresh_token(user_id: int) -> str:
    return _create_token(
        str(user_id), "refresh", timedelta(days=settings.refresh_token_expire_days)
    )


def decode_token(token: str, expected_type: str) -> int | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        return None
    if payload.get("type") != expected_type:
        return None
    try:
        return int(payload["sub"])
    except (KeyError, ValueError):
        return None


def _fernet() -> Fernet:
    key = settings.encryption_key
    if not key:
        # Dev-only fallback: derive a key from SECRET_KEY. Set ENCRYPTION_KEY in production.
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()
