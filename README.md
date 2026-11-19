# Sprinto cold outreach at scale (MESA Term 2, AI Case 2)

Give it a list of domains. For each one it **scrapes the website, extracts structured data, qualifies the company against Sprinto's ICP with an agent loop, finds the right decision-maker, works out their two most likely pain points, drafts a personalised email, and sends it to your own Gmail inbox.** You don't make any decisions along the way.

```
domains.txt ─► 1 Scrape ─► 2 Extract ─► 3 Qualify (agent loop) ─► 4 Find PoC ─► 5 Pain points ─► 6 Draft ─► 7 Send ─► your inbox
                               ▲             │  fields missing?
                               └── fetch /security, /careers, /pricing … (max 4) ◄┘
```

Every decision is written down: `outputs/run-*/<domain>.json` has the full trace, and each email arrives with **review notes** underneath (why this company, why this person, why this hook). To see the reasoning behind the rules, read **[DECISIONS.md](DECISIONS.md)**.

---

## Step-by-step setup (about 15 minutes)

### Step 1: Get the code and install
```bash
git clone <this repo> && cd sprinto
```
```bash
python3 -m venv .venv && source .venv/bin/activate
```
```bash
pip install -r requirements.txt
```
Optional: a headless browser for JavaScript-heavy homepages:
```bash
pip install playwright && playwright install chromium
```

### Step 2: Create your `.env`
```bash
cp .env.example .env
```
Fill it in:

| Variable | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys |
| `HUNTER_API_KEY` | hunter.io → sign up (free, 25 searches/month) → API. Leave it blank to use Option B |
| `GMAIL_ADDRESS` | The Gmail account that sends the email |
| `GMAIL_APP_PASSWORD` | Google Account → Security → turn on 2-Step Verification → **App passwords** → create one for "Mail". Your normal password **won't** work |
| `MY_EMAIL` | **Your own inbox.** This is the hardcoded `TO:` address, so the prospect is never emailed |
| `SENDER_NAME`, `SENDER_TITLE` | The signature on the drafted emails |

> School Google Workspace accounts sometimes block App Passwords. If yours does, use a personal Gmail as `GMAIL_ADDRESS` and keep `MY_EMAIL` as whichever inbox you want the email to land in.

### Step 3: Pick your PoC source (step 4 of the pipeline)
- **Option A, Hunter.io:** set `HUNTER_API_KEY`. Results are cached in `.cache/hunter/`, so each domain uses only one of your 25 monthly searches.
- **Option B, Apollo.io:** look up the right person in Apollo's web UI, then add them to `contacts_manual.json` under the domain:
  ```json
  "acme.com": [{"first_name": "Priya", "last_name": "Shah", "position": "Head of Security",
                "email": "priya@acme.com", "linkedin": "https://linkedin.com/in/...", "source": "apollo_manual"}]
  ```
  You can use both options. Hunter and manual contacts go into one pool and are ranked by the same rules.

### Step 4: Choose your domains
Put one domain per line in `domains.txt`. Good candidates are **B2B SaaS companies at Series A–C** that sell to enterprises or regulated industries, for example from recent funding announcements or the YC directory. Already-certified companies (both SOC 2 and ISO 27001) and compliance vendors are **dropped on purpose**. That's the qualifier working correctly, not a bug.

### Step 5: Do a dry run first
```bash
python run.py domains.txt --dry-run
```
This runs every step except the send and saves each draft to `outputs/run-*/emails/<domain>.eml`. Open `outputs/run-*/summary.md` to see what happened to each company.

### Step 6: Send for real (to your own inbox)
```bash
python run.py domains.txt
```
Check your inbox. Each qualified company produces one email addressed by first name to the PoC, with the review notes below a divider.

### Step 7: Run the tests (no API keys needed)
```bash
python -m pytest -q
```

---

## No Anthropic API key? Use handoff mode
```bash
python run.py domains.txt --llm handoff --dry-run --out outputs/my-run
```
Each model request (extract, judge, pain points, draft) is written to `handoff/pending/<key>.json` with its system prompt, input and JSON schema. An agent such as Claude Code answers it in `handoff/answers/<key>.json`, and you re-run the same command. Pages and contacts are cached, so each re-run picks up where the last one stopped. Answers are validated against the same schemas, and **every decision (what to fetch, scores, who to contact, the email checks) is still made by the code.** Each finished email is also written to `outputs/<run>/outbox/<domain>.json`, so it can be sent through a Gmail connector instead of SMTP. Mode is chosen automatically: `api` if `ANTHROPIC_API_KEY` is set, otherwise `handoff`.

