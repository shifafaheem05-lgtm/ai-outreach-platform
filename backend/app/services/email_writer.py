"""Cold-email writer. Uses an AI model when configured, otherwise a deterministic template.

Both paths use ONLY facts stored on the lead / research report; nothing is invented. The
unsubscribe link and postal address are added automatically at send time, never here.
"""
import hashlib
import logging
import re

from app.core.config import settings
from app.models import Lead, Organization, ResearchReport
from app.services import llm

log = logging.getLogger(__name__)

TONES = ["professional", "friendly", "direct", "casual", "consultative"]
VARIANTS = ["short", "medium", "detailed"]
WORDS = {"short": "50-80", "medium": "90-130", "detailed": "150-200"}

GREETING = {"professional": "Hello {n},", "friendly": "Hi {n},", "direct": "{n},", "casual": "Hey {n},", "consultative": "Hi {n},"}
ASK = {
    "professional": "Would you be open to a brief call next week?",
    "friendly": "Happy to chat if that sounds useful.",
    "direct": "Worth a 15-minute call?",
    "casual": "Interested?",
    "consultative": "Would it help if I sent over a few observations first?",
}


def first_name(lead: Lead) -> str:
    name = (lead.contact_name or "").strip()
    return name.split()[0] if name else ""


def sender_name(org: Organization) -> str:
    return (org.sender_name or org.name or "").strip()


def _pick(seed: str, options: list):
    return options[int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(options)]


def _sentence(text: str, limit: int = 150) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    cut = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return cut[:limit].rstrip(" ,;:-") if cut else ""


def _has_facts(report: ResearchReport | None) -> bool:
    return bool(report and report.sources and report.summary and not report.summary.startswith("Insufficient"))


def _greeting(lead: Lead, tone: str) -> str:
    n = first_name(lead)
    return GREETING.get(tone, GREETING["professional"]).format(n=n) if n else "Hello,"


def _signoff(org: Organization) -> str:
    return f"Best,\n{sender_name(org)}"


def _offer(org: Organization) -> str:
    services = settings.agency_services.strip()
    return f"At {org.name}, we help with {services}." if services else f"I'm reaching out from {org.name}."


def _opener(lead: Lead, report: ResearchReport | None) -> str:
    if _has_facts(report):
        return f"I took a look at {lead.company_name}'s website: {_sentence(report.summary)}."
    if lead.industry:
        return f"I'm reaching out to {lead.industry.lower()} companies like {lead.company_name}."
    return f"I came across {lead.company_name} and wanted to introduce myself."


def template_initial(lead: Lead, report: ResearchReport | None, tone: str, org: Organization, variant: str) -> dict:
    greet, ask = _greeting(lead, tone), ASK.get(tone, ASK["professional"])
    subjects = {
        "short": f"Quick question, {lead.company_name}",
        "medium": f"An idea for {lead.company_name}",
        "detailed": f"{lead.company_name} and {org.name}",
    }
    parts = [greet, _opener(lead, report), _offer(org)]
    if variant in ("medium", "detailed"):
        parts.append(f"If useful, I can share a couple of specific ideas for {lead.company_name}.")
    if variant == "detailed":
        parts.append(
            "How it would work: a short call so I understand your goals, a written set of "
            "recommendations afterwards, and then it's entirely up to you whether to go further."
        )
    parts += [ask, _signoff(org)]
    return {"variant": variant, "subject": subjects[variant], "body": "\n\n".join(parts)}


def template_followup(lead: Lead, tone: str, org: Organization, step: int, initial_subject: str = "") -> dict:
    greet = _greeting(lead, tone)
    if step <= 1:
        text = f"I wanted to follow up on my earlier note about {lead.company_name}. {ASK.get(tone, ASK['professional'])}\n\nIf this isn't relevant, just say so and I won't follow up again."
    elif step == 2:
        text = "Last note from me on this. If it isn't a priority right now, no problem at all. If it is, I'm happy to share a few ideas; just reply here."
    else:
        text = "I'll close the loop here so I don't clutter your inbox. If things change, feel free to reach out any time."
    subject = f"Following up: {initial_subject}" if initial_subject else f"Following up, {lead.company_name}"
    return {"subject": subject, "body": f"{greet}\n\n{text}\n\n{_signoff(org)}"}


