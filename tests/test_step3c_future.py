from datetime import date

from outreach.step2_extract import CompanyProfile
from outreach.step3c_future import assess_future, missing_signals

D = date(2026, 11, 19)


def test_near_miss_lists_signals_that_close_the_gap():
    p = CompanyProfile(regulated_industry="HR")        # has the regulated-industry signal already
    f = assess_future(p, "disqualified", "ICP score 4 is below the threshold of 5.", 4, {}, D)
    assert f.category == "near_miss" and f.gap == 1 and f.priority == "high" and f.recheck_date == "2027-02-18"
    assert any("Series A-C" in w for w in f.would_qualify_if)
    assert not any("regulated" in w for w in f.would_qualify_if)


def test_company_data_that_closes_the_gap_means_recheck_now():
    f = assess_future(CompanyProfile(), "disqualified", "ICP score 4 is below the threshold of 5.", 4,
                      {"metrics": {"employeesCount": 120, "raised": 20_000_000}}, D)
    assert f.label == "Re-check now" and f.priority == "high"
    assert any("120 employees" in e for e in f.evidence_now) and any("$20.0M raised" in e for e in f.evidence_now)


def test_outside_size_band_does_not_count():
    f = assess_future(CompanyProfile(), "disqualified", "ICP score 3 is below the threshold of 5.", 3,
                      {"metrics": {"employeesCount": 4000}}, D)
    assert f.label == "Near miss" and f.gap == 2 and f.priority == "medium"


def test_categories_for_gates():
    assert assess_future(CompanyProfile(), "disqualified", "Already runs compliance on Vanta (...)", 6, None, D).category == "renewal_watch"
    assert assess_future(CompanyProfile(), "disqualified", "Already holds both SOC 2 and ISO 27001 - solved.", 2, None, D).category == "expansion_watch"
    assert assess_future(CompanyProfile(), "disqualified", "Not a software/SaaS business.", 4, None, D).category == "not_a_fit"
    assert assess_future(CompanyProfile(), "manual_review", "Couldn't tell", 0, None, D).category == "manual_review"
    assert assess_future(CompanyProfile(), "qualified", "ok", 6, None, D).category == "lead_now"


def test_missing_signals_sorted_by_points():
    pts = [m[0] for m in missing_signals(CompanyProfile())]
    assert pts == sorted(pts, reverse=True) and pts[0] == 3
