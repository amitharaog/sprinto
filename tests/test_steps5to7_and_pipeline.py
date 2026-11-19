import json
import smtplib
from email import message_from_bytes

from outreach import pipeline as pl
from outreach import step3_qualify as s3
from outreach import step7_send as s7
from outreach.step1_scrape import Page
from outreach.step2_extract import CompanyProfile, Evidence
from outreach.step5_pain import PainPoint, PainPoints
from outreach.step6_email import EmailDraft, validate

FACT = "Now hiring: GRC & Compliance Manager"
GOOD_BODY = (
    "Hi Cy,\n\n"
    "Saw that Acme is hiring a GRC & Compliance Manager while rolling out an enterprise plan with SSO. "
    "That usually means security questionnaires are landing on your desk faster than the team can answer them, "
    "and a SOC 2 audit is not far behind.\n\n"
    "Sprinto connects to the cloud, HR and code tools you already use and collects audit evidence automatically, "
    "so your new hire starts from a monitored control set instead of spreadsheets.\n\n"
    "Worth a 15-minute call next week to compare notes?\n\nSam Lee\nGrowth, Sprinto"
)


def good_draft(**kw):
    d = dict(subject="Your GRC hire and SOC 2", body=GOOD_BODY, hook_fact=FACT,
             pain_point_used="questionnaires", why_written_this_way="Hook on the hire.")
    d.update(kw)
    return EmailDraft(**d)


def test_validate_accepts_good_draft():
    assert validate(good_draft(), "Cy", [FACT]) == []


def test_validate_catches_common_failures():
    bad = good_draft(body="Hello there [Name]! I hope this email finds you well. " * 3, hook_fact="made up")
    problems = " ".join(validate(bad, "Cy", [FACT]))
    for expected in ("Hi Cy", "words", "placeholder", "hope this email finds you", "exclamation", "hook_fact"):
        assert expected in problems


def test_message_is_always_addressed_to_my_email(monkeypatch, tmp_path):
    monkeypatch.setattr(s7.config, "MY_EMAIL", "me@example.com")
    monkeypatch.setattr(s7.config, "GMAIL_ADDRESS", "me@example.com")
    monkeypatch.setattr(s7.config, "GMAIL_APP_PASSWORD", "pw")
    sent = {}

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self, u, p): sent["login"] = u
        def send_message(self, msg, to_addrs): sent["to"] = to_addrs; sent["msg"] = msg

    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    msg = s7.build_message("Subj", "Hi Cy,\nbody", "Intended recipient: cy@acme.com")
    r = s7.send(msg, tmp_path / "a.eml")
    assert r.sent and sent["to"] == ["me@example.com"] and msg["To"] == "me@example.com"
    assert "cy@acme.com" not in msg["To"]
    assert (tmp_path / "a.eml").exists()


def test_auth_failure_is_permanent(monkeypatch, tmp_path):
    for k, v in {"MY_EMAIL": "me@x.com", "GMAIL_ADDRESS": "me@x.com", "GMAIL_APP_PASSWORD": "bad"}.items():
        monkeypatch.setattr(s7.config, k, v)

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self, u, p): raise smtplib.SMTPAuthenticationError(535, b"bad creds")

    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    try:
        s7.send(s7.build_message("s", "b", ""), tmp_path / "a.eml")
        assert False
    except s7.AuthFailed as e:
        assert "App Password" in str(e)


def test_end_to_end_pipeline(monkeypatch, tmp_path, fake_llm_cls):
    """Homepage -> loop fetches careers -> qualifies -> PoC from manual file -> pains -> email -> 'sent'."""
    home = Page(url="https://acme.com", kind="homepage", ok=True, text="Acme payroll API " * 40,
                word_count=120, links={"careers": ["https://acme.com/careers"]})
    monkeypatch.setattr(pl, "scrape_homepage", lambda d, f, c: home)
    monkeypatch.setattr(s3, "fetch_page", lambda url, kind, d, f, c=True: Page(
        url=url, kind=kind, ok=url.endswith("/careers"), text="CAREERS Series B GRC", word_count=40,
        failure=None if url.endswith("/careers") else "http_404"))

    def profile(user):
        p = CompanyProfile(company_name="Acme", one_line_description="Payroll API for HR platforms",
                           is_software_product=True, sells_to_businesses=True, regulated_industry="payroll")
        if "CAREERS" in user:
            p.enterprise_signals = ["Enterprise plan with SSO"]
            p.funding_stage = "series_b"
            p.security_or_compliance_roles = ["GRC & Compliance Manager"]
            p.evidence = [Evidence(field="security_or_compliance_roles", quote=FACT, url="https://acme.com/careers")]
        return p

    pains = PainPoints(points=[PainPoint(pain="Questionnaires pile up", why_this_person="owns security",
                                         evidence=FACT, sprinto_angle="questionnaires"),
                               PainPoint(pain="SOC 2 prep pulls engineers", why_this_person="x",
                                         evidence="Enterprise plan with SSO", sprinto_angle="evidence")])
    bad_then_good = iter([good_draft(body="Hi Cy, too short?"), good_draft()])
    llm = fake_llm_cls(profile, {"PainPoints": pains, "EmailDraft": lambda u: next(bad_then_good)})

    manual = tmp_path / "manual.json"
    manual.write_text(json.dumps({"acme.com": [
        {"first_name": "Di", "last_name": "Fe", "position": "VP Sales", "email": "di@acme.com"},
        {"first_name": "Cy", "last_name": "Lo", "position": "Head of Security", "email": "cy@acme.com"}]}))
    monkeypatch.setattr(pl.config, "MANUAL_CONTACTS_FILE", manual)
    monkeypatch.setattr(pl.config, "HUNTER_API_KEY", "")
    monkeypatch.setattr(s7.config, "MY_EMAIL", "me@example.com")

    out = tmp_path / "run"
    results = pl.Pipeline(llm, out_dir=out, dry_run=True, log=lambda *a: None).run(["https://www.acme.com"])
    r = results[0]
    assert r.outcome == "drafted", r.summary
    q = r.trace["step3_qualification"]
    assert q["status"] == "qualified_flagged"                     # /security 404'd: cert unknown -> qualify + flag
    assert "certified" in q["flags"][0]
    assert [s.url for s in q["loop_trace"] if s.url] == ["https://acme.com/security", "https://acme.com/careers"]
    assert r.trace["step6_email"]["attempts"] == 2                # first draft failed validation, was rewritten
    eml = message_from_bytes((out / "emails" / "acme.com.eml").read_bytes())
    assert eml["To"] == "me@example.com"
    body = eml.get_payload()
    assert body.startswith("Hi Cy,") and "WHY THIS PERSON" in body and "cy@acme.com" in body
    trace = json.loads((out / "acme.com.json").read_text())
    assert trace["trace"]["step4_poc"]["contact"]["first_name"] == "Cy"
    assert "acme.com" in (out / "summary.md").read_text()


def test_pipeline_records_scrape_failure_and_continues(monkeypatch, tmp_path, fake_llm_cls):
    monkeypatch.setattr(pl, "scrape_homepage", lambda d, f, c: Page(url="https://x.com", kind="homepage",
                                                                     ok=False, failure="blocked (403, cloudflare)"))
    res = pl.Pipeline(fake_llm_cls(), out_dir=tmp_path, dry_run=True, log=lambda *a: None).run(["x.com", "y.com"])
    assert [r.outcome for r in res] == ["failed", "failed"] and "cloudflare" in res[0].summary
