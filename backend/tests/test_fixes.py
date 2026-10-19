"""Fix generator: template drafts, grounded AI drafts, guards and quotas."""

import json

import pytest

from app.api import routes
from app.config import get_settings
from app.crawler.crawler import CrawledPage, CrawlResult
from app.analysis.extract import extract_page
from app.fixes.generator import _flag_unsupported_numbers, supports_fix
from app.providers import registry
from app.providers.base import AIProvider, ProviderAnswer
from app.services import jobs
from tests.test_accounts_and_limits import fake_resolve
from tests.test_api import HOME, FakeCrawler

SPA = '<html><head><title>Acme</title><script src="/a.js"></script></head><body><div id="root"></div></body></html>'


class HtmlCrawler(FakeCrawler):
    def __init__(self, html):
        super().__init__()
        self.html = html

    def crawl(self, url, progress=None):
        return CrawlResult(start_url=url, root_url=url, pages=[CrawledPage(extract_page(url, self.html), 200)],
                           robots={"found": False, "ai_crawlers": {}}, sitemap={"found": False}, https=True)


class DraftProvider(AIProvider):
    """Records the prompt it was given and returns a canned draft."""

    name = "anthropic"
    display_name = "Fake"

    def __init__(self, content="## FAQ\n\n**Is Acme free?** [ADD: pricing details]\n\nPlans cost $99 per month."):
        self.content, self.prompts = content, []

    def is_configured(self):
        return True

    def setup_instructions(self):
        return ""

    @property
    def model(self):
        return "fake-drafter"

    def answer(self, question):
        return ProviderAnswer(text="", model="fake-drafter")

    def complete_json(self, system, prompt, schema):
        self.prompts.append((system, prompt))
        return {"title": "FAQ page", "format": "markdown", "content": self.content,
                "placeholders": ["pricing details"], "notes": "Publish at /faq."}


@pytest.fixture(autouse=True)
def stubs(monkeypatch):
    monkeypatch.setattr(routes, "resolve_target", fake_resolve)
    monkeypatch.setattr(jobs, "crawler_factory", lambda: HtmlCrawler(HOME))
    yield
    registry.override_provider("anthropic", None)


def audited(client, monkeypatch=None, html=None):
    if html is not None:
        monkeypatch.setattr(jobs, "crawler_factory", lambda: HtmlCrawler(html))
    pid = client.post("/api/projects", json={"website_url": "acme.com", "brand_name": "Acme", "competitors": ["Globex"]}).json()["id"]
    client.post(f"/api/projects/{pid}/audits")
    return pid, {r["key"]: r for r in client.get(f"/api/projects/{pid}/recommendations").json()}


def test_supported_keys():
    assert supports_fix("crawl:sitemap") and supports_fix("content:faq") and supports_fix("competitors:globex")
    assert not supports_fix("crawl:js-rendering") and not supports_fix("visibility:brand-unknown")


def test_template_fixes_are_free_and_exact(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "quota_fix_generations_per_user_per_day", 0)  # templates don't need quota
    pid, recs = audited(client)
    assert recs["crawl:sitemap"]["fix_available"] and not recs.get("crawl:js-rendering", {}).get("fix_available")

    r = client.post(f"/api/recommendations/{recs['crawl:sitemap']['id']}/fixes")
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["generator"] == "template" and "<loc>https://acme.com/</loc>" in d["content"]

    org = client.post(f"/api/recommendations/{recs['schema:organization']['id']}/fixes").json()
    data = json.loads(org["content"].split(">", 1)[1].rsplit("<", 1)[0])
    assert data["@type"] == "Organization" and data["name"] == "Acme" and data["url"] == "https://acme.com/"
    assert data["logo"].startswith("[ADD:") and org["placeholders"]

    fixes = client.get(f"/api/recommendations/{recs['crawl:sitemap']['id']}/fixes").json()
    assert len(fixes) == 1 and fixes[0]["id"] == d["id"]


def test_ai_fix_is_grounded_in_site_content_and_flags_invented_numbers(client):
    provider = DraftProvider()
    registry.override_provider("anthropic", provider)
    pid, recs = audited(client)
    r = client.post(f"/api/recommendations/{recs['content:faq']['id']}/fixes")
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["generator"] == "fake-drafter" and d["sources"] == ["https://acme.com/"]
    assert "[ADD: pricing details]" in d["placeholders"]
    assert "$99" in d["notes"] and "don't appear on your crawled pages" in d["notes"]
    system, prompt = provider.prompts[0]
    assert "ONLY facts stated in the provided website content" in system
    assert "Acme - Project management for small teams" in prompt and "WEBSITE CONTENT" in prompt
    assert client.get("/api/usage").json()["fix_generation"]["used"] == 1


def test_ai_fix_refuses_without_site_content(client, monkeypatch):
    registry.override_provider("anthropic", DraftProvider())
    monkeypatch.setattr(get_settings(), "render_js", False)
    pid, recs = audited(client, monkeypatch, SPA)
    rec = recs["meta:descriptions"]
    r = client.post(f"/api/recommendations/{rec['id']}/fixes")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "no_site_content"
    assert client.get("/api/usage").json()["fix_generation"]["used"] == 0  # refused before using quota


def test_ai_fix_quota_and_missing_provider(client, monkeypatch):
    pid, recs = audited(client)
    r = client.post(f"/api/recommendations/{recs['content:faq']['id']}/fixes")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "provider_not_configured"
    registry.override_provider("anthropic", DraftProvider())
    monkeypatch.setattr(get_settings(), "quota_fix_generations_per_user_per_day", 1)
    assert client.post(f"/api/recommendations/{recs['content:faq']['id']}/fixes").status_code == 201
    r = client.post(f"/api/recommendations/{recs['content:faq']['id']}/fixes")
    assert r.status_code == 429


def test_unsupported_item(client):
    pid, recs = audited(client)
    rec = next(r for r in recs.values() if not r["fix_available"]) if any(not r["fix_available"] for r in recs.values()) else None
    if rec:
        assert client.post(f"/api/recommendations/{rec['id']}/fixes").status_code == 400


def test_number_flagging():
    assert _flag_unsupported_numbers("Costs $99 and 50% off, since 2019", "Our plan is $99 per month") == ["2019", "50%"]
    assert _flag_unsupported_numbers("No numbers here", "") == []
