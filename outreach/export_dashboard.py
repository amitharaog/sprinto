"""Turn a run's decision traces into CSVs for the outreach dashboard.

    python -m outreach.export_dashboard outputs/live-run [--sent uptiq.ai,zocks.io,...]

Writes <run>/dashboard/companies.csv, scores.csv and loop.csv, and dashboard/data.json
for the static dashboard deployed on Vercel. Contacts appear by
role only (names stay in the emails), so the files can be shared with a team.
--sent marks emails that were delivered some other way (e.g. a Gmail connector),
since the pipeline itself only knows about SMTP sends.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .config import QUALIFY_SCORE_THRESHOLD as QUALIFY_THRESHOLD

STAGES = ["Scraped", "Qualified", "Contact found", "Emailed"]


def _points(line: str) -> tuple[int, str]:
    m = re.match(r"\s*([+-]\d+)\s+(.*)", line)
    return (int(m.group(1)), m.group(2)) if m else (0, line)


def _tidy_title(t: str) -> str:
    """Hunter titles come title-cased ('Ceo And Founder'): restore acronyms and lowercase 'and'/'of'."""
    words = []
    for w in t.split():
        u = w.upper().strip(",&")
        if u in {"CEO", "CTO", "COO", "CFO", "CIO", "CISO", "VP", "SVP", "EVP", "GRC", "IT", "HR"}:
            w = w.upper()
        elif w.lower() in {"and", "of", "the", "for"} and words:
            w = w.lower()
        words.append(w)
    return " ".join(words)


def _source_label(src: str) -> str:
    """'hunter', 'web_research: <url> + hunter email finder' -> short, human labels."""
    parts = []
    if src.startswith("hunter"):
        parts.append("Hunter domain search")
    elif src.startswith("web_research"):
        parts.append("company team page")
    elif src:
        parts.append(src.split(":")[0].replace("_", " "))
    if "email finder" in src:
        parts.append("Hunter email finder")
    return " + ".join(parts)


def export(run_dir: Path, sent: set[str], site_dir: Path | None = None) -> Path:
    out = run_dir / "dashboard"
    out.mkdir(exist_ok=True)
    companies, scores, loop = [], [], []
    for f in sorted(run_dir.glob("*.json")):
        r = json.loads(f.read_text())
        t = r.get("trace", {})
        q = t.get("step3_qualification") or {}
        prof = t.get("step2_profile") or {}
        poc = (t.get("step4_poc") or {}).get("contact") or {}
        draft = (t.get("step6_email") or {}).get("draft") or {}
        outcome = "emailed" if r["domain"] in sent else r["outcome"]
        stage = ("Emailed" if outcome == "emailed" else
                 "Contact found" if poc else
                 "Qualified" if q.get("status", "").startswith("qualified") else
                 "Scraped" if t.get("step1_homepage", {}).get("ok") else "Not scraped")
        companies.append({
            "domain": r["domain"],
            "company": prof.get("company_name") or r["domain"],
            "outcome": outcome,
            "furthest_stage": stage,
            "icp_score": q.get("score", ""),
            "fit": (q.get("judgment") or {}).get("fit", ""),
            "reason": q.get("reason") or r.get("summary", ""),
            "why_now": (q.get("judgment") or {}).get("why_now_trigger", ""),
            "certifications": "; ".join(prof.get("certifications_held") or []),
            "extra_pages_read": q.get("extra_fetches", 0),
            "contact_role": _tidy_title(poc.get("position", "")),
            "contact_source": _source_label(poc.get("source") or ""),
            "contact_confidence": poc.get("confidence") or "",
            "email_subject": draft.get("subject", ""),
            "hook_fact": draft.get("hook_fact", ""),
            "draft_attempts": (t.get("step6_email") or {}).get("attempts", ""),
            "seconds": r.get("seconds", ""),
        })
        for line in q.get("score_breakdown", []):
            pts, why = _points(line)
            scores.append({"domain": r["domain"], "points": pts, "reason": why})
        for s in q.get("loop_trace", []):
            loop.append({"domain": r["domain"], "iteration": s["iteration"], "action": s["action"],
                         "url": s.get("url") or "", "result": s.get("result") or ""})

    if site_dir:
        site_dir.mkdir(parents=True, exist_ok=True)
        (site_dir / "data.json").write_text(json.dumps(
            {"run": run_dir.name, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "threshold": QUALIFY_THRESHOLD, "companies": companies, "scores": scores, "loop": loop},
            indent=1, ensure_ascii=False))
    for name, rows in (("companies", companies), ("scores", scores), ("loop", loop)):
        with open(out / f"{name}.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--sent", default="", help="comma-separated domains whose email was delivered")
    ap.add_argument("--site", default="dashboard", help="folder of the Vercel dashboard; data.json is written there")
    a = ap.parse_args()
    print(export(Path(a.run_dir), {d.strip() for d in a.sent.split(",") if d.strip()}, Path(a.site)))
