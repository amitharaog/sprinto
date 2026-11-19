"""Step 3 - Qualify the company against Sprinto's ICP, with an agent loop.

The loop implements the Evidence Map (DECISIONS.md):

  question        | where it lives                 | limit | if unanswered          | short-circuit
  ----------------|--------------------------------|-------|------------------------|-------------------------------
  B2B SaaS?       | homepage -> /product, /about   | 1     | manual_review          | NO -> disqualify, stop
  Certified?      | homepage footer -> /security   | 1     | assume not, flag       | holds SOC 2 AND ISO 27001 -> stop
  Right stage?    | /careers -> /pricing -> /customers | 2 | qualify lower, flag    | public / acquired -> stop
  (Competitor?)   | homepage                       | 0     | -                      | YES -> disqualify, stop

Worst case: 4 fetches beyond the homepage (MAX_EXTRA_FETCHES), fixed before the build.

Who decides what:
  * The MODEL extracts facts into named fields (step 2) and writes the judgment
    and the "why now" trigger (end of this step).
  * The CODE decides whether a question is answered (field filled or not), what
    to fetch next, when to stop, and the score/decision - so every outcome is
    repeatable and explainable line by line.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Literal, Optional

from pydantic import BaseModel, Field

from . import config
from .llm import StructuredLLM
from .step1_scrape import DEFAULT_PATHS, Fetcher, Page, fetch_page
from .step2_extract import CompanyProfile, extract_profile

Status = Literal["qualified", "qualified_flagged", "disqualified", "manual_review"]


# ----------------------------------------------------------------- evidence map

@dataclass
class Question:
    key: str
    label: str
    sources: list[str]          # page kinds to try, in order
    limit: int                  # max fetches this question is worth
    if_unanswered: str


def _cert_answered(p: CompanyProfile, kinds_fetched: set[str]) -> bool:
    # A named certification settles it. So does having read the security/trust page
    # and found none - absence on the page where it would live is an answer.
    return bool(p.certifications_held or p.certifications_in_progress) or "security" in kinds_fetched


QUESTIONS: list[tuple[Question, Callable[[CompanyProfile, set[str]], bool]]] = [
    (Question("b2b_saas", "Is it B2B SaaS?", ["product", "about"], 1, "manual_review"),
     lambda p, k: p.is_software_product is not None and p.sells_to_businesses is not None),
    (Question("certification", "Already certified?", ["security"], 1, "treat as not certified, flag"),
     _cert_answered),
    (Question("stage", "Right stage / compliance pressure?", ["careers", "pricing", "customers"], 2,
              "qualify at lower rank, flag"),
     lambda p, k: any([p.funding_stage, p.headcount_estimate, p.open_roles_count is not None,
                       p.enterprise_signals])),
]


def _norm_cert(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower()).replace("iec", "")   # "ISO/IEC 27001:2022" -> "iso270012022"


def _has(certs: list[str], name: str) -> bool:
    n = _norm_cert(name)
    return any(n in _norm_cert(c) for c in certs)


COMPLIANCE_PLATFORMS = ["Vanta", "Drata", "Secureframe", "Thoropass", "Scrut", "Scytale", "Sprinto", "Hyperproof"]


def detect_compliance_platform(pages: list[Page]) -> Optional[str]:
    """A trust centre hosted by a compliance-automation vendor means they already pay for one.
    Checked in code on the security page's title/host (e.g. trust.acme.com titled 'Vanta')."""
    for pg in pages:
        if pg.kind != "security" or not pg.ok:
            continue
        head = (pg.title + " " + pg.url + " " + pg.text[:300]).lower()
        for name in COMPLIANCE_PLATFORMS:
            if re.search(rf"\b{name.lower()}\b", head):
                return name
    return None


def short_circuit(domain: str, p: CompanyProfile, pages: Optional[list[Page]] = None) -> Optional[str]:
    """A single answer that ends the whole assessment. Returns the reason, or None."""
    if domain in config.COMPETITOR_DOMAINS or p.is_compliance_automation_vendor:
        return "Sells compliance automation itself - a competitor, not a customer."
    if pages and (platform := detect_compliance_platform(pages)) and platform != "Sprinto":
        return (f"Already runs compliance on {platform} (its trust centre is hosted by {platform}) - "
                "a displacement deal, not a cold first-touch prospect.")
    if p.is_software_product is False:
        return "Not a software/SaaS business."
    if p.sells_to_businesses is False:
        return "Sells to consumers, not businesses - no enterprise buyer asking for SOC 2."
    if _has(p.certifications_held, "SOC 2") and _has(p.certifications_held, "ISO 27001"):
        return "Already holds both SOC 2 and ISO 27001 - the core problem is solved."
    if p.funding_stage in ("public", "acquired"):
        return f"Company is {p.funding_stage}: outside the Series A-C ICP, compliance is owned by an established team."
    return None


