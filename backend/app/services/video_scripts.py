"""Personalised video scripts for Loom (or any screen recorder).

Honest scope: Loom has no public API to create or upload videos, so this module prepares
everything around the recording (script, checklist, description, cover image) and validates
the share link the user pastes back. The person records with their OWN voice and screen.
"""
import html
import re
import textwrap

from app.models import Lead, Organization, ResearchReport
from app.services import llm
from app.services.email_writer import _context, _has_facts, _sentence, first_name, sender_name

LOOM_RE = re.compile(r"^https?://(?:www\.)?loom\.com/(?:share|embed)/([a-f0-9]{32})(?:[/?#].*)?$", re.I)
WPM = 150  # comfortable speaking pace


def normalize_loom_url(url: str) -> str | None:
    match = LOOM_RE.match((url or "").strip())
    return f"https://www.loom.com/share/{match.group(1).lower()}" if match else None


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", text))


def checklist(lead: Lead) -> list[dict]:
    site = lead.website or "their website"
    return [
        {"step": "Open Loom (desktop app or Chrome extension) and choose Screen + Camera.", "requires_user": True},
        {"step": f"Open {site} in a browser tab and have one or two pages ready to show.", "requires_user": True},
        {"step": "Read the intro and script in your own words; do not read word for word.", "requires_user": True},
        {"step": "Record for 60 to 90 seconds, then stop.", "requires_user": True},
        {"step": f"Title the video \"{lead.company_name}: a quick idea for you\".", "requires_user": True},
        {"step": "Copy the Loom share link and paste it into this app.", "requires_user": True},
        {"step": "Insert the link into the email draft (the app adds it for you).", "requires_user": False},
    ]


def _template(lead: Lead, report: ResearchReport | None, org: Organization) -> dict:
    n = first_name(lead) or "there"
    me, company = sender_name(org), lead.company_name
    observation = (
        f"I spent a few minutes on your website and here's what stood out: {_sentence(report.summary)}."
        if _has_facts(report) else f"I've been looking at {company} and the work you do{' in ' + lead.industry.lower() if lead.industry else ''}."
    )
    intro = f"Hi {n}, it's {me} from {org.name}. I made this short video just for {company}."
    script = (
        f"{intro}\n\n"
        f"{observation}\n\n"
        f"[SHOW YOUR SCREEN: open their homepage and point at the part you want to talk about.]\n\n"
        f"Why I'm reaching out: at {org.name} we work with companies like {company}, and I wanted to share one or two ideas "
        f"instead of sending a long email. [ADD YOUR IDEA: one specific, honest suggestion based on what you see on their site.]\n\n"
        f"I'm not going to pitch a big package in this video. I'd rather keep it short, show you something specific, "
        f"and let you decide whether it's worth a conversation.\n\n"
        f"The next step is simple: reply to my email with a time that suits you, or just tell me it isn't relevant "
        f"and I'll leave it there. If any of that is useful, we can find ten minutes to talk it through. "
        f"No pressure at all either way. Thanks for watching, {n}, and have a great day."
    )
    return {"intro": intro, "script": script}


def generate(lead: Lead, report: ResearchReport | None, org: Organization, tone: str = "friendly") -> dict:
    data = _template(lead, report, org)
    ai = llm.chat_json(
        f"You write 60-90 second video scripts (about 150-220 words, spoken aloud) in a {tone} tone for a salesperson "
        "recording a personal video for ONE prospect. Use ONLY the facts given; never invent compliments, results or clients. "
        "Where the speaker must show something on screen or add their own idea, write a bracketed cue in capitals like "
        "[SHOW YOUR SCREEN: ...] or [ADD YOUR IDEA: ...]. Reply with JSON only: {\"intro\":\"1-2 sentence greeting\",\"script\":\"full script including the intro\"}.",
        _context(lead, report, org), max_tokens=900,
    )
    if isinstance(ai, dict) and str(ai.get("script", "")).strip():
        data = {"intro": str(ai.get("intro", "")).strip() or data["intro"], "script": str(ai["script"]).strip()}
    spoken = re.sub(r"\[[^\]]*\]", "", data["script"])
    words = word_count(spoken)
    warnings = []
    if words < 120:
        warnings.append("Script is short for 60 to 90 seconds; add detail where you see [ADD YOUR IDEA].")
    if words > 240:
        warnings.append("Script may run past 90 seconds; trim it.")
    data.update(
        word_count=words, est_seconds=round(words / WPM * 60), warnings=warnings,
        checklist=checklist(lead),
        description=f"A quick personal video for {lead.company_name} from {sender_name(org)} at {org.name}.",
        thumbnail_text=f"A quick idea for {lead.company_name}",
    )
    return data


def thumbnail_svg(company: str, headline: str, sender: str) -> str:
    lines = textwrap.wrap(headline, 26)[:3] or [headline]
    tspans = "".join(f'<tspan x="80" dy="{0 if i == 0 else 84}">{html.escape(line)}</tspan>' for i, line in enumerate(lines))
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#4c1d95"/><stop offset="1" stop-color="#7c3aed"/></linearGradient></defs>'
        '<rect width="1280" height="720" fill="url(#g)"/><circle cx="1100" cy="140" r="220" fill="#ffffff" fill-opacity="0.07"/>'
        f'<text x="80" y="120" font-family="Arial,sans-serif" font-size="34" fill="#ddd6fe">For {html.escape(company)}</text>'
        f'<text x="80" y="330" font-family="Arial,sans-serif" font-size="76" font-weight="700" fill="#ffffff">{tspans}</text>'
        f'<text x="80" y="640" font-family="Arial,sans-serif" font-size="36" fill="#ede9fe">{html.escape(sender)}</text>'
        '<polygon points="1060,560 1060,640 1130,600" fill="#ffffff" fill-opacity="0.9"/></svg>'
    )
