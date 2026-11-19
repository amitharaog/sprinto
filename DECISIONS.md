# Decisions — and how to defend them

The case asks you to "defend every decision the system made: why this company qualified, why this person, why the email was written this way." This file explains each choice and links it to the code that applies it. Every run also writes these reasons to `outputs/run-*/<domain>.json` and adds them as **review notes** below each email.

---

## 1. The 9 checks: should this be built?

| Check | Answer | Why |
|---|---|---|
| 01 Problem real? | Yes | 15–20 minutes per company, 8–15 companies a week, and quality falls off by Friday |
| 02 Workflow repeated? | Yes | Same research steps every week for every new prospect |
| 03 Input available? | Yes | Company websites are public. Contacts come from Hunter.io (API) or Apollo (by hand) |
| 04 Output valuable? | Yes | A qualified lead with a drafted email is ready to act on |
| 05 Impact measurable? | Yes | Time per company, % of emails rewritten, reply rate |
| 06 ROI worth it? | Yes | About $0.10–0.30 of Claude usage per company, against 15+ minutes of a Growth Lead's time |
| 07 Failure risk OK? | Partial | Emails go only to your own inbox, so a mistake can't reach a prospect. Contact data can be out of date |
| 08 Judgment protected? | Partial | You set the ICP rules and the model applies them. A human reviews before any real send |
| 09 Owner clear? | Yes | The Growth Lead owns the output and decides what gets sent |

**Where the build stops by design:** no email reaches a real prospect without a human reading it first. `TO:` is hardcoded to `MY_EMAIL` (`outreach/step7_send.py`). The prospect's address appears only in the review notes.

## 2. The 5 pre-build decisions

1. **Outcome:** cut research time from 15–20 minutes to under 2 minutes per company, measured by time-to-draft and how much of each email gets rewritten.
2. **Baseline:** 8–15 companies a week, all researched and written by hand, with quality that varies.
3. **Workflow change:** the Growth Lead stops researching and writing, and starts reviewing and sending. They supply the domain list and approve each email before a real send.
4. **Measurement:** each company takes under 2 minutes (the run log records `seconds` per company), fewer than 20% of emails are rewritten, and conversion holds steady or improves.
5. **Kill criterion:** shut it down if more than 50% of emails are rewritten, if running it takes longer than doing the work by hand, or if fewer than 60% of PoCs are correct.

---

## 3. Who counts as a "right company" (the ICP)

Sprinto's brief says: *B2B SaaS, usually Series A–C, either preparing for an audit or under pressure from enterprise customers to get certified.* That turns into three layers.

### 3a. Hard gates: any one of these drops the company immediately (`short_circuit()` in `step3_qualify.py`)

| Gate | Why |
|---|---|
| Sells compliance automation itself (Vanta, Drata, Secureframe, …) | It's a competitor, not a customer |
| Not a software business | Sprinto is built for SaaS stacks (cloud, code, HR integrations) |
| Sells to consumers only | Without enterprise buyers, nobody is asking them for SOC 2 |
| Already holds **both** SOC 2 and ISO 27001 | The core problem is already solved. *Holding just one does **not** disqualify:* adding the second framework is a real expansion pitch, because Sprinto reuses the shared controls |
| Public or acquired | Outside the Series A–C ICP. Compliance is handled by an established team and bought through procurement |
| Trust centre hosted by Vanta, Drata, Secureframe, etc. | They already pay for a compliance platform, so this is a displacement deal, not a cold first touch. Detected in code from where the security page loads its scripts (e.g. assets.vanta.com), then its title or host. Added after the first live run, where trust.ampersand.ai turned out to be a Vanta trust centre |

### 3b. Points table (`score_profile()`): qualify at **5 or more**

| Signal | Points | Why it matters |
|---|---|---|
| Series A, B or C | +3 | The ICP's core |
| Seed | +1 | Can still be pushed into an audit by one big deal |
| Series D or later | −2 | Usually has its own compliance programme already |
| 20–500 employees | +2 | Big enough to need an audit, too small for a GRC team |
| 501–1,500 / over 1,500 employees | +1 / −2 | |
| Enterprise signals (enterprise plan, SSO, Fortune 500 logos, trust centre) | +2 | Enterprise buyers send security questionnaires and ask for SOC 2 |
| Hiring for security, GRC or compliance | +3 | The clearest sign they're "preparing for an audit" |
| Says it is working toward a certification | +3 | They're in the buying window right now |
| Serves a regulated industry (fintech, health, HR/payroll, …) | +2 | Compliance is expected from day one |
| Handles sensitive data (if not regulated) | +1 | |
| Sells in the EU or UK | +1 | GDPR exposure |
| No certification claimed | +2 | Greenfield |
| Holds one of SOC 2 / ISO 27001 | +1 | Expansion angle |
| 5 or more open roles | +1 | Growing, and headcount growth is a common audit trigger |

