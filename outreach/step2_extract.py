"""Step 2 - Extract structured company data from the cleaned page text.

The model reads meaning, not position, so this survives redesigns that would
break CSS-selector rules. It fills *named fields*; a field it can't support
from the text stays null. Step 3's code then checks which fields are filled -
"a model might be confident about an empty page; a field is either populated
or it isn't."
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from .llm import StructuredLLM
from .step1_scrape import Page

FundingStage = Literal["pre_seed", "seed", "series_a", "series_b", "series_c",
                       "series_d_plus", "public", "bootstrapped", "acquired"]


class Evidence(BaseModel):
    field: str = Field(description="Which profile field this supports, e.g. 'funding_stage'")
    quote: str = Field(description="Short verbatim quote from the page text (under 30 words)")
    url: str = Field(description="URL of the page the quote came from")


class CompanyProfile(BaseModel):
    company_name: Optional[str] = None
    one_line_description: Optional[str] = Field(None, description="What they sell and to whom, in one sentence")

    # Q: B2B SaaS?
    is_software_product: Optional[bool] = Field(None, description="Sells software/SaaS/API (not services, hardware, agency work)")
    sells_to_businesses: Optional[bool] = Field(None, description="Buyers are businesses (B2B), not consumers")
    buyer_description: Optional[str] = Field(None, description="Who buys it, as stated, e.g. 'HR software platforms'")
    is_compliance_automation_vendor: Optional[bool] = Field(None, description="They themselves sell SOC 2/ISO compliance automation (a Sprinto competitor)")

    # Q: Already certified?
    certifications_held: list[str] = Field(default_factory=list, description="Frameworks the company says it HOLDS (e.g. 'SOC 2 Type II', 'ISO 27001'). Not ones it merely mentions or helps customers with.")
    certifications_in_progress: list[str] = Field(default_factory=list, description="Frameworks it says it is working towards / auditing for")

    # Q: Right stage?
    funding_stage: Optional[FundingStage] = None
    last_funding_detail: Optional[str] = Field(None, description="e.g. '$25M Series B led by X, 2025'")
    headcount_estimate: Optional[int] = Field(None, description="Only if stated or clearly countable (team page, careers page)")
    open_roles_count: Optional[int] = Field(None, description="Number of open job listings, only if a careers/jobs page lists them")
    open_role_titles: list[str] = Field(default_factory=list, description="Up to 15 open job titles if listed")

    # Compliance pressure signals (feed the score and the email hook)
    security_or_compliance_roles: list[str] = Field(default_factory=list, description="Open roles in security, GRC, compliance, IT, trust")
    enterprise_signals: list[str] = Field(default_factory=list, description="Enterprise plan/tier, SSO/SAML, SLA, 'Fortune 500' or named large enterprise customers, security questionnaire / trust centre mentions")
    notable_customers: list[str] = Field(default_factory=list)
    regulated_industry: Optional[str] = Field(None, description="If they sell into or handle data for fintech, healthcare, HR/payroll, insurance, legal, government, education: name it")
    handles_sensitive_data: Optional[bool] = Field(None, description="Processes customer PII, financial, health or HR data")
    sells_in_eu_or_uk: Optional[bool] = None
    recent_news: list[str] = Field(default_factory=list, description="Launches, funding, expansion, new markets mentioned on the pages")

    evidence: list[Evidence] = Field(default_factory=list, description="One quote per non-null field you filled")


SYSTEM = """You extract facts about a company from the text of its own web pages for a B2B sales research tool.

Rules:
- Use ONLY the text provided. Do not use outside knowledge about the company, even if you recognise it.
- If the text does not state or clearly imply a field, leave it null (or an empty list). Never guess. An empty field is a correct answer.
- certifications_held only counts frameworks the company says IT holds (e.g. "we are SOC 2 Type II certified", a trust page listing its own reports). A product that helps customers with GDPR does not mean the company holds anything.
- For every non-null field, add an evidence entry with a short verbatim quote and the page URL it came from.
- Keep lists short and specific; no marketing adjectives."""


def build_corpus(pages: list[Page]) -> str:
    parts = []
    for p in pages:
        if not p.ok:
            continue
        badges = f"\n[Keyword scan of raw HTML incl. footer badges - could be marketing copy, not proof of certification: {', '.join(p.cert_mentions)}]" if p.cert_mentions else ""
        parts.append(f"=== PAGE ({p.kind}) {p.url}\nTITLE: {p.title}{badges}\n{p.text}")
    return "\n\n".join(parts)


def extract_profile(domain: str, pages: list[Page], llm: StructuredLLM) -> CompanyProfile:
    user = (f"Company domain: {domain}\n\n"
            f"Extract the company profile from these pages:\n\n{build_corpus(pages)}")
    return llm.parse(system=SYSTEM, user=user, schema=CompanyProfile, effort="low")
