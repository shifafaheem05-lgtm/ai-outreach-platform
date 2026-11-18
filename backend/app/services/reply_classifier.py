"""Classify replies to cold emails. Rules always work; an AI model refines the label if configured."""
import re

from app.models import Lead, Organization
from app.services import llm
from app.services.email_writer import first_name, sender_name

LABELS = ["interested", "not_interested", "need_more_information", "meeting_requested", "follow_up_later", "out_of_office"]

OPT_OUT = re.compile(
    r"\b(unsubscribe|remove me|take me off|stop (emailing|contacting|sending)|do not (contact|email)|don'?t (contact|email))\b", re.I
)
PATTERNS = [
    ("out_of_office", re.compile(r"out of (the )?office|auto[- ]?reply|automatic reply|on (annual )?leave|on vacation|away from (my )?(email|desk)", re.I)),
    ("not_interested", re.compile(r"not interested|no thanks|no thank you|not a fit|not for us|we('| a)re all set|pass on this|already (have|work)", re.I)),
    ("meeting_requested", re.compile(r"schedule a (call|meeting)|book a (call|time)|set up a (call|meeting)|calendar|available (on|at|this|next)|let'?s (talk|chat|connect|meet|hop)|(call|meet) (on|at|this|next|tomorrow)|time slots?", re.I)),
    ("follow_up_later", re.compile(r"(reach|check|circle|get) back (to me |in |with me )?|next (quarter|month|year)|in (january|february|march|april|may|june|july|august|september|october|november|december)|not (right )?now|bad timing|few (weeks|months)|later this", re.I)),
    ("need_more_information", re.compile(r"pric(e|ing)|how much|cost|more (info|information|details)|case stud|examples?|who else|references?|tell me more|what exactly|how does (it|this) work", re.I)),
    ("interested", re.compile(r"interested|sounds (good|great|interesting)|love to|yes\b|please (send|share)|let me know more|curious", re.I)),
]


def classify_rules(subject: str, body: str, auto_submitted: bool = False) -> tuple[str, float]:
    if auto_submitted:
        return "out_of_office", 0.9
    text = f"{subject}\n{body}"
    if OPT_OUT.search(text):
        return "not_interested", 0.9
    for label, pattern in PATTERNS:
        if pattern.search(text):
            return label, 0.65
    return "need_more_information", 0.3  # unclear replies need a human look


def classify(subject: str, body: str, auto_submitted: bool = False) -> dict:
    label, confidence = classify_rules(subject, body, auto_submitted)
    method = "rules"
    if not auto_submitted and llm.is_configured():
        data = llm.chat_json(
            "Classify a reply to a cold sales email. Labels: " + ", ".join(LABELS) + ". "
            'Reply with JSON only: {"label":"<label>","confidence":0.0-1.0}.',
            f"Subject: {subject}\n\n{body[:1500]}",
            max_tokens=80,
        )
        if isinstance(data, dict) and data.get("label") in LABELS:
            try:
                label, confidence, method = data["label"], float(data.get("confidence", 0.7)), "ai"
            except (TypeError, ValueError):
                pass
    return {"label": label, "confidence": round(min(max(confidence, 0), 1), 2), "opt_out": bool(OPT_OUT.search(f"{subject}\n{body}")), "method": method}


def suggested_response(label: str, lead: Lead, org: Organization, opt_out: bool = False) -> str:
    n = first_name(lead)
    hi = f"Hi {n}," if n else "Hello,"
    sign = f"Best,\n{sender_name(org)}"
    if opt_out:
        return f"{hi}\n\nUnderstood. I've removed you from my list and you won't hear from me again. Apologies for the interruption.\n\n{sign}"
    return {
        "interested": f"{hi}\n\nThanks for getting back to me, glad it's relevant. Would a 15-minute call this week work? Send me a couple of times that suit you and I'll confirm.\n\n{sign}",
        "meeting_requested": f"{hi}\n\nGreat, thank you. I'm flexible, so please send a couple of slots that work for you and I'll confirm right away.\n\n{sign}",
        "need_more_information": f"{hi}\n\nThanks for the questions. [ADD DETAILS: answer their specific questions here]\n\nHappy to go through it on a short call if that's easier.\n\n{sign}",
        "follow_up_later": f"{hi}\n\nThanks for letting me know. I'll check back in [ADD WHEN] unless you'd like me to reach out sooner.\n\n{sign}",
        "not_interested": f"{hi}\n\nUnderstood, thanks for letting me know. I won't follow up again. Best of luck with everything at {lead.company_name}.\n\n{sign}",
        "out_of_office": "",
    }.get(label, "")
