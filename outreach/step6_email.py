"""Step 6 - Draft a personalised cold email, addressed by name, with a specific hook.

The model writes; the code checks. A draft is rejected and rewritten (with the
reasons fed back, max MAX_ATTEMPTS) if it:
  * doesn't open with "Hi <first name>,"
  * is outside 60-140 words (cold emails that get replies are short)
  * contains placeholders like [Company] or {name}
  * uses stock openers ("I hope this email finds you well", "I came across...")
  * has a hook that isn't one of the evidence facts we actually scraped
  * asks for more than one thing
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from . import config
from .llm import StructuredLLM
from .step2_extract import CompanyProfile
from .step3_qualify import Judgment
from .step4_poc import Contact
from .step5_pain import PainPoints

MAX_ATTEMPTS = 3
MIN_WORDS, MAX_WORDS = 60, 140
BANNED = [
    "hope this email finds you", "hope you're doing well", "hope you are doing well", "i came across",
    "i stumbled upon", "just following up", "touch base", "synergy", "game-changer", "game changer",
    "revolutionize", "cutting-edge", "best-in-class", "i wanted to reach out", "quick question",
]


class EmailDraft(BaseModel):
    subject: str = Field(description="Under 8 words, specific to them, no clickbait, no emojis")
    body: str = Field(description="Plain text. Starts with 'Hi <first name>,'. Ends with the sender signature.")
    hook_fact: str = Field(description="The exact scraped fact the opening line is built on (copied from the evidence list)")
    pain_point_used: str = Field(description="Which of the two pain points the email leans on")
    why_written_this_way: str = Field(description="2-3 sentences a sales lead could use to defend the angle, hook and CTA")


SYSTEM = f"""You write first-touch cold emails for Sprinto's Growth Lead. They must read like a thoughtful human wrote them after ten minutes of research - because that is the job you're replacing.

Structure (plain text, {MIN_WORDS}-{MAX_WORDS} words in the body):
1. "Hi <first name>," on its own line.
2. Opening line = the hook: one specific, verifiable fact about THEIR company from the evidence list (a role they're hiring, an enterprise plan they launched, a market they entered, a certification they're working on). Show you noticed; don't flatter.
3. One or two sentences connecting that fact to the pain point - in their language, for their role.
4. One sentence on how Sprinto helps, using ONLY these facts (no invented numbers, customers or claims):
{chr(10).join('   - ' + f for f in config.SPRINTO_FACTS)}
5. One low-friction ask (e.g. "Worth a 15-minute call next week?"). Exactly one question mark in the email.
6. Signature: "{config.SENDER_NAME}" then "{config.SENDER_TITLE}" on separate lines.

Never use: placeholders in brackets, "I hope this email finds you well", "I came across your website", buzzwords, exclamation marks, or anything not supported by the evidence."""


def validate(draft: EmailDraft, first_name: str, allowed_facts: list[str]) -> list[str]:
    problems = []
    body = draft.body.strip()
    first_line = body.splitlines()[0].strip() if body else ""
    if not re.match(rf"^(hi|hello|hey)\s+{re.escape(first_name)}\s*,", first_line, re.I):
        problems.append(f"First line must be 'Hi {first_name},' (got: {first_line[:40]!r}).")
    n = len(body.split())
    if not MIN_WORDS <= n <= MAX_WORDS:
        problems.append(f"Body is {n} words; must be {MIN_WORDS}-{MAX_WORDS}.")
    if re.search(r"\[[^\]]*\]|\{[^}]*\}|<[^>]*>", body + draft.subject):
        problems.append("Contains a placeholder like [Company] or {name}.")
    low = body.lower()
    for b in BANNED:
        if b in low:
            problems.append(f"Uses banned phrase: '{b}'.")
    if "!" in body:
        problems.append("No exclamation marks.")
    if body.count("?") != 1:
        problems.append(f"Must contain exactly one question (the ask); found {body.count('?')}.")
    if len(draft.subject.split()) > 8:
        problems.append("Subject longer than 8 words.")
    hook = _norm(draft.hook_fact)
    if not hook or not any(hook in _norm(f) or _norm(f) in hook for f in allowed_facts):
        problems.append("hook_fact must be copied from the evidence list.")
    return problems


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def evidence_facts(profile: CompanyProfile, judgment: Judgment) -> list[str]:
    facts = [e.quote for e in profile.evidence]
    facts += [judgment.trigger_evidence] + profile.enterprise_signals + profile.security_or_compliance_roles
    facts += profile.recent_news + profile.certifications_in_progress + profile.open_role_titles
    if profile.last_funding_detail:
        facts.append(profile.last_funding_detail)
    return [f for f in dict.fromkeys(facts) if f and f.strip()]


def draft_email(profile: CompanyProfile, judgment: Judgment, contact: Contact, pains: PainPoints,
                llm: StructuredLLM) -> tuple[EmailDraft, list[str], int]:
    """Returns (draft, remaining_problems, attempts). Remaining problems are surfaced for review."""
    facts = evidence_facts(profile, judgment)
    base = (f"Recipient: {contact.first_name} {contact.last_name}, {contact.position} at "
            f"{profile.company_name or 'the company'}\n"
            f"What they do: {profile.one_line_description}\n"
            f"Why now: {judgment.why_now_trigger}\n\n"
            "Evidence list (the hook must be one of these, copied exactly):\n"
            + "\n".join(f"- {f}" for f in facts)
            + "\n\nPain points (most likely first):\n"
            + "\n".join(f"{i + 1}. {p.pain} (evidence: {p.evidence}; Sprinto angle: {p.sprinto_angle})"
                        for i, p in enumerate(pains.points)))
    user = base
    draft, problems = None, []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        draft = llm.parse(system=SYSTEM, user=user, schema=EmailDraft, effort="medium")
        problems = validate(draft, contact.first_name, facts)
        if not problems:
            return draft, [], attempt
        user = (base + "\n\nYour previous draft was rejected:\n" + "\n".join(f"- {p}" for p in problems)
                + f"\n\nPrevious draft:\nSubject: {draft.subject}\n{draft.body}\n\nRewrite it fixing every problem.")
    return draft, problems, MAX_ATTEMPTS
