"""Step 4 - Find the right point of contact (PoC).

Sources (in order):
  A. Hunter.io Domain Search API (free tier: 25 searches/month - results are
     cached on disk so a re-run never spends a second search on a domain).
  B. contacts_manual.json - people looked up by hand in Apollo's web UI.

Who is "right" depends on company size - the person who owns the SOC 2
problem changes as a company grows (reasoning in DECISIONS.md):

  small  (<=50 people, or seed/Series A):  CTO / founder-CEO own it
  mid    (51-500, or Series B/C):          Head of Security / GRC, then CTO
  large  (>500):                           GRC / compliance lead, then CISO

Ranking is code, not a model: role points + Hunter confidence. People in
sales, marketing, HR, support etc. are never picked, and if nobody matches a
role we stop and flag it instead of emailing "the nearest manager".
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Literal, Optional

import requests

from . import config
from .step2_extract import CompanyProfile

SizeBand = Literal["small", "mid", "large"]

ROLE_PATTERNS: dict[str, str] = {
    "security": r"\bciso\b|chief (information )?security|head of (information |product |cyber)?security|"
                r"(vp|vice president|director)[ ,of]*(information )?security|security (lead|director|manager|officer)",
    "compliance": r"\bgrc\b|compliance|governance|\brisk\b|\btrust\b|privacy officer|\bdpo\b|data protection",
    "tech_exec": r"\bcto\b|chief technology|chief information officer|\bcio\b|(vp|vice president|head|director)[ ,of]*(engineering|technology|infrastructure|platform|it)\b",
    "founder_ceo": r"\bceo\b|chief executive|co-?founder|\bfounder\b",
    "ops_exec": r"\bcoo\b|chief operating|head of operations",
}
EXCLUDE = re.compile(r"sales|marketing|recruit|talent|\bhr\b|people|support|success|design|account exec|"
                     r"\bsdr\b|\bbdr\b|intern|growth|brand|content|social|partnership", re.I)

ROLE_POINTS: dict[SizeBand, dict[str, int]] = {
    "small": {"founder_ceo": 100, "tech_exec": 95, "security": 90, "compliance": 85, "ops_exec": 70},
    "mid":   {"security": 100, "compliance": 95, "tech_exec": 90, "ops_exec": 70, "founder_ceo": 65},
    "large": {"compliance": 100, "security": 98, "tech_exec": 75, "ops_exec": 60, "founder_ceo": 40},
}


@dataclass
class Contact:
    first_name: str
    last_name: str
    email: str
    position: str
    source: str                      # hunter | apollo_manual
    confidence: Optional[int] = None
    linkedin: Optional[str] = None
    role_bucket: Optional[str] = None
    rank_score: float = 0.0


@dataclass
class PocResult:
    contact: Optional[Contact]
    size_band: SizeBand
    why: str
    candidates_considered: list[dict] = field(default_factory=list)
    source_notes: list[str] = field(default_factory=list)


def size_band(p: CompanyProfile) -> SizeBand:
    hc = p.headcount_estimate
    if hc is not None:
        return "small" if hc <= 50 else "mid" if hc <= 500 else "large"
    if p.funding_stage in ("pre_seed", "seed", "series_a", "bootstrapped"):
        return "small"
    if p.funding_stage in ("series_d_plus", "public"):
        return "large"
    return "mid"


def role_bucket(position: str) -> Optional[str]:
    pos = (position or "").lower()
    if not pos or EXCLUDE.search(pos):
        return None
    for bucket, pat in ROLE_PATTERNS.items():
        if re.search(pat, pos):
            return bucket
    return None


# ----------------------------------------------------------------- sources

def hunter_domain_search(domain: str, api_key: str, session: requests.Session | None = None) -> tuple[list[Contact], str]:
    """Returns (contacts, note). Cached forever per domain to protect the 25/month quota."""
    cache = config.CACHE_DIR / "hunter" / f"{domain}.json"
    if cache.exists():
        data = json.loads(cache.read_text())
        note = "hunter (cached - no search spent)"
    else:
        s = session or requests.Session()
        params = {"domain": domain, "api_key": api_key, "type": "personal", "limit": 10}
        data, note = None, "hunter: no response"
        for attempt in range(2):           # transient (429/5xx/timeout) -> retry once, then fall back
            try:
                r = s.get("https://api.hunter.io/v2/domain-search", params=params, timeout=20)
            except requests.RequestException as e:
                note = f"hunter network error: {type(e).__name__}"
                time.sleep(2)
                continue
            if r.status_code == 200:
                data = r.json()
                break
            if r.status_code in (429, 500, 502, 503) and attempt == 0:
                time.sleep(2)
                continue
            # 401 bad key / 402-403 quota or plan: permanent -> don't retry
            return [], f"hunter error {r.status_code}: {r.text[:150]}"
        if data is None:
            return [], note
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data))
        note = "hunter (live search)"

    contacts = []
    for e in (data.get("data") or {}).get("emails", []):
        if not e.get("value") or not e.get("first_name"):
            continue
        contacts.append(Contact(first_name=e["first_name"].strip(), last_name=(e.get("last_name") or "").strip(),
                                email=e["value"], position=e.get("position") or "", source="hunter",
                                confidence=e.get("confidence"), linkedin=e.get("linkedin")))
    return contacts, f"{note}: {len(contacts)} named people"


def manual_contacts(domain: str) -> list[Contact]:
    """contacts_manual.json (committed example) + contacts_research.json (git-ignored: real people's
    details from Apollo or public team pages stay off GitHub)."""
    data: dict = {}
    for f in (config.MANUAL_CONTACTS_FILE, config.MANUAL_CONTACTS_FILE.with_name("contacts_research.json")):
        if f.exists():
            for d, people in json.loads(f.read_text()).items():
                if not d.startswith("_"):
                    data.setdefault(d, []).extend(people)
    return [Contact(first_name=c["first_name"], last_name=c.get("last_name", ""), email=c.get("email", ""),
                    position=c.get("position", ""), source=c.get("source", "apollo_manual"),
                    linkedin=c.get("linkedin"))
            for c in data.get(domain, []) if c.get("first_name")]


# ----------------------------------------------------------------- ranking

def rank(contacts: list[Contact], band: SizeBand) -> list[Contact]:
    ranked = []
    for c in contacts:
        bucket = role_bucket(c.position)
        if bucket is None:
            continue
        c.role_bucket = bucket
        c.rank_score = ROLE_POINTS[band][bucket] + (c.confidence or 50) / 10
        ranked.append(c)
    return sorted(ranked, key=lambda c: c.rank_score, reverse=True)


def find_poc(domain: str, profile: CompanyProfile) -> PocResult:
    band = size_band(profile)
    notes: list[str] = []
    pool: list[Contact] = []

    if config.HUNTER_API_KEY:
        found, note = hunter_domain_search(domain, config.HUNTER_API_KEY)
        notes.append(note)
        pool += found
    else:
        notes.append("hunter skipped: no HUNTER_API_KEY")
    manual = manual_contacts(domain)
    notes.append(f"manual (Apollo) file: {len(manual)} people")
    pool += manual

    ranked = rank(pool, band)
    considered = [{"name": f"{c.first_name} {c.last_name}".strip(), "position": c.position, "source": c.source,
                   "bucket": role_bucket(c.position) or "excluded / no matching role",
                   "score": round(c.rank_score, 1)} for c in pool]
    if not ranked:
        return PocResult(None, band, "No one with a role that owns compliance (security, GRC, CTO, founder) was "
                         "found. Not emailing a random manager - add the right person to contacts_manual.json.",
                         considered, notes)
    best = ranked[0]
    order = " > ".join(sorted(ROLE_POINTS[band], key=ROLE_POINTS[band].get, reverse=True))
    why = (f"Company size band '{band}' (headcount {profile.headcount_estimate or 'unknown'}, stage "
           f"{profile.funding_stage or 'unknown'}) -> role priority {order}. "
           f"{best.first_name} {best.last_name} ({best.position}) is the top '{best.role_bucket}' match"
           f"{f' with Hunter confidence {best.confidence}%' if best.confidence else ''}, source: {best.source}.")
    return PocResult(best, band, why, considered, notes)