**Why use points instead of letting the model decide:** the same website always gets the same score, and every point shows its reason in the trace. The model still writes a fit judgment and the **why-now trigger** (`Judgment` in `step3_qualify.py`). If the model calls the fit "weak" but the score passes, the company is flagged for review rather than dropped silently.

### 3c. The evidence map: what the agent loop fetches, in what order, and when it stops

| Question | Fact that answers it | Where it usually is | Answered when (checked in code) | Fetch limit | If still unanswered | Ends the assessment? |
|---|---|---|---|---|---|---|
| B2B SaaS? | Product description naming a business buyer | Homepage → /product → /about | `is_software_product` and `sells_to_businesses` both filled | 1 | `manual_review` (no email) | NO → disqualify |
| Already certified? | A certification the company says it holds | Footer badges (scanned in raw HTML) → /security, /trust | A cert is named, **or** the security page was read and listed none | 1 | Treat as not certified, flag | Holds SOC 2 + ISO 27001 → disqualify |
| Right stage / pressure? | Funding stage, headcount, open roles, enterprise tier | /careers (checked first: one page often gives roles, headcount and funding) → /pricing → /customers | Any of those four is filled | 2 | Qualify with a lower score, flag | Public or acquired → disqualify |
| **Worst case** | | | | **4 fetches beyond the homepage** | | |

**Design rule from L4:** the model fills named fields, and the code checks whether they're filled. A model can sound confident about an empty page, but a field is either populated or it isn't. The fetch cap (`MAX_EXTRA_FETCHES = 4`) was set before the build. When the cap is hit, the "if unanswered" column decides what happens. The loop never just tries harder.

**"Two of three answered, one unknown: qualify, drop, or qualify-and-flag?"** It depends which one is unknown. If the B2B question is unknown, it goes to a human, because we can't even tell whether this is a SaaS company. If certification or stage is unknown, the company is **qualified and flagged**: the score still has to reach 5 on the signals we do have, and the flag shows up in the review notes.

---

## 3d. What a prospect could be worth (step 3b, `step3b_value.py`)

**These are estimates, not forecasts.** They exist to rank prospects so the Growth Lead works the biggest opportunities first. Every input sits in `config.py` ("deal value") to be replaced with Sprinto's own price book.

| Input | Where it comes from | Why |
|---|---|---|
| Company size | Website headcount, else Hunter.io Company Enrichment (employees, funding raised) | Price scales with size |
| Frameworks in scope | SOC 2 + ISO 27001 always; GDPR if it sells in the EU/UK; HIPAA if health data. Each marked *held* or *new* | What Sprinto would sell or take over |
| First-framework price | 1–50 people $6k–$10k, 51–250 $10k–$15k, 251–500 $15k–$25k, 501+ $25k–$45k a year | Vendr-based Sprinto median ~$15k/yr; Vanta/Drata market bands sit higher, and Sprinto is positioned below them |
| Extra frameworks | +40% (low case) to +60% (high case) each | Guides report ISO 27001 on top of SOC 2 adds 40–70% |
| Chance of winning | Fit strong 8%, moderate 5%, weak 2%, +1 point per ICP point above the threshold | A starting guess for "first cold email to closed deal"; calibrate from real outcomes |
| Expected value | Midpoint contract value × chance of winning | Comparable across prospects |
| 3-year value | Midpoint × (1 + 0.9 + 0.81) | 90% yearly retention |

Hunter's headcount also feeds the contact ranking's size band when the website doesn't state one.

## 4. Why this person (`step4_poc.py`)

Who owns the SOC 2 problem changes as a company grows:

| Size band (from headcount, or funding stage if headcount is unknown) | Role priority |
|---|---|
| **small** (50 or fewer, or seed / Series A) | Founder or CEO > CTO / VP Engineering > Head of Security > GRC/Compliance > COO |
| **mid** (51–500, or Series B/C) | Head of Security / CISO > GRC/Compliance > CTO / VP Engineering > COO > CEO |
| **large** (over 500) | GRC/Compliance > CISO / Security > CTO > COO > CEO |

