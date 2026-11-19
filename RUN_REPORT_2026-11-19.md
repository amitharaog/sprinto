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

## Contacts (chosen by role, using the size-band rules)

| Company | Role chosen | Others considered | Rule |
|---|---|---|---|
| uptiq.ai | CTO | COO, CEO, General Counsel (no matching role bucket) | Mid band: security > compliance > **tech exec** > ops > founder. No security lead is named on the site |
| zocks.io | CTO & co-founder | CEO & co-founder | Mid band: tech exec ranks above founder-CEO |
| remotepass.com | Co-founder & CEO | none | The only named leader. Flagged: the email address still needs verifying in Hunter or Apollo |

## Fixes the live run forced (now in the code, with tests)
1. Link matching used substrings, so `/case-studies/dk-security` was treated as a security page. It now uses URL structure.
2. A soft 404 ("Page not found" served with HTTP 200) counted as a security page with no certifications. It now counts as a failed fetch.
3. "ISO/IEC 27001" wasn't recognised as ISO 27001. The label is now normalised.
4. New hard gate: a trust centre hosted by a compliance vendor means they already use a competitor, and the check needs no model call.

## Known limits of this run
- Email addresses weren't verified (no Hunter key). The review notes under each email say so.
- `procuros.io/careers` and `/de/careers` are the same page in two languages, so one of the stage question's two fetches was wasted.
