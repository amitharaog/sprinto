"""Step 1 - Scrape a prospect's website for raw signal.

A single-fetch scraper (narrowest scope, lowest cost, lowest legal exposure):
  Request -> Parse -> Extract -> Clean -> Store

* robots.txt is checked before every page. Disallowed = we stop, not evade.
* Bot protection (403/429/503, Cloudflare challenge) is recorded as a failure
  reason and the pipeline moves on. We don't try to get around it.
* Cleaning drops nav/footer/scripts/cookie banners, blocks under 8 words and
  duplicates, and caps each page at ~2,000 tokens.
* Certification badges usually live in the footer or in image alt text, which
  cleaning removes - so we scan the *raw* page for them first, in code.
* Every response is cached on disk for CACHE_TTL_DAYS.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from . import config

# Page kinds the agent loop knows how to ask for, and how to recognise them.
PAGE_KIND_PATTERNS: dict[str, list[str]] = {
    "security": ["security", "trust", "compliance", "soc-2", "soc2", "iso", "gdpr", "privacy-and-security"],
    "careers": ["careers", "jobs", "join-us", "join", "work-with-us", "hiring", "open-positions",
                "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com"],
    "pricing": ["pricing", "plans", "enterprise"],
    "customers": ["customers", "case-studies", "case-study", "stories", "testimonials"],
    "about": ["about", "company", "team", "who-we-are"],
    "product": ["product", "platform", "features", "solutions", "how-it-works"],
}
# Common paths to try when the homepage doesn't link to a page of that kind.
DEFAULT_PATHS: dict[str, list[str]] = {
    "security": ["/security", "/trust"],
    "careers": ["/careers", "/jobs"],
    "pricing": ["/pricing"],
    "customers": ["/customers"],
    "about": ["/about"],
    "product": ["/product"],
}
# External hosts that legitimately hold a company's own pages (job boards, trust centres).
ALLOWED_EXTERNAL_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com",
                          "trust.", "security.", "safebase.io", "vanta.com/trust", "drata.com/trust")

CERT_PATTERNS = {
    "SOC 2": r"\bSOC[\s\-]?2\b|\bSOC[\s\-]?II\b",
    "ISO 27001": r"\bISO[\s/\-]?(?:IEC[\s\-]?)?27001\b",
    "GDPR": r"\bGDPR\b",
    "HIPAA": r"\bHIPAA\b",
    "PCI DSS": r"\bPCI[\s\-]?DSS\b",
    "ISO 27701": r"\bISO[\s/\-]?27701\b",
}
DROP_TAGS = ["script", "style", "noscript", "svg", "nav", "footer", "header", "form",
             "iframe", "button", "template", "dialog"]
NOISE_ATTR = re.compile(r"cookie|consent|gdpr-banner|newsletter|modal|popup|navbar|menu|breadcrumb", re.I)
BLOCKED_STATUSES = {401, 403, 429, 503}
SKIP_LINK = re.compile(r"sign-?in|log-?in|sign-?up|register|/blog/|/docs?/|\.pdf$|mailto:|^https?://app\.", re.I)


@dataclass
class Page:
    url: str
    kind: str                       # homepage | security | careers | ...
    ok: bool
    status: int | None = None
    failure: str | None = None      # why it failed, in plain words
    title: str = ""
    text: str = ""                  # cleaned, capped text for the model
    word_count: int = 0
    cert_mentions: list[str] = field(default_factory=list)   # found in RAW html (incl. footer, alt text)
    links: dict[str, list[str]] = field(default_factory=dict)  # kind -> candidate URLs
    fetched_with: str = "requests"
    from_cache: bool = False


# --------------------------------------------------------------------------- utils

def normalize_domain(domain: str) -> str:
    d = domain.strip().lower()
    d = re.sub(r"^https?://", "", d).split("/")[0]
    return d[4:] if d.startswith("www.") else d


def _cache_path(url: str) -> Path:
    return config.CACHE_DIR / "pages" / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".json")


def _load_cache(url: str) -> Page | None:
    p = _cache_path(url)
    if not p.exists() or (time.time() - p.stat().st_mtime) > config.CACHE_TTL_DAYS * 86400:
        return None
    data = json.loads(p.read_text())
    page = Page(**data)
    page.from_cache = True
    return page


def _save_cache(page: Page) -> None:
    p = _cache_path(page.url)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(page)))


class Fetcher:
    """Polite HTTP: robots.txt check, per-host delay, one session."""

    def __init__(self, session: requests.Session | None = None, delay_s: float = config.POLITE_DELAY_S):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": config.USER_AGENT,
                                     "Accept": "text/html,application/xhtml+xml",
                                     "Accept-Language": "en"})
        self.delay_s = delay_s
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last_hit: dict[str, float] = {}

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self._robots:
            rp = RobotFileParser()
            try:
                r = self.session.get(base + "/robots.txt", timeout=config.REQUEST_TIMEOUT_S)
                if r.status_code >= 400:
                    rp = None        # no robots.txt -> no stated restrictions
                else:
                    rp.parse(r.text.splitlines())
            except requests.RequestException:
                rp = None
            self._robots[base] = rp
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(config.USER_AGENT, url)

    def get(self, url: str) -> requests.Response:
        host = urlparse(url).netloc
        wait = self.delay_s - (time.time() - self._last_hit.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        self._last_hit[host] = time.time()
        return self.session.get(url, timeout=config.REQUEST_TIMEOUT_S, allow_redirects=True)


# ------------------------------------------------------------------ parse & clean

def find_cert_mentions(html: str) -> list[str]:
    """Scan the raw page, including footer badges and image alt/title text."""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    alt_text = " ".join(img.get("alt", "") + " " + img.get("title", "") for img in soup.find_all("img"))
    haystack = soup.get_text(" ") + " " + alt_text
    return [name for name, pat in CERT_PATTERNS.items() if re.search(pat, haystack, re.I)]


def clean_html(html: str) -> tuple[str, str]:
    """Return (title, cleaned text). Rules, not guesses: drop chrome, short blocks, duplicates."""
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.get_text(strip=True) if soup.title else "")[:200]
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    meta_desc = (meta.get("content") or "").strip() if meta else ""

    for tag in soup(DROP_TAGS):
        tag.decompose()
    for el in soup.find_all(True):
        if getattr(el, "decomposed", False) or el.attrs is None:
            continue
        attrs = " ".join([el.get("id") or "", " ".join(el.get("class") or []), el.get("role") or ""])
        if NOISE_ATTR.search(attrs) and el.name not in ("html", "body", "main"):
            el.decompose()

    blocks: list[str] = []
    seen: set[str] = set()
    if meta_desc:
        blocks.append(meta_desc)
        seen.add(meta_desc.lower())
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "blockquote", "dd", "figcaption"]):
        if el.find(["p", "li", "h1", "h2", "h3"]):   # skip containers; we take their children
            continue
        txt = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
        n_words = len(txt.split())
        is_heading = el.name in ("h1", "h2", "h3")
        if n_words < (3 if is_heading else 8):        # "drop anything under eight words" (headings: 3)
            continue
        key = txt.lower()
        if key in seen:
            continue
        seen.add(key)
        blocks.append(("## " + txt) if is_heading else txt)

    text = "\n".join(blocks)
    if len(text) > config.MAX_CLEAN_CHARS:
        text = text[: config.MAX_CLEAN_CHARS].rsplit("\n", 1)[0]
    return title, text


def discover_links(html: str, page_url: str, domain: str) -> dict[str, list[str]]:
    """Map each page kind the agent loop might want to candidate URLs found on this page."""
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, list[str]] = {k: [] for k in PAGE_KIND_PATTERNS}
    for a in soup.find_all("a", href=True):
        href = urljoin(page_url, a["href"]).split("#")[0].rstrip("/")
        parsed = urlparse(href)
        if parsed.scheme not in ("http", "https"):
            continue
        host = parsed.netloc.lower()
        own = host == domain or host.endswith("." + domain)
        if not own and not any(h in href.lower() for h in ALLOWED_EXTERNAL_HOSTS):
            continue
        if SKIP_LINK.search(href):
            continue
        haystack = (parsed.path + " " + host + " " + a.get_text(" ", strip=True)).lower()
        for kind, pats in PAGE_KIND_PATTERNS.items():
            if any(p in haystack for p in pats) and href not in found[kind] and href.rstrip("/") != page_url.rstrip("/"):
                found[kind].append(href)
    # Canonical paths first (/security), then shortest: /security beats /blog/our-security-journey-3
    def rank(kind: str, url: str) -> tuple[int, int]:
        canonical = urlparse(url).path.rstrip("/") in DEFAULT_PATHS.get(kind, [])
        return (0 if canonical else 1, len(url))
    return {k: sorted(v, key=lambda u, k=k: rank(k, u))[:5] for k, v in found.items() if v}


# --------------------------------------------------------------------------- fetch

def _fetch_with_browser(url: str) -> str | None:
    """Optional headless-browser fallback for JavaScript-rendered pages (10-50x the cost)."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(user_agent=config.USER_AGENT)
            page.goto(url, wait_until="networkidle", timeout=30000)
            html = page.content()
            browser.close()
            return html
    except Exception:
        return None


