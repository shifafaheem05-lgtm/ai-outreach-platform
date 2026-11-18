"""Shared input validation helpers (used by several routers)."""
import re
from urllib.parse import urlparse

from email_validator import EmailNotValidError, validate_email

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HOST = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def strip_ctrl(value: str) -> str:
    """Remove NUL and other control characters (they break PostgreSQL and exports)."""
    return _CTRL.sub("", value or "")


def check_password(password: str) -> str:
    if not password.strip() or password != password.strip():
        raise ValueError("Password must not start or end with spaces")
    if not (any(c.isalpha() for c in password) and any(c.isdigit() for c in password)):
        raise ValueError("Password must contain at least one letter and one number")
    return password


def check_website(url: str) -> str:
    if not url:
        return url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not _HOST.match(host) or " " in url:
        raise ValueError("Website must be a valid address such as example.com")
    return url


def check_email(email: str) -> str:
    if not email:
        return email
    try:
        validate_email(email, check_deliverability=False)
    except EmailNotValidError as exc:
        raise ValueError(f"Invalid email address: {exc}") from exc
    return email
