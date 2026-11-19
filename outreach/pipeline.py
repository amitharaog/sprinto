"""Runs the 7 steps for each domain and records every decision.

A company that fails at any step gets its failure reason recorded and the run
moves on to the next one - a robust pipeline records the failure and
continues. Every company gets a JSON trace in outputs/<run>/ so each decision
(why it qualified, why this person, why this email) can be defended later.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import config
from .llm import LLMError, StructuredLLM
from .llm_handoff import NeedsAnswer
from .step1_scrape import Fetcher, normalize_domain, scrape_homepage
from .step3_qualify import qualify
from .step3b_value import company_enrichment, estimate_value
from .step4_poc import find_poc
from .step5_pain import identify_pain_points
from .step6_email import draft_email
from .step7_send import AuthFailed, build_message, send


@dataclass
class CompanyResult:
    domain: str
    outcome: str = "pending"         # emailed | drafted | disqualified | manual_review | no_poc | failed | awaiting_model
    summary: str = ""
    seconds: float = 0.0
    trace: dict[str, Any] = field(default_factory=dict)


def _jsonable(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    return obj


def review_notes(domain, q, poc, pains, draft, problems, value=None) -> str:
    c = poc.contact
    lines = [
        f"Intended recipient: {c.first_name} {c.last_name} <{c.email or 'email not found - verify in Hunter/Apollo'}>"
        f" - {c.position} (source: {c.source})",
        f"Company: {domain}  |  Status: {q.status}  |  ICP score: {q.score}",
        "", "WHY THIS COMPANY QUALIFIED", q.reason, *[f"  {r}" for r in q.score_breakdown],
        f"  Why now: {q.judgment.why_now_trigger}" if q.judgment else "",
        *([f"  FLAG: {f}" for f in q.flags]),
        *(["", "DEAL VALUE (ESTIMATE - assumptions in config.py)",
            f"  ACV ${value.acv_low:,}-${value.acv_high:,}/yr · win probability {value.win_probability:.0%} · "
            f"expected value ${value.expected_value:,} · 3-year value ${value.three_year_value:,}",
            *[f"  {line}" for line in value.explanation]] if value else []),
        "", "WHY THIS PERSON", poc.why,
        "", "PAIN POINTS", *[f"  {i + 1}. {p.pain}\n     evidence: {p.evidence}" for i, p in enumerate(pains.points)],
        "", "WHY THE EMAIL IS WRITTEN THIS WAY", draft.why_written_this_way, f"  Hook fact: {draft.hook_fact}",
        *([f"  UNRESOLVED CHECK: {p}" for p in problems]),
        "", "PAGES READ", *[f"  [{p.kind}] {p.url} - {'ok' if p.ok else p.failure}" for p in q.pages],
    ]
    return "\n".join(l for l in lines if l is not None)


class Pipeline:
    def __init__(self, llm: StructuredLLM, out_dir: Optional[Path] = None, dry_run: bool = False,
                 use_cache: bool = True, log=print):
        self.llm = llm
        self.dry_run = dry_run
        self.use_cache = use_cache
        self.log = log
        self.fetcher = Fetcher()
        self.sending_disabled: Optional[str] = None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.out_dir = out_dir or (config.OUTPUT_DIR / f"run-{stamp}")
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def run(self, domains: list[str]) -> list[CompanyResult]:
        results = []
        for i, d in enumerate(domains, 1):
            self.log(f"\n[{i}/{len(domains)}] {d}")
            res = self.run_one(d)
            self.log(f"    -> {res.outcome.upper()}: {res.summary}")
            (self.out_dir / f"{res.domain}.json").write_text(json.dumps(_jsonable(res), indent=2, default=str))
            results.append(res)
        self.write_summary(results)
        return results

    def run_one(self, raw_domain: str) -> CompanyResult:
        t0 = time.time()
        domain = normalize_domain(raw_domain)
        res = CompanyResult(domain=domain)
        try:
            self._run_steps(domain, res)
        except NeedsAnswer as e:
            res.outcome, res.summary = "awaiting_model", str(e)
        except LLMError as e:
            res.outcome, res.summary = "failed", f"Claude call failed: {e}"
        except Exception as e:  # never let one company kill the batch
            res.outcome, res.summary = "failed", f"{type(e).__name__}: {e}"
        res.seconds = round(time.time() - t0, 1)
        return res

    def _run_steps(self, domain: str, res: CompanyResult) -> None:
        log = self.log
        # Step 1
        home = scrape_homepage(domain, self.fetcher, self.use_cache)
        res.trace["step1_homepage"] = {k: v for k, v in asdict(home).items() if k != "text"}
        if not home.ok:
            res.outcome, res.summary = "failed", f"Homepage not readable: {home.failure}"
            return
        log(f"    1 scraped homepage ({home.word_count} words{', cached' if home.from_cache else ''})")

        # Steps 2 + 3 (extraction runs inside the qualification loop)
        q = qualify(domain, home, self.llm, self.fetcher, self.use_cache)
        res.trace["step2_profile"] = q.profile
        res.trace["step3_qualification"] = {
            "status": q.status, "reason": q.reason, "score": q.score, "score_breakdown": q.score_breakdown,
            "questions": q.questions, "flags": q.flags, "judgment": q.judgment, "extra_fetches": q.extra_fetches,
            "loop_trace": q.loop_trace, "pages": [{"url": p.url, "kind": p.kind, "ok": p.ok, "failure": p.failure}
                                                  for p in q.pages]}
        log(f"    2-3 {q.status} (score {q.score}, {q.extra_fetches} extra pages): {q.reason[:110]}")
        if q.status in ("disqualified", "manual_review"):
            res.outcome, res.summary = q.status, q.reason
            return

        # Step 3b - what this prospect could be worth (estimate)
        enrichment, enrich_note = company_enrichment(domain, config.HUNTER_API_KEY)
        score = q.score
        value = estimate_value(domain, q.profile, q.judgment.fit if q.judgment else None, score, enrichment)
        res.trace["step3b_value"] = {"value": value, "enrichment_note": enrich_note}
        log(f"    3b value: ACV ${value.acv_low:,}-${value.acv_high:,}, win {value.win_probability:.0%}, "
            f"expected ${value.expected_value:,}")

        # Step 4
        poc = find_poc(domain, q.profile, value.headcount)
        res.trace["step4_poc"] = poc
        if not poc.contact:
            res.outcome, res.summary = "no_poc", poc.why
            return
        c = poc.contact
        log(f"    4 PoC: {c.first_name} {c.last_name}, {c.position} ({c.source})")

        # Step 5
        pains = identify_pain_points(q.profile, q.judgment, c, self.llm)
        res.trace["step5_pain_points"] = pains
        log(f"    5 pain points: {' | '.join(p.pain[:60] for p in pains.points)}")

        # Step 6
        draft, problems, attempts = draft_email(q.profile, q.judgment, c, pains, self.llm)
        res.trace["step6_email"] = {"draft": draft, "unresolved_checks": problems, "attempts": attempts}
        log(f"    6 drafted in {attempts} attempt(s): \"{draft.subject}\"" + (f" ({len(problems)} checks unresolved)" if problems else ""))

        # Step 7
        notes = review_notes(domain, q, poc, pains, draft, problems, value)
        msg = build_message(draft.subject, draft.body, notes)
        eml = self.out_dir / "emails" / f"{domain}.eml"
        if self.sending_disabled:
            sent = send(msg, eml, dry_run=True)
            sent.note = f"not sent: {self.sending_disabled}"
        else:
            try:
                sent = send(msg, eml, dry_run=self.dry_run)
            except AuthFailed as e:
                self.sending_disabled = str(e)
                sent = send(msg, eml, dry_run=True)
                sent.note = f"not sent: {e}"
        res.trace["step7_send"] = sent
        outbox = self.out_dir / "outbox"
        outbox.mkdir(exist_ok=True)
        (outbox / f"{domain}.json").write_text(json.dumps({
            "to": msg["To"], "subject": draft.subject, "body": msg.get_content(), "sent": sent.sent}, indent=1))
        log(f"    7 {sent.note} -> {sent.eml_path}")
        res.outcome = "emailed" if sent.sent else "drafted"
        res.summary = f"{c.first_name} {c.last_name} ({c.position}) - \"{draft.subject}\""

    def write_summary(self, results: list[CompanyResult]) -> Path:
        rows = ["| Domain | Outcome | Est. ACV | Expected value | Summary | Time |", "|---|---|---|---|---|---|"]
        ev = lambda r: getattr((r.trace.get("step3b_value") or {}).get("value"), "expected_value", -1)
        for r in sorted(results, key=ev, reverse=True):     # biggest expected opportunities first
            v = (r.trace.get("step3b_value") or {}).get("value")
            acv = f"${v.acv_low:,}-${v.acv_high:,}" if v else "-"
            exp = f"${v.expected_value:,}" if v else "-"
            rows.append(f"| {r.domain} | {r.outcome} | {acv} | {exp} | {r.summary.replace('|', '/')[:140]} | {r.seconds}s |")
        counts: dict[str, int] = {}
        for r in results:
            counts[r.outcome] = counts.get(r.outcome, 0) + 1
        text = (f"# Outreach run - {datetime.now():%Y-%m-%d %H:%M}\n\n"
                + ", ".join(f"**{k}**: {v}" for k, v in counts.items()) + "\n\n" + "\n".join(rows)
                + "\n\nFull decision trace per company: `<domain>.json`. Drafts: `emails/<domain>.eml`.\n")
        path = self.out_dir / "summary.md"
        path.write_text(text)
        return path