Contacts found by hand (in Apollo or on public team pages) can go in `contacts_research.json`, which uses the same format as `contacts_manual.json` but is git-ignored, so real people's details stay off GitHub.

---

## Dashboard
After a run, export its decision traces for the outreach dashboard:
```bash
python -m outreach.export_dashboard outputs/<run> --sent uptiq.ai,zocks.io
```
This writes `companies.csv`, `scores.csv` and `loop.csv` to `outputs/<run>/dashboard/`, and `dashboard/data.json` for the web dashboard. Contacts appear by role only.

**Web dashboard (Vercel):** `dashboard/` is a static site (HTML, CSS, JS, no build step) that draws `data.json`. Its live address is https://sprinto-outreach-dashboard-nine.vercel.app, deployed from this repo with root directory `dashboard`. To update it after a run, re-export, commit `dashboard/data.json` and redeploy (Vercel dashboard → Redeploy, or `vercel --prod` from `dashboard/`). Preview it locally with `python -m http.server -d dashboard`.

---

## What each step does

| # | Step | File | Model or code? | Key choices |
|---|---|---|---|---|
| 1 | Scrape | `outreach/step1_scrape.py` | Code | Checks robots.txt. Records bot blocks and doesn't evade them. Strips nav, footer and cookie banners. Drops blocks under 8 words and duplicates. Caps each page at about 2k tokens. Scans raw HTML for cert badges. Finds /security, /careers, /pricing links. 7-day cache |
| 2 | Extract | `outreach/step2_extract.py` | Claude (structured output) | Named fields left null when unknown, plus a verbatim evidence quote for each filled field |
| 3 | Qualify | `outreach/step3_qualify.py` | Code decides, Claude judges | The evidence-map loop: code checks which questions are still open and fetches the next page (max 4). Short-circuits stop early. A points table decides. Claude writes the why-now trigger |
| 3b | Deal value | `outreach/step3b_value.py` | Code | Estimated contract value range, chance of winning and expected value per qualified company, from Hunter company data and an editable price table. Ranks the summary |
| 3c | Future leads | `outreach/step3c_future.py` | Code | For every company that didn't qualify: near miss, watch for renewal, re-check now or not a fit, with what's missing, what to watch for and a re-check date |
| 4 | Find PoC | `outreach/step4_poc.py` | Code | Hunter.io and/or the Apollo file. Role priority depends on company size. Never picks sales/HR/marketing. Stops instead of guessing |
| 5 | Pain points | `outreach/step5_pain.py` | Claude | Exactly 2, specific to the role, each quoting a scraped fact |
| 6 | Draft | `outreach/step6_email.py` | Claude writes, code checks | Name, 60–140 words, one ask, no placeholders or clichés, hook must come from the evidence. Rewrites up to 3 times |
| 7 | Send | `outreach/step7_send.py` | Code | Gmail SMTP. `TO:` is always `MY_EMAIL`. Saves an `.eml` every time. Retry and abort rules are set per failure type |

`outreach/pipeline.py` runs the steps in order for each domain. If one company fails, its reason is recorded and the run moves on.

### Possible outcomes for each company
`emailed` · `drafted` (dry run or no Gmail credentials) · `disqualified` (with the reason) · `manual_review` (couldn't tell whether it's B2B SaaS) · `no_poc` (nobody suitable found, so add someone from Apollo) · `failed` (for example `blocked (403, cloudflare)`)

## Cost and model
- Uses `claude-opus-5-5` by default. Change it with `CLAUDE_MODEL` in `.env`.
- Cleaning keeps each page to about 2k tokens. A company with the full 4 extra pages costs roughly **$0.10–0.30** in Claude usage, and cached pages and contacts cost nothing on a re-run.
- **Server-side refusal fallback is on** (`fallbacks="default"` in `outreach/llm.py`): if a safety classifier declines a request, the API retries on a fallback model within the same call. Delete those two lines if you don't want it.

## Repository map
```
run.py                  CLI entry point
outreach/config.py      every knob: limits, thresholds, competitor list, Sprinto facts the email may use
outreach/llm.py         Claude wrapper (structured outputs, refusal handling)
outreach/step1..7_*.py  one file per pipeline step
outreach/pipeline.py    orchestration, decision trace, summary.md
DECISIONS.md            ICP definition, evidence map, 9 checks, 5 pre-build decisions, failure table
tests/                  offline tests (fake model, fake websites, fake SMTP)
```
