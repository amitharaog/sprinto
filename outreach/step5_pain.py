"""Step 5 - Identify the two most likely pain points for this person.

Pain is role-specific: a CTO at 40 people feels SOC 2 as engineers pulled off
the roadmap for evidence collection; a GRC lead at 400 feels it as
spreadsheets and audit season. So the model gets the company profile, the
why-now trigger AND the person's role, and every pain point must point at a
fact from the profile (checked in code).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from . import config
from .llm import StructuredLLM
from .step2_extract import CompanyProfile
from .step3_qualify import Judgment
from .step4_poc import Contact


class PainPoint(BaseModel):
    pain: str = Field(description="The problem, in the prospect's words, one sentence")
    why_this_person: str = Field(description="Why someone in this role feels it personally")
    evidence: str = Field(description="The specific fact from the profile that makes this likely (quote it)")
    sprinto_angle: str = Field(description="Which Sprinto fact addresses it")


class PainPoints(BaseModel):
    points: list[PainPoint] = Field(description="Exactly two, most likely first")


SYSTEM = f"""You are a B2B sales researcher for Sprinto. Given a prospect company's profile (from its own website), the reason it qualified, and the person we will email, name the TWO most likely compliance-related pain points this specific person has right now.

Rules:
- Ground each pain point in a concrete fact from the profile and quote that fact in `evidence`. No generic pains that would fit any company.
- Make them specific to the person's role and the company's stage.
- `sprinto_angle` may only use these facts about Sprinto:
{chr(10).join('  - ' + f for f in config.SPRINTO_FACTS)}
- Return exactly two."""


def identify_pain_points(profile: CompanyProfile, judgment: Judgment, contact: Contact,
                         llm: StructuredLLM) -> PainPoints:
    user = (f"Person: {contact.first_name} {contact.last_name}, {contact.position}\n"
            f"Why the company qualified (why now): {judgment.why_now_trigger}\n"
            f"Trigger evidence: {judgment.trigger_evidence}\n\n"
            f"Company profile JSON:\n{profile.model_dump_json(indent=1)}")
    result = llm.parse(system=SYSTEM, user=user, schema=PainPoints, effort="medium")
    result.points = result.points[:2]
    return result
