from pathlib import Path

from outreach import step1_scrape as s1

HTML = (Path(__file__).parent / "fixtures" / "acme_home.html").read_text()


def test_clean_drops_chrome_short_blocks_and_duplicates():
    title, text = s1.clean_html(HTML)
    assert title.startswith("Acme")
    assert "payroll API that HR and fintech platforms" in text          # meta description kept
    assert text.count("single API to calculate") == 1                    # deduplicated
    assert "Short line" not in text                                      # under 8 words
    assert "cookies" not in text                                         # cookie banner
    assert "Copyright" not in text                                       # footer
    assert "## Payroll infrastructure for platforms" in text             # heading kept


def test_cert_mentions_come_from_raw_html_including_alt_text_not_scripts():
    certs = s1.find_cert_mentions(HTML)
    assert "SOC 2" in certs           # only in footer <img alt>
    assert "ISO 27001" not in certs   # only inside <script>


def test_discover_links_classifies_and_skips_login():
    links = s1.discover_links(HTML, "https://acme.com", "acme.com")
    assert links["security"] == ["https://acme.com/security"]
    assert links["careers"] == ["https://acme.com/careers"]
    assert links["pricing"] == ["https://acme.com/pricing"]
    assert "https://acme.com/login" not in sum(links.values(), [])


def test_normalize_domain():
    assert s1.normalize_domain("https://www.Acme.com/about") == "acme.com"


class FakeResp:
    def __init__(self, status, text="", headers=None):
        self.status_code, self.text, self.url = status, text, "https://acme.com"
        self.headers = headers or {"content-type": "text/html; charset=utf-8"}
        self.encoding = "utf-8"


class FakeFetcher:
    def __init__(self, resp, allowed=True):
        self.resp, self._allowed = resp, allowed

    def allowed(self, url):
        return self._allowed

    def get(self, url):
        return self.resp


def test_fetch_page_respects_robots():
    page = s1.fetch_page("https://acme.com", "homepage", "acme.com", FakeFetcher(FakeResp(200, HTML), allowed=False), use_cache=False)
    assert not page.ok and page.failure.startswith("robots_disallowed")


def test_fetch_page_records_bot_block_instead_of_evading():
    resp = FakeResp(403, "", {"content-type": "text/html", "cf-ray": "abc"})
    page = s1.fetch_page("https://acme.com", "homepage", "acme.com", FakeFetcher(resp), use_cache=False)
    assert not page.ok and "cloudflare" in page.failure


def test_fetch_page_success(tmp_path, monkeypatch):
    monkeypatch.setattr(s1.config, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(s1, "_fetch_with_browser", lambda url: None)   # never launch a browser in tests
    page = s1.fetch_page("https://acme.com", "homepage", "acme.com", FakeFetcher(FakeResp(200, HTML)), use_cache=True)
    assert page.ok and page.word_count > 20 and "SOC 2" in page.cert_mentions
    again = s1.fetch_page("https://acme.com", "homepage", "acme.com", FakeFetcher(FakeResp(500)), use_cache=True)
    assert again.ok and again.from_cache
