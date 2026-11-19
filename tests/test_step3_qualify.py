from outreach import step3_qualify as s3
from outreach.step1_scrape import Page
from outreach.step2_extract import CompanyProfile


def home(**links):
    return Page(url="https://acme.com", kind="homepage", ok=True, text="Acme sells a payroll API " * 30,
                word_count=150, links=links)


def patch_fetch(monkeypatch, served):
    log = []

    def fake_fetch(url, kind, domain, fetcher, use_cache=True):
        log.append(url)
        if url in served:
            return Page(url=url, kind=kind, ok=True, text=served[url], word_count=50)
        return Page(url=url, kind=kind, ok=False, failure="http_404")

    monkeypatch.setattr(s3, "fetch_page", fake_fetch)
    return log


def test_short_circuit_on_competitor(monkeypatch, fake_llm_cls):
    log = patch_fetch(monkeypatch, {})
    llm = fake_llm_cls(lambda u: CompanyProfile(is_software_product=True, sells_to_businesses=True,
                                                is_compliance_automation_vendor=True))
    q = s3.qualify("acme.com", home(), llm, fetcher=object())
    assert q.status == "disqualified" and "competitor" in q.reason
    assert log == []                                     # stopped before fetching anything


def test_short_circuit_when_both_core_certs_held(monkeypatch, fake_llm_cls):
    patch_fetch(monkeypatch, {})
    llm = fake_llm_cls(lambda u: CompanyProfile(is_software_product=True, sells_to_businesses=True,
                                                certifications_held=["SOC 2 Type II", "ISO/IEC 27001:2022"]))
    assert s3.qualify("acme.com", home(), llm, fetcher=object()).status == "disqualified"


def test_loop_fetches_security_then_careers_and_qualifies(monkeypatch, fake_llm_cls):
    log = patch_fetch(monkeypatch, {
        "https://acme.com/security": "SECURITYPAGE we take security seriously",
        "https://acme.com/careers": "CAREERSPAGE Series B, hiring a GRC Manager",
    })

    def profile(user):
        p = CompanyProfile(is_software_product=True, sells_to_businesses=True, regulated_industry="payroll/HR")
        if "CAREERSPAGE" in user:
            p.funding_stage = "series_b"
            p.security_or_compliance_roles = ["GRC Manager"]
            p.open_roles_count = 12
        return p

    llm = fake_llm_cls(profile)
    q = s3.qualify("acme.com", home(security=["https://acme.com/security"], careers=["https://acme.com/careers"]),
                   llm, fetcher=object())
    assert log == ["https://acme.com/security", "https://acme.com/careers"]   # evidence-map order
    assert q.status == "qualified", q.reason
    assert q.questions == {"b2b_saas": "answered", "certification": "answered", "stage": "answered"}
    assert q.score >= 5 and q.extra_fetches == 2
    assert any("GRC Manager" in r for r in q.score_breakdown)


def test_loop_respects_fetch_cap_and_flags_gaps(monkeypatch, fake_llm_cls):
    log = patch_fetch(monkeypatch, {})       # every extra page 404s
    llm = fake_llm_cls(lambda u: CompanyProfile(is_software_product=True, sells_to_businesses=True,
                                                regulated_industry="fintech", handles_sensitive_data=True,
                                                sells_in_eu_or_uk=True))
    q = s3.qualify("acme.com", home(), llm, fetcher=object())
    assert len(log) <= s3.config.MAX_EXTRA_FETCHES
    assert q.questions["certification"].startswith("unanswered")
    assert q.questions["stage"].startswith("unanswered")
    # 2 (regulated) + 1 (EU) + 2 (no cert) = 5 -> qualifies, but flagged
    assert q.status == "qualified_flagged" and len(q.flags) == 2


def test_unknown_b2b_goes_to_manual_review(monkeypatch, fake_llm_cls):
    patch_fetch(monkeypatch, {})
    q = s3.qualify("acme.com", home(), fake_llm_cls(lambda u: CompanyProfile()), fetcher=object())
    assert q.status == "manual_review"


def test_low_score_is_disqualified(monkeypatch, fake_llm_cls):
    patch_fetch(monkeypatch, {"https://acme.com/security": "x", "https://acme.com/careers": "x"})
    llm = fake_llm_cls(lambda u: CompanyProfile(is_software_product=True, sells_to_businesses=True,
                                                certifications_held=["SOC 2"], funding_stage="series_d_plus",
                                                headcount_estimate=3000))
    q = s3.qualify("acme.com", home(), llm, fetcher=object())
    assert q.status == "disqualified" and "below the threshold" in q.reason


def test_iso_iec_label_is_recognised():
    assert s3._has(["ISO/IEC 27001:2022"], "ISO 27001") and s3._has(["SOC 2 Type II"], "SOC 2")


def test_vanta_hosted_trust_centre_short_circuits(monkeypatch, fake_llm_cls):
    def fake_fetch(url, kind, domain, fetcher, use_cache=True):
        return Page(url="https://trust.acme.com/", kind=kind, ok=True, title="Vanta",
                    text="Trust Centers are the fastest way to demonstrate security", word_count=10)
    monkeypatch.setattr(s3, "fetch_page", fake_fetch)
    llm = fake_llm_cls(lambda u: CompanyProfile(is_software_product=True, sells_to_businesses=True))
    q = s3.qualify("acme.com", home(security=["https://trust.acme.com"]), llm, fetcher=object())
    assert q.status == "disqualified" and "Vanta" in q.reason
