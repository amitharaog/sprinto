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
from .step1_scrape import Fetcher, normalize_domain, scrape_homepage
from .step3_qualify import qualify
from .step4_poc import find_poc
from .step5_pain import identify_pain_points
from .step6_email import draft_email
from .step7_send import AuthFailed, build_message, send


@dataclass
class CompanyResult:
    domain: str
    outcome: str = "pending"         # emailed | drafted | disqualified | manual_review | no_poc | failed
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


def review_notes(domain, q, poc, pains, draft, problems) -> str:
    c = poc.contact
    lines = [
        f"Intended recipient: {c.first_name} {c.last_name} <{c.email}> - {c.position} (source: {c.source})",
        f"Company: {domain}  |  Status: {q.status}  |  ICP score: {q.score}",
        "", "WHY THIS COMPANY QUALIFIED", q.reason, *[f"  {r}" for r in q.score_breakdown],
        f"  Why now: {q.judgment.why_now_trigger}" if q.judgment else "",
        *([f"  FLAG: {f}" for f in q.flags]),
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

        # Step 4
        poc = find_poc(domain, q.profile)
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
        notes = review_notes(domain, q, poc, pains, draft, problems)
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
        log(f"    7 {sent.note} -> {sent.eml_path}")
        res.outcome = "emailed" if sent.sent else "drafted"
        res.summary = f"{c.first_name} {c.last_name} ({c.position}) - \"{draft.subject}\""

    def write_summary(self, results: list[CompanyResult]) -> Path:
        rows = ["| Domain | Outcome | Summary | Time |", "|---|---|---|---|"]
        for r in results:
            rows.append(f"| {r.domain} | {r.outcome} | {r.summary.replace('|', '/')[:160]} | {r.seconds}s |")
        counts: dict[str, int] = {}
        for r in results:
            counts[r.outcome] = counts.get(r.outcome, 0) + 1
        text = (f"# Outreach run - {datetime.now():%Y-%m-%d %H:%M}\n\n"
                + ", ".join(f"**{k}**: {v}" for k, v in counts.items()) + "\n\n" + "\n".join(rows)
                + "\n\nFull decision trace per company: `<domain>.json`. Drafts: `emails/<domain>.eml`.\n")
        path = self.out_dir / "summary.md"
        path.write_text(text)
        return path
