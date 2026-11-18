"""Polite website research.

- Honours robots.txt (4xx = allowed, unreachable/5xx = do not crawl, per RFC 9309).
- Identifiable User-Agent, >=1.5 s between requests to the same host, max 3 pages.
- Refuses private/loopback addresses (SSRF), including on every redirect hop.
- Never invents facts: the AI model only sees fetched text; without a model the report is
  extractive (title, description, headings) and says that analysis needs an AI model.
"""
import ipaddress
import logging
import re
import socket
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AuditLog, Lead, ResearchReport
from app.services import llm

log = logging.getLogger(__name__)

USER_AGENT = "AIOutreachProBot/0.1 (B2B research; honours robots.txt)"
MIN_DELAY_SECONDS = 1.5
MAX_BYTES = 1_000_000
MAX_PAGES = 3
_last_hit: dict[str, float] = {}


class FetchError(Exception):
    pass


@dataclass
class Page:
    url: str
    title: str = ""
    description: str = ""
    headings: list[str] = field(default_factory=list)
    text: str = ""


# DNS-rebinding between this check and the connection is not fully closed; acceptable for
# a research crawler that only reads public pages, but do not reuse this for internal APIs.
def assert_public_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise FetchError("No website")
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise FetchError("Only http/https websites are supported")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        infos = socket.getaddrinfo(parsed.hostname, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, ValueError) as exc:
        raise FetchError("Domain does not resolve") from exc
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise FetchError("Blocked: address is not public")
    return url


def _throttle(host: str) -> None:
    wait = MIN_DELAY_SECONDS - (time.monotonic() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.monotonic()


def _get(client: httpx.Client, url: str, html_only: bool = True) -> tuple[str, str]:
    for _ in range(4):
        url = assert_public_url(url)
        _throttle(urlparse(url).hostname or "")
        with client.stream("GET", url, follow_redirects=False) as resp:
            if resp.is_redirect:
                url = urljoin(url, resp.headers.get("location", ""))
                continue
            if resp.status_code >= 400:
                raise FetchError(f"HTTP {resp.status_code}")
            if html_only and "html" not in resp.headers.get("content-type", "").lower():
                raise FetchError("Not an HTML page")
            data = b""
            for chunk in resp.iter_bytes():
                data += chunk
                if len(data) > MAX_BYTES:
                    break
            return url, data.decode(resp.encoding or "utf-8", errors="ignore")
    raise FetchError("Too many redirects")


def _robots_allows(client: httpx.Client, url: str) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        _, body = _get(client, robots_url, html_only=False)
    except FetchError as exc:
        if re.match(r"HTTP 4\d\d", str(exc)):
            return True  # no robots.txt = no restrictions
        raise FetchError("robots.txt could not be read, so the site was not crawled") from exc
    rp = RobotFileParser()
    rp.parse(body.splitlines())
    return rp.can_fetch(USER_AGENT, url)


def parse_page(url: str, html: str) -> Page:
    soup = BeautifulSoup(html, "html.parser")
    desc_tag = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    page = Page(
        url=url,
        title=(soup.title.string or "").strip() if soup.title and soup.title.string else "",
        description=(desc_tag.get("content", "").strip() if desc_tag else ""),
    )
    page.headings = [
        h.get_text(" ", strip=True)
        for h in soup.find_all(["h1", "h2", "h3"])
        if 3 <= len(h.get_text(strip=True)) <= 120
    ][:15]
    for tag in soup(["script", "style", "nav", "footer", "noscript", "svg", "form"]):
        tag.decompose()
    page.text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:3000]
    return page


def _internal_links(base_url: str, html: str) -> list[str]:
    host = urlparse(base_url).hostname
    wanted = re.compile(r"about|service|solution|product|what-we-do|offer|platform|work", re.I)
    links: list[str] = []
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        target = urljoin(base_url, a["href"]).split("#")[0]
        p = urlparse(target)
        if p.hostname == host and p.scheme in ("http", "https") and wanted.search(p.path) and target not in links:
            links.append(target)
    return links


