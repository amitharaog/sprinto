"""All tunable knobs in one place: env vars, limits, and the ICP definition.

Everything a reviewer might ask "why this number?" about lives here, so the
answer is one file away. The reasoning behind each choice is in DECISIONS.md.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / ".cache"
OUTPUT_DIR = ROOT / "outputs"
MANUAL_CONTACTS_FILE = ROOT / "contacts_manual.json"

# --- Claude -----------------------------------------------------------------
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")

# --- Step 1: scraping -------------------------------------------------------
USER_AGENT = (
    "Mozilla/5.0 (compatible; SprintoOutreachResearch/1.0; "
    "single-page research, respects robots.txt)"
)
REQUEST_TIMEOUT_S = 15
POLITE_DELAY_S = 1.0          # pause between two requests to the same host
CACHE_TTL_DAYS = 7            # a company researched this week costs nothing to re-run
MIN_WORDS_BEFORE_BROWSER = 200  # thinner than this -> try a headless browser (if installed)
MAX_CLEAN_CHARS = 8000        # ~2,000 tokens per page sent to the model

# --- Step 3: the agent loop ---------------------------------------------------
MAX_EXTRA_FETCHES = 4         # worst case: 4 pages beyond the homepage (set BEFORE the build)
QUALIFY_SCORE_THRESHOLD = 5   # see ICP scoring table in DECISIONS.md

# Compliance-automation vendors are competitors, not customers.
COMPETITOR_DOMAINS = {
    "sprinto.com", "vanta.com", "drata.com", "secureframe.com", "thoropass.com",
    "scrut.io", "scytale.ai", "sprinto.io", "hyperproof.io", "anecdotes.ai",
}

# --- Step 4: PoC ------------------------------------------------------------
HUNTER_API_KEY = os.getenv("HUNTER_API_KEY", "").strip()

# --- Step 7: Gmail ----------------------------------------------------------
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "").strip()
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
MY_EMAIL = os.getenv("MY_EMAIL", "").strip()   # hardcoded TO: - your own inbox
SENDER_NAME = os.getenv("SENDER_NAME", "The Sprinto team").strip()
SENDER_TITLE = os.getenv("SENDER_TITLE", "Growth, Sprinto").strip()

# What the email is allowed to claim about Sprinto. The model may only use these,
# so it can't invent customer counts or statistics. Edit to match current messaging.
SPRINTO_FACTS = [
    "Sprinto automates compliance for SaaS companies: SOC 2, ISO 27001, GDPR, HIPAA and more.",
    "It connects to the cloud, HR and code tools a company already uses and collects audit evidence automatically.",
    "It monitors controls continuously, so a company stays audit-ready instead of scrambling before each audit.",
    "One set of controls maps across frameworks, so adding ISO 27001 after SOC 2 reuses most of the work.",
    "It helps teams answer enterprise security questionnaires faster with a ready trust/compliance posture.",
]
