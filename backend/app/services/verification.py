"""Free email verification: syntax + disposable/role checks + DNS (MX) lookup.

Honest limit: this proves the domain can receive mail, NOT that the mailbox exists.
Only SMTP probing or a paid service can do that, so good addresses are marked
"valid" (deliverable domain) and role/disposable ones "risky".
"""
import dns.exception
import dns.resolver
from email_validator import EmailNotValidError, validate_email

ROLE_LOCALPARTS = {
    "info", "admin", "sales", "contact", "support", "hello", "office", "team",
    "help", "noreply", "no-reply", "billing", "jobs", "careers", "webmaster",
}
DISPOSABLE_DOMAINS = {
    "mailinator.com", "10minutemail.com", "guerrillamail.com", "tempmail.com",
    "yopmail.com", "trashmail.com", "throwawaymail.com", "sharklasers.com",
}


def _mx_lookup(domain: str) -> str:
    """Return 'ok', 'none' (domain cannot receive mail) or 'error' (lookup failed)."""
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 4
    try:
        if len(resolver.resolve(domain, "MX")) > 0:
            return "ok"
    except dns.resolver.NXDOMAIN:
        return "none"
    except dns.resolver.NoAnswer:
        pass  # no MX: mail may still go to the A record (RFC 5321 implicit MX)
    except (dns.exception.Timeout, dns.resolver.NoNameservers):
        return "error"
    except Exception:  # noqa: BLE001
        return "error"
    try:
        resolver.resolve(domain, "A")
        return "ok"
    except dns.resolver.NXDOMAIN:
        return "none"
    except dns.resolver.NoAnswer:
        return "none"
    except Exception:  # noqa: BLE001
        return "error"


def verify_email(email: str, _cache: dict | None = None) -> tuple[str, str]:
    """Return (status, reason). status: valid | risky | invalid | unverified."""
    email = (email or "").strip().lower()
    if not email:
        return "invalid", "No email address"
    try:
        parsed = validate_email(email, check_deliverability=False)
    except EmailNotValidError as exc:
        return "invalid", f"Bad syntax: {exc}"
    domain = parsed.domain
    local = parsed.local_part
    if domain in DISPOSABLE_DOMAINS:
        return "risky", "Disposable email domain"

    cache = _cache if _cache is not None else {}
    if domain not in cache:
        cache[domain] = _mx_lookup(domain)
    result = cache[domain]
    if result == "none":
        return "invalid", "Domain cannot receive email"
    if result == "error":
        return "unverified", "DNS lookup failed; try again later"
    if local in ROLE_LOCALPARTS:
        return "risky", "Role-based address (shared inbox)"
    return "valid", "Domain accepts email (mailbox not confirmed)"
