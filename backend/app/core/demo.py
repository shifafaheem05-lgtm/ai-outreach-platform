"""Public-demo switch (DEMO_MODE). Lets visitors try the app safely: the shared demo account is protected,
real mail cannot be sent, and nothing can be pointed at an outside mail server."""
from fastapi import HTTPException, status

from app.core.config import settings

DEMO_EMAIL = "demo@aioutreach.pro"
DEMO_PASSWORD = "Demo1234!"
MAX_DEMO_USERS = 300  # bounds growth of the throwaway demo database


def forbid_in_demo(what: str) -> None:
    """Block an action for everyone while DEMO_MODE is on."""
    if settings.demo_mode:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"{what} is disabled in the public demo.")


def forbid_demo_account(user, what: str) -> None:
    """Block an action on the shared demo account (visitors must not lock each other out)."""
    if settings.demo_mode and user.email == DEMO_EMAIL:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"{what} is disabled for the shared demo account. Create your own workspace to try it.")
