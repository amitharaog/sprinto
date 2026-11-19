import json

from outreach import step4_poc as s4
from outreach.step2_extract import CompanyProfile


def test_role_buckets():
    assert s4.role_bucket("Co-founder & CTO") == "tech_exec"
    assert s4.role_bucket("Head of Security") == "security"
    assert s4.role_bucket("GRC Manager") == "compliance"
    assert s4.role_bucket("Founder & CEO") == "founder_ceo"
    assert s4.role_bucket("VP of Engineering") == "tech_exec"
    assert s4.role_bucket("VP Sales") is None
    assert s4.role_bucket("Head of People") is None
    assert s4.role_bucket("Product Marketing Manager") is None
    assert s4.role_bucket("") is None


def test_size_band():
    assert s4.size_band(CompanyProfile(headcount_estimate=30)) == "small"
    assert s4.size_band(CompanyProfile(funding_stage="series_b")) == "mid"
    assert s4.size_band(CompanyProfile(headcount_estimate=900)) == "large"


PEOPLE = [
    s4.Contact("Ana", "Ray", "ana@acme.com", "CEO & Co-founder", "hunter", 95),
    s4.Contact("Ben", "Ito", "ben@acme.com", "CTO", "hunter", 90),
    s4.Contact("Cy", "Lo", "cy@acme.com", "Head of Security", "hunter", 80),
    s4.Contact("Di", "Fe", "di@acme.com", "VP Sales", "hunter", 99),
]


def test_ranking_changes_with_company_size():
    assert s4.rank(list(PEOPLE), "small")[0].first_name == "Ana"
    assert s4.rank(list(PEOPLE), "mid")[0].first_name == "Cy"
    assert all(c.first_name != "Di" for c in s4.rank(list(PEOPLE), "mid"))


def test_find_poc_uses_hunter_cache_and_explains(tmp_path, monkeypatch):
    monkeypatch.setattr(s4.config, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(s4.config, "HUNTER_API_KEY", "k")
    monkeypatch.setattr(s4.config, "MANUAL_CONTACTS_FILE", tmp_path / "none.json")
    (tmp_path / "hunter").mkdir()
    (tmp_path / "hunter" / "acme.com.json").write_text(json.dumps({"data": {"emails": [
        {"value": "cy@acme.com", "first_name": "Cy", "last_name": "Lo", "position": "Head of Security", "confidence": 91},
        {"value": "di@acme.com", "first_name": "Di", "last_name": "Fe", "position": "VP Sales", "confidence": 99},
        {"value": "info@acme.com", "first_name": None, "position": None},
    ]}}))
    r = s4.find_poc("acme.com", CompanyProfile(funding_stage="series_b"))
    assert r.contact.email == "cy@acme.com"
    assert "Head of Security" in r.why and "mid" in r.why
    assert "cached" in r.source_notes[0]


def test_find_poc_refuses_to_pick_irrelevant_people(tmp_path, monkeypatch):
    monkeypatch.setattr(s4.config, "HUNTER_API_KEY", "")
    f = tmp_path / "m.json"
    f.write_text(json.dumps({"acme.com": [{"first_name": "Di", "position": "VP Sales", "email": "d@acme.com"}]}))
    monkeypatch.setattr(s4.config, "MANUAL_CONTACTS_FILE", f)
    r = s4.find_poc("acme.com", CompanyProfile())
    assert r.contact is None and "Not emailing" in r.why
