"""Run the Sprinto cold-outreach pipeline on a list of domains.

    python run.py domains.txt              # research, draft, and send to MY_EMAIL
    python run.py domains.txt --dry-run    # everything except the send (.eml drafts only)
    python run.py posthog.com linear.app   # domains straight on the command line
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from outreach import config
from outreach.llm import LLM
from outreach.llm_handoff import HandoffLLM
from outreach.pipeline import Pipeline


def read_domains(args: list[str]) -> list[str]:
    domains: list[str] = []
    for a in args:
        p = Path(a)
        if p.suffix in (".txt", ".csv") and p.exists():
            for line in p.read_text().splitlines():
                line = line.split(",")[0].strip()
                if line and not line.startswith("#"):
                    domains.append(line)
        else:
            domains.append(a)
    return list(dict.fromkeys(domains))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="domains.txt and/or domains")
    ap.add_argument("--dry-run", action="store_true", help="draft and save .eml files, don't send")
    ap.add_argument("--no-cache", action="store_true", help="re-fetch pages even if cached this week")
    ap.add_argument("--llm", choices=["api", "handoff"], default=None,
                    help="api = Anthropic API (needs ANTHROPIC_API_KEY); handoff = an agent such as Claude Code "
                         "answers model requests via handoff/ files (default when no API key is set)")
    ap.add_argument("--out", help="output folder (reuse it across handoff rounds)")
    args = ap.parse_args()

    domains = read_domains(args.inputs)
    if not domains:
        print("No domains given.")
        return 1
    has_key = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
    mode = args.llm or ("api" if has_key else "handoff")
    if mode == "api" and not has_key:
        print("ANTHROPIC_API_KEY is not set. Add it to .env, or use --llm handoff (see README).")
        return 1
    if not args.dry_run and not config.MY_EMAIL:
        print("MY_EMAIL is not set in .env - running as --dry-run (drafts only).")
        args.dry_run = True

    print(f"Running {len(domains)} domain(s) with {config.CLAUDE_MODEL if mode == 'api' else 'handoff model'}"
          f"{' [dry run]' if args.dry_run else f' -> sending to {config.MY_EMAIL}'}")
    llm = LLM() if mode == "api" else HandoffLLM()
    pipe = Pipeline(llm, out_dir=Path(args.out) if args.out else None, dry_run=args.dry_run,
                    use_cache=not args.no_cache)
    results = pipe.run(domains)
    waiting = [r.domain for r in results if r.outcome == "awaiting_model"]
    if waiting:
        print(f"\n{len(waiting)} company(ies) waiting for model answers in handoff/pending/ - answer them and re-run.")
    print(f"\nSummary: {pipe.out_dir / 'summary.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
