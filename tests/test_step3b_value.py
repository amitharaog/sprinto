import json

from outreach import step3b_value as v
from outreach.step2_extract import CompanyProfile


def test_frameworks_mark_held_and_new():
    p = CompanyProfile(certifications_held=["SOC 2 Type II"], sells_in_eu_or_uk=True, regulated_industry="healthcare")
    fws = {f.name: f.status for f in v.frameworks_in_scope(p)}
    assert fws == {"SOC 2": "held", "ISO 27001": "new", "GDPR": "new", "HIPAA": "new"}


def test_estimate_uses_hunter_headcount_and_explains_every_number():
    p = CompanyProfile(certifications_held=["SOC 2 Type II"])          # 2 frameworks in scope
    enrich = {"metrics": {"employees": "51-250", "employeesCount": 193, "raised": 70_000_000}}
    d = v.estimate_value("acme.com", p, "strong", 5, enrich)
    assert d.headcount == 193 and "Hunter" in d.headcount_source
    assert (d.acv_low, d.acv_high) == (14_000, 24_000)                 # 10k*1.4, 15k*1.6
    assert d.acv_mid == 19_000 and d.win_probability == 0.08 and d.expected_value == 1_520
    assert d.three_year_value == round(19_000 * (1 + 0.9 + 0.81), -2)
    assert len(d.explanation) == 5 and "$70.0M raised" in d.explanation[0]


def test_unknown_size_and_extra_points():
    d = v.estimate_value("acme.com", CompanyProfile(sells_in_eu_or_uk=True), "moderate", 7, {})
    assert d.headcount is None and "unknown" in d.headcount_source
    assert d.win_probability == 0.07                                    # 5% + 2 points above threshold


def test_enrichment_is_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(v.config, "CACHE_DIR", tmp_path)
    (tmp_path / "hunter").mkdir()
    (tmp_path / "hunter" / "company-acme.com.json").write_text(json.dumps({"data": {"metrics": {"employeesCount": 40}}}))
    data, note = v.company_enrichment("acme.com", "k")
    assert data["metrics"]["employeesCount"] == 40 and "cached" in note
