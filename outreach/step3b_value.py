"""Step 3b - Estimate what a qualified prospect could be worth to Sprinto.

These are ESTIMATES built from an editable assumption table (config.py,
"deal value"), not forecasts. Every number shows how it was worked out, so the
Growth Lead can challenge any input.

  1. Company size: the website's headcount if stated, else Hunter.io's Company
     Enrichment (employees, funding raised). Cached per domain.
  2. Frameworks in scope: SOC 2 and ISO 27001 for every B2B SaaS prospect, plus
     GDPR if it sells in the EU/UK and HIPAA if it handles health data. Each is
     marked "held" (Sprinto would take over its upkeep) or "new" (the gap).
  3. Contract value (ACV) range: first-framework price for the size band, plus
     40-60% per extra framework.
  4. Win probability: by the model's fit judgment, +1 point per ICP point above
     the threshold. A starting guess to calibrate from real outcomes.
  5. Expected value = mid ACV x win probability. 3-year value assumes 90% retention.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

import requests

from . import config
from .step2_extract import CompanyProfile


@dataclass
class Framework:
    name: str
    status: str            # "held" | "new"
    why: str


@dataclass
class DealValue:
    headcount: Optional[int]
    headcount_source: str
    raised_usd: Optional[int]
    frameworks: list[Framework]
    acv_low: int
    acv_high: int
    acv_mid: int
    win_probability: float
    expected_value: int
    three_year_value: int
    explanation: list[str] = field(default_factory=list)


def company_enrichment(domain: str, api_key: str, session: requests.Session | None = None) -> tuple[dict, str]:
    """Hunter.io Company Enrichment (employees, funding). Cached per domain, so a re-run is free."""
    cache = config.CACHE_DIR / "hunter" / f"company-{domain}.json"
    if cache.exists():
        return (json.loads(cache.read_text()).get("data") or {}), "hunter company enrichment (cached)"
    if not api_key:
        return {}, "hunter company enrichment skipped: no HUNTER_API_KEY"
    try:
        r = (session or requests.Session()).get("https://api.hunter.io/v2/companies/find",
                                                params={"domain": domain, "api_key": api_key}, timeout=20)
    except requests.RequestException as e:
        return {}, f"hunter company enrichment network error: {type(e).__name__}"
    if r.status_code != 200:
        return {}, f"hunter company enrichment error {r.status_code}"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(r.text)
    return (r.json().get("data") or {}), "hunter company enrichment (live)"


def _has(certs: list[str], name: str) -> bool:
    from .step3_qualify import _has as has  # same normalisation as the qualifier ("ISO/IEC 27001" == "ISO 27001")
    return has(certs, name)


def frameworks_in_scope(p: CompanyProfile) -> list[Framework]:
    held = p.certifications_held + p.certifications_in_progress
    fws = [
        Framework("SOC 2", "held" if _has(held, "SOC 2") else "new", "US enterprise buyers ask for it"),
        Framework("ISO 27001", "held" if _has(held, "ISO 27001") else "new", "EU and global enterprise buyers ask for it"),
    ]
    if p.sells_in_eu_or_uk:
        fws.append(Framework("GDPR", "held" if _has(held, "GDPR") else "new", "sells in the EU/UK"))
    if p.regulated_industry and any(w in p.regulated_industry.lower() for w in ("health", "medical", "hipaa")):
        fws.append(Framework("HIPAA", "held" if _has(held, "HIPAA") else "new", f"serves {p.regulated_industry}"))
    return fws


def price_band(headcount: Optional[int]) -> tuple[int, int, str]:
    hc = headcount if headcount is not None else 100          # unknown size -> assume the 51-250 band
    prev = 0
    for max_emp, low, high in config.PRICE_FIRST_FRAMEWORK:
        if hc <= max_emp:
            label = f"{prev + 1}-{max_emp} employees" if max_emp < 10**9 else f"{prev + 1}+ employees"
            return low, high, label
        prev = max_emp
    raise AssertionError("unreachable")


def estimate_value(domain: str, profile: CompanyProfile, fit: Optional[str], score: int,
                   enrichment: Optional[dict] = None) -> DealValue:
    enrichment = enrichment or {}
    metrics = enrichment.get("metrics") or {}
    if profile.headcount_estimate:
        headcount, src = profile.headcount_estimate, "company website"
    elif metrics.get("employeesCount"):
        headcount, src = int(metrics["employeesCount"]), f"Hunter.io ({metrics.get('employees', '')} band)"
    else:
        headcount, src = None, "unknown - priced as 51-250 employees"
    raised = metrics.get("raised")

    fws = frameworks_in_scope(profile)
    n = len(fws)
    base_low, base_high, band = price_band(headcount)
    up_low, up_high = config.EXTRA_FRAMEWORK_UPLIFT
    acv_low = int(round(base_low * (1 + up_low * (n - 1)), -2))
    acv_high = int(round(base_high * (1 + up_high * (n - 1)), -2))
    acv_mid = int(round((acv_low + acv_high) / 2, -2))

    p = config.WIN_PROBABILITY.get(fit or "moderate", config.WIN_PROBABILITY["moderate"])
    p += config.WIN_PROBABILITY_PER_EXTRA_POINT * max(0, score - config.QUALIFY_SCORE_THRESHOLD)
    p = round(min(p, 0.5), 3)
    expected = round(acv_mid * p)
    r = config.ANNUAL_RETENTION
    three_year = int(round(acv_mid * (1 + r + r * r), -2))

    new = [f.name for f in fws if f.status == "new"]
    held = [f.name for f in fws if f.status == "held"]
    explanation = [
        f"Size: {headcount if headcount is not None else 'unknown'} employees ({src})"
        + (f", ${raised / 1e6:.1f}M raised" if raised else "") + f" -> {band} price band "
        f"${base_low:,}-${base_high:,}/yr for the first framework.",
        f"Frameworks in scope ({n}): " + ", ".join(f"{f.name} ({f.status})" for f in fws)
        + f". New for them: {', '.join(new) or 'none'}; already held: {', '.join(held) or 'none'}.",
        f"ACV: first framework + {int(up_low * 100)}-{int(up_high * 100)}% per extra framework x {n - 1} "
        f"= ${acv_low:,}-${acv_high:,}/yr (mid ${acv_mid:,}).",
        f"Win probability {p:.0%}: model fit '{fit or 'moderate'}' plus 1 point per ICP point above "
        f"{config.QUALIFY_SCORE_THRESHOLD} (score {score}).",
        f"Expected value ${expected:,} (mid ACV x win probability); 3-year value ${three_year:,} at "
        f"{int(r * 100)}% yearly retention.",
    ]
    return DealValue(headcount, src, raised, fws, int(acv_low), int(acv_high), int(acv_mid), p,
                     expected, int(three_year), explanation)
