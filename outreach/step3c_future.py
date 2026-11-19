"""Step 3c - Could a company that didn't qualify become a lead later?

A "no" today is often "not yet". This step sorts every non-qualified company into:

  near_miss       score is 1-2 points short and nothing rules it out. We name the
                  missing signals that would close the gap and the triggers to watch
                  (funding round, compliance hire, enterprise plan, EU launch).
  renewal_watch   already runs compliance on a competitor (e.g. a Vanta-hosted trust
                  centre). A lead when that contract comes up for renewal.
  expansion_watch already holds SOC 2 and ISO 27001. A lead if it needs a new
                  framework (HIPAA, GDPR programme, ISO 42001 for AI).
  manual_review   the website didn't say enough to decide.
  not_a_fit       competitor, not software, consumer-only, public or acquired. No follow-up.

Third-party company data (Hunter.io) is used here, never in the qualification
score itself: the qualifier scores only what the company says about itself. If
Hunter's data alone would close the gap, the company is flagged "re-check now"
for the Growth Lead rather than emailed automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from . import config
from .step2_extract import CompanyProfile

NEVER = ("competitor", "Not a software", "consumers", "public", "acquired")


@dataclass
class FutureLead:
    category: str                  # near_miss | renewal_watch | expansion_watch | manual_review | not_a_fit | lead_now
    label: str
    priority: str                  # high | medium | low | none
    recheck_in_months: Optional[int]
    recheck_date: Optional[str]
    gap: Optional[int]             # points short of the threshold
    would_qualify_if: list[str] = field(default_factory=list)
    watch_for: list[str] = field(default_factory=list)
    evidence_now: list[str] = field(default_factory=list)   # e.g. Hunter company data that closes the gap
    note: str = ""


def _add_months(start: date, months: int) -> str:
    return (start + timedelta(days=round(months * 30.44))).isoformat()


def missing_signals(p: CompanyProfile, kinds_fetched: set[str] | None = None) -> list[tuple[int, str, str]]:
    """Scoring-table signals the company hasn't shown yet: (points, signal, trigger to watch for)."""
    out: list[tuple[int, str, str]] = []
    if p.funding_stage is None:
        out.append((3, "a Series A-C round", "a funding announcement (Series A-C)"))
    if not p.security_or_compliance_roles:
        out.append((3, "a security/GRC/compliance hire", "a security, GRC or compliance job posting"))
    if not p.certifications_in_progress:
        out.append((3, "working towards SOC 2 / ISO 27001", "'SOC 2 in progress' or a new trust page"))
    if p.headcount_estimate is None:
        out.append((2, "20-500 employees", "headcount stated on their site"))
    if not p.enterprise_signals:
        out.append((2, "enterprise signals (enterprise plan, SSO, big-name customers)", "an enterprise plan or enterprise customer logos"))
    if not p.regulated_industry:
        out.append((2, "selling into a regulated industry", "a fintech, health or HR customer segment"))
    if not p.sells_in_eu_or_uk:
        out.append((1, "selling in the EU/UK", "an EU or UK launch"))
    return sorted(out, key=lambda x: -x[0])


def assess_future(p: CompanyProfile, status: str, reason: str, score: int,
                  enrichment: Optional[dict] = None, run_date: Optional[date] = None) -> FutureLead:
    run_date = run_date or date.today()
    t = config.QUALIFY_SCORE_THRESHOLD
    if status in ("qualified", "qualified_flagged"):
        return FutureLead("lead_now", "Lead now", "none", None, None, 0, note="Qualified in this run.")

    if status == "manual_review":
        return FutureLead("manual_review", "Needs a human look", "medium", 1, _add_months(run_date, 1), None,
                          watch_for=["a clearer product page saying who buys it"],
                          note="The website didn't say whether it sells B2B software.")

    if "Vanta" in reason or "Drata" in reason or "compliance platform" in reason or "runs compliance on" in reason:
        return FutureLead("renewal_watch", "Watch for renewal", "medium", 10, _add_months(run_date, 10), None,
                          watch_for=["their compliance-platform contract renewal (usually yearly)",
                                     "a new framework their current tool handles poorly",
                                     "complaints about audit effort or tool cost"],
                          note="Already pays for a competing platform: a displacement deal timed to renewal, not a cold first touch.")

    if "SOC 2 and ISO 27001" in reason:
        return FutureLead("expansion_watch", "Watch for a new framework", "low", 12, _add_months(run_date, 12), None,
                          watch_for=["HIPAA or health-data customers", "an AI product needing ISO 42001", "a GDPR/EU programme"],
                          note="Core certifications done; a lead only if a new framework appears.")

    if any(w in reason for w in NEVER):
        return FutureLead("not_a_fit", "Not a fit", "none", None, None, None, note=reason)

    # Score below threshold: how far short, and what would close the gap?
    gap = max(1, t - score)
    missing = missing_signals(p)
    closes = [f"{sig} (+{pts})" for pts, sig, _ in missing if pts >= gap]
    watch = [trig for pts, _, trig in missing if pts >= gap][:4]

    evidence: list[str] = []
    extra = 0
    m = (enrichment or {}).get("metrics") or {}
    if p.headcount_estimate is None and m.get("employeesCount"):
        n = int(m["employeesCount"])
        if 20 <= n <= 500:
            evidence.append(f"{n} employees (Hunter.io): +2 if confirmed")
            extra += 2
        else:
            evidence.append(f"{n} employees (Hunter.io): outside 20-500, no points")
    if p.funding_stage is None and m.get("raised"):
        evidence.append(f"${m['raised'] / 1e6:.1f}M raised (Hunter.io): +3 if it's a Series A-C round")

    if extra >= gap:
        return FutureLead("near_miss", "Re-check now", "high", 0, run_date.isoformat(), gap, closes, watch, evidence,
                          note="Company data closes the gap. Re-score with it before the next run.")
    months, prio = (3, "high") if gap == 1 else (6, "medium") if gap == 2 else (9, "low")
    return FutureLead("near_miss", "Near miss", prio, months, _add_months(run_date, months), gap, closes, watch, evidence,
                      note=f"{gap} point{'s' if gap > 1 else ''} short of the threshold of {t}.")