# ----------------------------------------------------------------------- scoring

def score_profile(p: CompanyProfile, kinds_fetched: set[str]) -> tuple[int, list[str]]:
    """Transparent points table. Every point comes with its reason."""
    pts: list[tuple[int, str]] = []
    stage = p.funding_stage
    if stage in ("series_a", "series_b", "series_c"):
        pts.append((3, f"Funding stage {stage.replace('_', ' ').title()} is the ICP sweet spot"))
    elif stage == "seed":
        pts.append((1, "Seed stage: may be early for an audit, but enterprise deals can force it"))
    elif stage == "series_d_plus":
        pts.append((-2, "Series D+: likely already has an in-house compliance programme"))

    hc = p.headcount_estimate
    if hc is not None:
        if 20 <= hc <= 500:
            pts.append((2, f"Headcount ~{hc}: big enough to need an audit, small enough to lack a GRC team"))
        elif 500 < hc <= 1500:
            pts.append((1, f"Headcount ~{hc}: mid-size"))
        elif hc > 1500:
            pts.append((-2, f"Headcount ~{hc}: enterprise-sized, likely has a GRC team"))

    if p.enterprise_signals:
        pts.append((2, "Selling to enterprises (" + "; ".join(p.enterprise_signals[:3]) + ") - buyers demand SOC 2/ISO"))
    if p.security_or_compliance_roles:
        pts.append((3, "Hiring for security/compliance (" + ", ".join(p.security_or_compliance_roles[:3]) + ")"))
    if p.certifications_in_progress:
        pts.append((3, "Working towards " + ", ".join(p.certifications_in_progress) + " right now"))
    if p.regulated_industry:
        pts.append((2, f"Serves a regulated industry ({p.regulated_industry})"))
    elif p.handles_sensitive_data:
        pts.append((1, "Handles sensitive customer data"))
    if p.sells_in_eu_or_uk:
        pts.append((1, "Sells in the EU/UK - GDPR exposure"))

    held_soc2, held_iso = _has(p.certifications_held, "SOC 2"), _has(p.certifications_held, "ISO 27001")
    if not p.certifications_held:
        pts.append((2, "No certification claimed" + (" on its security page" if "security" in kinds_fetched else "")))
    elif held_soc2 != held_iso:
        have, missing = ("SOC 2", "ISO 27001") if held_soc2 else ("ISO 27001", "SOC 2")
        pts.append((1, f"Has {have} but not {missing} - expansion angle"))

    if p.open_roles_count is not None and p.open_roles_count >= 5:
        pts.append((1, f"{p.open_roles_count} open roles - growing"))

    return sum(x for x, _ in pts), [f"{x:+d}  {why}" for x, why in pts]


# ---------------------------------------------------------------- model judgment

class Judgment(BaseModel):
    fit: Literal["strong", "moderate", "weak"]
    why_now_trigger: str = Field(description="The single most concrete reason this company would care about compliance NOW, grounded in a fact from the profile")
    trigger_evidence: str = Field(description="The exact fact/quote from the profile that supports the trigger")
    rationale: str = Field(description="2-3 sentences: why they do or don't fit Sprinto's ICP")
    risks: list[str] = Field(default_factory=list, description="What could make this a bad lead (missing info, ambiguous signals)")


JUDGE_SYSTEM = f"""You are qualifying prospects for Sprinto, which automates SOC 2, ISO 27001, GDPR and HIPAA compliance for SaaS companies.

Sprinto's ICP: B2B SaaS companies, typically Series A-C, that are preparing for a compliance audit or are under pressure from enterprise customers to get certified.

You receive a structured profile extracted from the company's own website, plus a points-based score computed in code. Judge the fit, and name the single most concrete "why now" trigger, grounded only in facts in the profile. Do not invent facts. If evidence is thin, say so in risks."""


def judge(domain: str, p: CompanyProfile, score: int, reasons: list[str], llm: StructuredLLM) -> Judgment:
    user = (f"Domain: {domain}\n\nProfile JSON:\n{p.model_dump_json(indent=1)}\n\n"
            f"Code-computed ICP score: {score} (threshold {config.QUALIFY_SCORE_THRESHOLD})\n" + "\n".join(reasons))
    return llm.parse(system=JUDGE_SYSTEM, user=user, schema=Judgment, effort="medium")


# ---------------------------------------------------------------------- the loop

@dataclass
class LoopStep:
    iteration: int
    open_questions: list[str]
    action: str
    url: Optional[str] = None
    result: Optional[str] = None


@dataclass
class Qualification:
    status: Status
    reason: str
    score: int
    score_breakdown: list[str]
    questions: dict[str, str]                 # key -> answered / unanswered: <fallback>
    flags: list[str]
    loop_trace: list[LoopStep]
    pages: list[Page]
    profile: CompanyProfile
    judgment: Optional[Judgment] = None
    extra_fetches: int = 0


