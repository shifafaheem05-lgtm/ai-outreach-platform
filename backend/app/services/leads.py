"""Lead helpers: normalisation, dedupe keys, region flag and CSV import."""
import csv
import io
import re
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Lead

MAX_CSV_BYTES = 2_000_000
MAX_CSV_ROWS = 5000

FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "proton.me", "aol.com"}
EU_UK_TLDS = {
    "uk", "eu", "de", "fr", "it", "es", "nl", "ie", "be", "se", "dk", "fi", "pl", "pt", "at",
    "gr", "cz", "ro", "hu", "bg", "hr", "sk", "si", "lt", "lv", "ee", "lu", "mt", "cy",
}
EU_UK_WORDS = (
    "united kingdom", "england", "scotland", "wales", "germany", "france", "italy", "spain",
    "netherlands", "ireland", "belgium", "sweden", "denmark", "finland", "poland", "portugal",
    "austria", "greece", "europe",
)

HEADER_ALIASES = {
    "company_name": {"company", "company_name", "company name", "organization", "organisation", "business", "business name"},
    "website": {"website", "url", "domain", "site", "web"},
    "industry": {"industry", "sector"},
    "location": {"location", "city", "country", "region", "address"},
    "company_size": {"company_size", "size", "employees", "company size", "headcount"},
    "niche": {"niche", "category", "segment"},
    "contact_name": {"contact_name", "name", "full_name", "full name", "contact", "contact name"},
    "first_name": {"first_name", "first name", "firstname"},
    "last_name": {"last_name", "last name", "lastname", "surname"},
    "contact_title": {"title", "contact_title", "job_title", "job title", "position", "role"},
    "email": {"email", "email_address", "e-mail", "email address", "work email"},
}


def normalize_domain(value: str) -> str:
    value = (value or "").strip().lower()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    host = urlparse(value).hostname or ""
    return host[4:] if host.startswith("www.") else host


def normalize_website(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    return value if "://" in value else "https://" + value


def make_dedupe_key(company: str, website: str, email: str) -> str:
    email = (email or "").strip().lower()
    if email:
        return email
    domain = normalize_domain(website)
    if domain:
        return domain
    return re.sub(r"[^a-z0-9]+", "-", (company or "").lower()).strip("-")


def region_flag(website: str, email: str, location: str) -> str:
    domain = normalize_domain(website) or (email.split("@")[-1] if "@" in email else "")
    tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
    loc = (location or "").lower()
    if tld in EU_UK_TLDS or any(w in loc for w in EU_UK_WORDS):
        return "EU/UK"
    return ""


def clean_lead_fields(data: dict) -> dict:
    from app.core.validation import strip_ctrl

    out = {k: (strip_ctrl(str(v)).strip() if v is not None else "") for k, v in data.items()}
    # Only touch keys that were supplied, so a partial update never wipes other fields.
    if "email" in out:
        out["email"] = out["email"].lower()
    if "website" in out:
        out["website"] = normalize_website(out["website"])
    return out


def _map_headers(fieldnames: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for raw in fieldnames:
        key = (raw or "").strip().lower()
        for canonical, aliases in HEADER_ALIASES.items():
            if key in aliases and canonical not in mapping.values():
                mapping[raw] = canonical
                break
    return mapping


def import_csv(db: Session, org_id: int, raw: bytes, source: str = "csv") -> dict:
    if len(raw) > MAX_CSV_BYTES:
        raise ValueError("CSV is larger than 2 MB")
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")
    mapping = _map_headers(reader.fieldnames)
    if "company_name" not in mapping.values() and "email" not in mapping.values():
        raise ValueError("CSV needs at least a 'company' or 'email' column")

    existing = set(db.scalars(select(Lead.dedupe_key).where(Lead.org_id == org_id)))
    created = duplicates = skipped = 0
    errors: list[dict] = []

    for line_no, row in enumerate(reader, start=2):
        if line_no - 1 > MAX_CSV_ROWS:
            errors.append({"row": line_no, "reason": f"Stopped after {MAX_CSV_ROWS} rows"})
            break
        data = {canonical: (row.get(raw_key) or "").strip() for raw_key, canonical in mapping.items()}
        if not data.get("contact_name"):
            data["contact_name"] = f"{data.get('first_name', '')} {data.get('last_name', '')}".strip()
        data.pop("first_name", None)
        data.pop("last_name", None)
        data = clean_lead_fields(data)
        for _k in ("company_name", "email", "website"):
            data.setdefault(_k, "")

        if not data.get("company_name") and not data.get("email"):
            skipped += 1
            errors.append({"row": line_no, "reason": "No company or email"})
            continue
        if not data.get("company_name"):
            data["company_name"] = normalize_domain(data["email"].split("@")[-1]) or data["email"]
        if data["email"] and "@" not in data["email"]:
            data["email"] = ""
            errors.append({"row": line_no, "reason": "Email ignored (no @)"})
        if data["website"]:
            from app.core.validation import check_website

            try:
                check_website(data["website"])
            except ValueError:
                errors.append({"row": line_no, "reason": "Website ignored (not a valid address)"})
                data["website"] = ""

        key = make_dedupe_key(data["company_name"], data["website"], data["email"])
        if key in existing:
            duplicates += 1
            continue
        existing.add(key)
        db.add(
            Lead(
                org_id=org_id,
                source=source,
                dedupe_key=key,
                region_flag=region_flag(data["website"], data["email"], data.get("location", "")),
                **data,
            )
        )
        created += 1
    db.commit()
    return {"created": created, "duplicates": duplicates, "skipped": skipped, "errors": errors[:50]}