def _context(lead: Lead, report: ResearchReport | None, org: Organization) -> str:
    facts = f"Website summary: {report.summary}\nServices seen: {report.products_services}" if _has_facts(report) else "No website research available."
    offer = settings.agency_services.strip() or "(not specified)"
    return (
        f"Recipient: {lead.contact_name or 'unknown'} ({lead.contact_title or 'title unknown'}) at {lead.company_name}\n"
        f"Industry: {lead.industry or 'unknown'}; Location: {lead.location or 'unknown'}\n{facts}\n"
        f"Sender: {sender_name(org)} from {org.name}. What the sender offers: {offer}"
    )


RULES = (
    "Use ONLY the facts given. Never invent compliments, news, clients, results, numbers or prior contact. "
    "No filler like 'I hope this finds you well'. Sound like a person. One clear, low-pressure ask. "
    "Do not include an unsubscribe line or postal address (added automatically). "
    "Sign off with 'Best,' and the sender's name."
)


def _clean(item: dict) -> tuple[str, str] | None:
    subject, body = str(item.get("subject", "")).strip(), str(item.get("body", "")).strip()
    return (subject, body) if subject and body else None


def generate_initial(lead, report, tone, org, variants=None) -> list[dict]:
    variants = [v for v in (variants or VARIANTS) if v in VARIANTS]
    result = {v: template_initial(lead, report, tone, org, v) for v in variants}
    data = llm.chat_json(
        f"You write cold B2B emails in a {tone} tone. {RULES} Reply with JSON only: "
        '{"variants":[{"variant":"short|medium|detailed","subject":"...","body":"..."}]}. '
        f"Word counts: {', '.join(f'{v} {WORDS[v]}' for v in variants)}. Every subject must be unique.",
        _context(lead, report, org) + f"\nWrite these variants: {', '.join(variants)}",
        max_tokens=1600,
    )
    for item in (data or {}).get("variants", []) if isinstance(data, dict) else []:
        cleaned = _clean(item) if isinstance(item, dict) else None
        if cleaned and item.get("variant") in result:
            result[item["variant"]] = {"variant": item["variant"], "subject": cleaned[0], "body": cleaned[1], "ai": True}
    return [result[v] for v in variants]


def generate_followup(lead, report, tone, org, previous: list[dict], step: int) -> dict:
    initial_subject = previous[0]["subject"] if previous else ""
    fallback = template_followup(lead, tone, org, step, initial_subject)
    if not previous:
        return fallback
    history = "\n\n".join(f"EMAIL {i + 1}\nSubject: {p['subject']}\n{p['body'][:800]}" for i, p in enumerate(previous[-3:]))
    data = llm.chat_json(
        f"You write short, polite follow-up emails in a {tone} tone. {RULES} The recipient has NOT replied. "
        "Do not repeat the earlier email; add a new angle only from the given facts, or keep it brief. "
        'Reply with JSON only: {"subject":"...","body":"..."}. Under 90 words.',
        _context(lead, report, org) + f"\n\nEarlier emails sent (no reply yet):\n{history}\n\nThis is follow-up number {step}.",
    )
    cleaned = _clean(data) if isinstance(data, dict) else None
    return {"subject": cleaned[0], "body": cleaned[1], "ai": True} if cleaned else fallback


def generate_sequence(lead, report, tone, org, variant: str, followups: int) -> list[dict]:
    """Initial email + N follow-ups, as a list of {subject, body}."""
    initial = generate_initial(lead, report, tone, org, [variant])[0]
    emails = [{"subject": initial["subject"], "body": initial["body"]}]
    for step in range(1, followups + 1):
        emails.append(generate_followup(lead, report, tone, org, [{"subject": initial["subject"], "body": initial["body"]}], step))
    return emails
