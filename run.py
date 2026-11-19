"""Run the Sprinto cold-outreach pipeline on a list of domains.

    python run.py domains.txt              # research, draft, and send to MY_EMAIL
    python run.py domains.txt --dry-run    # everything except the send (.eml drafts only)
    python run.py posthog.com linear.app   # domains straight on the command line
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from outreach import config
from outreach.llm import LLM
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
    args = ap.parse_args()

    domains = read_domains(args.inputs)
    if not domains:
        print("No domains given.")
        return 1
    if not args.dry_run and not config.MY_EMAIL:
        print("MY_EMAIL is not set in .env - running as --dry-run (drafts only).")
        args.dry_run = True

    print(f"Running {len(domains)} domain(s) with {config.CLAUDE_MODEL}"
          f"{' [dry run]' if args.dry_run else f' -> sending to {config.MY_EMAIL}'}")
    pipe = Pipeline(LLM(), dry_run=args.dry_run, use_cache=not args.no_cache)
    pipe.run(domains)
    print(f"\nDone. Summary: {pipe.out_dir / 'summary.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
