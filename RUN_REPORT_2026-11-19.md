# Live run: 19 Nov 2026

Input: `prospects.txt`, 8 B2B companies picked from 2026 funding announcements (Series A/B).
Mode: `--llm handoff`. Claude Code answered the model requests, and the code made every decision. Contacts came from each company's public about page (Option B: manual lookup). Emails were sent through the Gmail connector to the student's own inbox.

## Outcomes

| Company | Outcome | Why (from the decision trace) | Pages read beyond homepage |
|---|---|---|---|
| uptiq.ai | **Emailed** | Score 5. Sells to 500+ banks and credit unions (+2), regulated industry (+2), holds SOC 2 Type 2 but not ISO 27001 (+1). Why now: just launched GovernAI, its bank-grade AI governance product | /ai-security |
| remotepass.com | **Emailed** | Score 6. Multinational customers like Valmont (+2), HR/payroll data (+2), sells in the EU/UK (+1), SOC 2 Type II only (+1) | none (all questions answered from the homepage) |
| zocks.io | **Emailed** | Score 5. Used by 7 of the 9 top mega RIAs (+2), financial services (+2), SOC 2 badge only (+1) | /platform/privacy-security |
| withampersand.com | Disqualified | Its trust centre (trust.ampersand.ai) is **hosted by Vanta**, so it already uses a competitor | trust.ampersand.ai |
| kashable.com | Disqualified | It's a consumer lender (NMLS-licensed), not a SaaS business | none |
| farseer.com | Disqualified | Score 4. Already ISO 27001, and no signs of an audit or SOC 2 demand | none |
| humanly.io | Disqualified | Score 4. HR data (+2) and no certification (+2), but no enterprise or stage signals; /security was a soft 404 | /careers, /pulses |
| procuros.io | Disqualified | Score 3. Selling in the EU is the only pressure signal, and they don't hire publicly | /careers, /de/careers |

## Contacts (chosen by role, using the size-band rules, then Hunter.io)

| Company | Role chosen | Address | Why |
|---|---|---|---|
| uptiq.ai | CTO | Hunter Email Finder, 95% | Mid band: tech exec ranks above COO/CEO. Hunter's domain search didn't list the CTO, so Email Finder looked up the name taken from the company's team page |
| remotepass.com | Director of Engineering | Hunter domain search, 79% | Hunter found an engineering leader, who outranks the CEO (the first manual pick) for a mid-size company |
| zocks.io | CEO & co-founder | Hunter domain search, 99% | The CTO & co-founder ranks higher, but Hunter has no address for them, so the best-ranked reachable person was chosen |

Hunter usage: 3 domain searches + 3 Email Finder lookups (at most 6 of the free plan's 25/month). All results are cached in `.cache/hunter/`.

## Estimated value of the qualified companies (step 3b)

Estimates from public benchmarks (assumptions in `config.py`), ranked by expected value:

| Company | Size (Hunter) | Raised | New frameworks | Est. contract value / yr | Win chance | Expected value | 3-year value |
|---|---|---|---|---|---|---|---|
| RemotePass | 131 | $24.9M | ISO 27001, GDPR | $18k–$33k | 6% | $1,530 | $69k |
| Uptiq | 193 | $70M | ISO 27001 | $14k–$24k | 8% | $1,520 | $51.5k |
| Zocks | 203 | $64.3M | ISO 27001 | $14k–$24k | 5% | $950 | $51.5k |
| **Total** | | | | **$46k–$81k (mid $63.5k)** | | **$4,000** | **$172k** |

Hunter usage for this step: 3 Company Enrichment lookups (cached).

## Fixes the live run forced (now in the code, with tests)
1. Link matching used substrings, so `/case-studies/dk-security` was treated as a security page. It now uses URL structure.
2. A soft 404 ("Page not found" served with HTTP 200) counted as a security page with no certifications. It now counts as a failed fetch.
3. "ISO/IEC 27001" wasn't recognised as ISO 27001. The label is now normalised.
4. New hard gate: a trust centre hosted by a compliance vendor means they already use a competitor, and the check needs no model call. On the re-run the Ampersand page had changed its title from "Vanta" to "Ampersand Trust Center", so the check now reads where the page loads its code from (assets.vanta.com), not just the title.
5. Hunter Email Finder fills in an address for a top-ranked person found by hand; if none is findable, the best-ranked reachable person is chosen and the review notes say so.

## Known limits of this run
- First pass had no Hunter key, so contacts came from team pages without addresses. Re-run with Hunter: all three now have addresses with Hunter confidence scores, and two contacts changed (see above).
- `procuros.io/careers` and `/de/careers` are the same page in two languages, so one of the stage question's two fetches was wasted.