def fetch_pages(website: str) -> list[Page]:
    """Fetch the homepage plus up to two relevant internal pages. Raises FetchError."""
    url = assert_public_url(website)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
    with httpx.Client(headers=headers, timeout=httpx.Timeout(10.0)) as client:
        if not _robots_allows(client, url):
            raise FetchError("robots.txt does not allow crawling this site")
        final_url, html = _get(client, url)
        pages = [parse_page(final_url, html)]
        for link in _internal_links(final_url, html)[: MAX_PAGES - 1]:
            try:
                if not _robots_allows(client, link):
                    continue
                link_url, link_html = _get(client, link)
                pages.append(parse_page(link_url, link_html))
            except FetchError:
                continue
    return pages


NO_AI_NOTE = "Not generated: needs an AI model. Add a free API key (see .env.example) and re-run research."


def build_report(lead: Lead, pages: list[Page], error: str | None = None) -> dict:
    if not pages:
        return {
            "summary": f"Insufficient data: the website could not be analysed ({error or 'no pages fetched'}).",
            "products_services": "",
            "pain_points": "",
            "opportunities": "",
            "sources": [],
            "model": "none",
        }
    sources = [{"url": p.url, "title": p.title} for p in pages]
    home = pages[0]

    if llm.is_configured():
        material = "\n\n".join(
            f"PAGE {i + 1} ({p.url})\nTitle: {p.title}\nDescription: {p.description}\n"
            f"Headings: {'; '.join(p.headings)}\nText: {p.text[:2500]}"
            for i, p in enumerate(pages)
        )
        offering = settings.agency_services or "marketing, automation or software services"
        result = llm.chat_json(
            "You analyse company websites for a B2B agency. Use ONLY the page text provided. "
            "Never invent facts, numbers, clients or technologies. If the text does not support "
            "something, write 'Not enough information'. Phrase pain points and opportunities as "
            "possibilities and mention which page supports them. Reply with JSON only, keys: "
            "summary (2-3 sentences), products_services (short bullet text), pain_points (short "
            "bullet text), opportunities (short bullet text).",
            f"Company: {lead.company_name}\nIndustry: {lead.industry}\n"
            f"Our agency offers: {offering}\n\n{material}",
        )
        if result:
            return {
                "summary": str(result.get("summary", "")),
                "products_services": _as_text(result.get("products_services")),
                "pain_points": _as_text(result.get("pain_points")),
                "opportunities": _as_text(result.get("opportunities")),
                "sources": sources,
                "model": settings.openai_model,
            }

    headings = list(dict.fromkeys(h for p in pages for h in p.headings))[:12]
    summary = " ".join(x for x in (home.title, home.description) if x) or "No title or description found."
    return {
        "summary": summary,
        "products_services": "\n".join(f"- {h}" for h in headings) or "No headings found on the fetched pages.",
        "pain_points": NO_AI_NOTE,
        "opportunities": NO_AI_NOTE,
        "sources": sources,
        "model": "extractive",
    }


def _as_text(value) -> str:
    if isinstance(value, list):
        return "\n".join(f"- {v}" for v in value)
    return str(value or "")


def run_research(db: Session, lead: Lead, user_id: int | None = None) -> ResearchReport:
    error = None
    pages: list[Page] = []
    try:
        pages = fetch_pages(lead.website)
    except FetchError as exc:
        error = str(exc)
    except Exception as exc:  # noqa: BLE001 - network errors must not become 500s
        log.warning("Research fetch failed for lead %s: %s", lead.id, exc)
        error = "network error"
    data = build_report(lead, pages, error)
    report = ResearchReport(lead_id=lead.id, **data)
    db.add(report)
    db.add(
        AuditLog(
            org_id=lead.org_id, user_id=user_id, action="lead.research", entity="lead",
            entity_id=lead.id, meta={"pages": len(pages), "error": error, "model": data["model"]},
        )
    )
    db.commit()
    return report