def _candidates(kind: str, domain: str, pages: list[Page]) -> list[str]:
    urls: list[str] = []
    for pg in pages:
        urls += pg.links.get(kind, [])
    urls += [f"https://{domain}{path}" for path in DEFAULT_PATHS.get(kind, [])]
    out, seen = [], set()
    for u in urls:
        key = u.rstrip("/").replace("://www.", "://")
        if key not in seen:
            seen.add(key)
            out.append(u)
    return out


def qualify(domain: str, homepage: Page, llm: StructuredLLM, fetcher: Fetcher | None = None,
            use_cache: bool = True) -> Qualification:
    fetcher = fetcher or Fetcher()
    pages: list[Page] = [homepage]
    tried: set[str] = {homepage.url.rstrip("/")}
    attempts = {q.key: 0 for q, _ in QUESTIONS}
    trace: list[LoopStep] = []
    profile = extract_profile(domain, pages, llm)
    extra = 0

    def kinds_ok() -> set[str]:
        return {pg.kind for pg in pages if pg.ok}

    stop_reason: Optional[str] = None
    for iteration in range(1, config.MAX_EXTRA_FETCHES + 2):
        if (stop_reason := short_circuit(domain, profile, pages)):
            trace.append(LoopStep(iteration, [], "short_circuit", result=stop_reason))
            break
        open_qs = [q for q, ok in QUESTIONS if not ok(profile, kinds_ok())]
        if not open_qs:
            trace.append(LoopStep(iteration, [], "stop", result="all questions answered"))
            break
        if extra >= config.MAX_EXTRA_FETCHES:
            trace.append(LoopStep(iteration, [q.key for q in open_qs], "stop", result="fetch cap reached - hand remaining gaps to the fallback rules"))
            break

        # Pick the first open question that still has budget and an untried source.
        choice = None
        for q in open_qs:
            if attempts[q.key] >= q.limit:
                continue
            for kind in q.sources:
                for url in _candidates(kind, domain, pages):
                    if url.rstrip("/").replace("://www.", "://") not in {t.replace("://www.", "://") for t in tried}:
                        choice = (q, kind, url)
                        break
                if choice:
                    break
            if choice:
                break
        if not choice:
            trace.append(LoopStep(iteration, [q.key for q in open_qs], "stop", result="no budget or sources left for open questions"))
            break

        q, kind, url = choice
        attempts[q.key] += 1
        extra += 1
        tried.add(url.rstrip("/"))
        page = fetch_page(url, kind, domain, fetcher, use_cache)
        if page.ok and detect_compliance_platform([page]):
            pages.append(page)                       # decided in code - no model call needed
            res = f"ok; trust centre hosted by {detect_compliance_platform([page])}"
        elif page.ok:
            pages.append(page)
            profile = extract_profile(domain, pages, llm)
            res = f"ok ({page.word_count} words); re-extracted profile"
        else:
            res = f"failed: {page.failure}"
        trace.append(LoopStep(iteration, [x.key for x in open_qs], f"fetch {kind} page for '{q.label}'", url, res))

    # ---- Decide (code) ------------------------------------------------------
    answered = {q.key: ok(profile, kinds_ok()) for q, ok in QUESTIONS}
    questions = {q.key: ("answered" if answered[q.key] else f"unanswered -> {q.if_unanswered}") for q, _ in QUESTIONS}
    score, breakdown = score_profile(profile, kinds_ok())
    flags = [f"'{q.label}' unanswered: {q.if_unanswered}" for q, _ in QUESTIONS
             if not answered[q.key] and q.key != "b2b_saas"]

    base = dict(score=score, score_breakdown=breakdown, questions=questions, loop_trace=trace,
                pages=pages, profile=profile, extra_fetches=extra)
    if stop_reason:
        return Qualification(status="disqualified", reason=stop_reason, flags=flags, **base)
    if not answered["b2b_saas"]:
        return Qualification(status="manual_review", flags=flags,
                             reason="Couldn't tell from the website whether this is B2B SaaS - a human should look.", **base)

    judgment = judge(domain, profile, score, breakdown, llm)
    if score < config.QUALIFY_SCORE_THRESHOLD:
        return Qualification(status="disqualified", judgment=judgment, flags=flags,
                             reason=f"ICP score {score} is below the threshold of {config.QUALIFY_SCORE_THRESHOLD}.", **base)
    if judgment.fit == "weak":
        flags.append("Model judged the fit 'weak' despite the score - review before sending.")
    status: Status = "qualified_flagged" if flags else "qualified"
    return Qualification(status=status, judgment=judgment, flags=flags,
                         reason=f"ICP score {score} >= {config.QUALIFY_SCORE_THRESHOLD}. {judgment.rationale}", **base)