def fetch_page(url: str, kind: str, domain: str, fetcher: Fetcher, use_cache: bool = True) -> Page:
    if use_cache and (cached := _load_cache(url)):
        cached.kind = kind
        return cached

    if not fetcher.allowed(url):
        return Page(url=url, kind=kind, ok=False, failure="robots_disallowed: robots.txt forbids this path")
    try:
        r = fetcher.get(url)
    except requests.RequestException as e:
        return Page(url=url, kind=kind, ok=False, failure=f"network_error: {type(e).__name__}")

    if r.status_code in BLOCKED_STATUSES:
        cf = "cloudflare" if ("cf-ray" in r.headers or "cloudflare" in r.headers.get("server", "").lower()) else ""
        reason = f"blocked ({r.status_code}{', ' + cf if cf else ''}): bot protection or rate limit - not evading"
        return Page(url=url, kind=kind, ok=False, status=r.status_code, failure=reason)
    if r.status_code >= 400:
        return Page(url=url, kind=kind, ok=False, status=r.status_code, failure=f"http_{r.status_code}")
    if "html" not in r.headers.get("content-type", "html"):
        return Page(url=url, kind=kind, ok=False, status=r.status_code, failure="not_html")

    if "charset" not in r.headers.get("content-type", "").lower():
        r.encoding = "utf-8"          # requests defaults to latin-1 and garbles text otherwise
    html = r.text
    fetched_with = "requests"
    title, text = clean_html(html)
    if len(text.split()) < config.MIN_WORDS_BEFORE_BROWSER and kind == "homepage":
        if (rendered := _fetch_with_browser(url)):
            html, fetched_with = rendered, "headless_browser"
            title, text = clean_html(html)

    page = Page(
        url=r.url, kind=kind, ok=True, status=r.status_code, title=title, text=text,
        word_count=len(text.split()), cert_mentions=find_cert_mentions(html),
        links=discover_links(html, r.url, domain), fetched_with=fetched_with,
    )
    if page.word_count == 0:
        page.ok, page.failure = False, "empty_after_cleaning: likely JavaScript-rendered (install playwright to handle)"
    if page.ok:
        _save_cache(page)
    return page


def scrape_homepage(domain: str, fetcher: Fetcher | None = None, use_cache: bool = True) -> Page:
    domain = normalize_domain(domain)
    fetcher = fetcher or Fetcher()
    page = fetch_page(f"https://{domain}", "homepage", domain, fetcher, use_cache)
    if not page.ok and page.failure and page.failure.startswith("network_error"):
        page = fetch_page(f"https://www.{domain}", "homepage", domain, fetcher, use_cache)
    return page