- At a 40-person startup the CTO or a founder runs the audit personally. At 300 people a security lead usually exists and owns it. At 1,000 people there's a GRC function.
- Ranking: role points plus Hunter's confidence ÷ 10. Sales, marketing, HR/people, support, design and growth roles are **never** chosen.
- **Hunter Email Finder** fills in an address when the best-ranked person came from Apollo or a team page without one (one search per person, cached).
- **An email must be deliverable.** If the best-ranked person still has no address, the best-ranked person who has one is chosen, and the review notes name who was skipped and why.
- **If nobody fits, the system stops.** It doesn't email "the nearest person with manager in their title" (the L4 failure mode). The outcome is `no_poc`, and the fix is to add the right person to `contacts_manual.json` from Apollo.
- Hunter's free tier allows 25 searches a month, so every result is cached in `.cache/hunter/`. Re-running a domain uses no searches.

## 5. Why the email is written this way (`step5_pain.py`, `step6_email.py`)

- **Pain points are specific to the role and backed by evidence.** Each of the two pain points must quote a fact from the profile. For example, a CTO at 40 people feels SOC 2 as engineers pulled off the roadmap. A GRC lead feels it as spreadsheets and audit season.
- **The hook is a fact, not flattery.** The first line has to use one of the scraped evidence quotes, such as a role they're hiring for, an enterprise plan, a new market, or a certification in progress. The code checks that `hook_fact` really appears in the evidence list.
- **Sprinto claims come from a fixed list** (`SPRINTO_FACTS` in `config.py`), so the model can't make up customer counts or statistics.
- **Shape:** "Hi <first name>,", 60–140 words, one question (the ask), no exclamation marks, no stock openers, a subject line under 8 words. If a draft breaks a rule, it goes back to the model with the reasons, up to 3 attempts. Any check still failing after that is printed in the review notes.

---

## 6. Scraping choices (`step1_scrape.py`)

- **One page per request, no crawling.** That is the narrowest scope, the lowest cost and the lowest legal exposure.
- **robots.txt is checked before every page.** If it disallows a page, the scraper stops.
- **Bot protection (403/429/503, Cloudflare) gets recorded and skipped**, never worked around. Cloudflare on a site is a statement that the owner doesn't want automated traffic. For example, sprinto.com itself returns a 403 to scripts.
- **Cleaning:** removes nav, header, footer, scripts and cookie banners. Drops blocks under 8 words and duplicates. Caps each page at about 2,000 tokens. At $2 per million tokens, 15,000 raw tokens for 200 companies costs $6.00, while 500 cleaned tokens costs $0.20.
- **Certification badges sit in the footer or in image alt text, which cleaning removes.** So before cleaning, a regex scans the raw HTML for them and the model gets the results labelled as "could be marketing copy, not proof".
- **Headless browser only as a fallback.** If a homepage has under 200 words after cleaning and Playwright is installed, the page is rendered in a browser, which costs 10–50× more.
- **Soft 404s count as failures.** Some sites answer a missing `/security` with HTTP 200 and a "Page not found" title. That page must not count as "security page checked, no certification found".
- **Links are classified by URL structure**, not by any substring. `/case-studies/dk-security` is a customer story, not a security page.
- **Pages are cached for 7 days.** Re-running a company researched this week costs nothing.

## 7. What happens when a step fails (decided per tool before the build)

| Tool / step | Failure | Type | What happens |
|---|---|---|---|
| Homepage scrape | Blocked, robots.txt, timeout | Permanent for this run | Record the reason, move to the next company |
| Extra page fetch | 404 or blocked | Permanent | Counts against that question's fetch limit, then the "if unanswered" rule applies |
| Claude call | Refusal | | Server-side fallback model retries inside the same call (`fallbacks="default"`). If it still fails, the company is marked failed |
| Claude call | 429 / 5xx / connection error | Transient | The SDK retries automatically, then the company is marked failed and the run continues |
| Hunter.io | 429 / 5xx / timeout | Transient | Retry once, then use the manual Apollo file |
| Hunter.io | 401 / quota used up | Permanent | Use the manual Apollo file right away |
| Gmail send | Timeout or disconnect | Transient, nothing depends on it | Retry once, then skip. The `.eml` draft is still saved |
| Gmail send | Authentication failure | Permanent | Stop sending for the rest of the run, keep saving `.eml` drafts |

## 8. Why a hand-built loop and not LangGraph

L6 asks how much of the complexity sits in the loop and how much in the tools. Here it's mostly in the tools: scraping, cleaning and ranking. The loop is one ordered list of questions with a fetch cap, and it never has to remember anything between runs. That makes it a **pipeline with one adaptive step**, so plain Python is simpler to debug and to explain. LangGraph would become worth it for the next stage (reply → check calendar → propose times → counter-proposal → book), where state depends on other state and the flow loops back on itself.
