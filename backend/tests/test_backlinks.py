"""Backlink & brand-mention discovery: verified pages only, real link attributes, honest statuses."""

import json

import httpx
import pytest

from app.api import backlink_routes, routes
from app.backlinks.discovery import DiscoveryProfile, build_queries, classify
from app.backlinks.search import BraveSearch
from app.config import Settings, get_settings
from app.crawler.fetcher import SafeFetcher
from app.providers import registry
from app.services import jobs
from tests.test_accounts_and_limits import fake_resolve
from tests.test_api import FakeCrawler

PAGES = {
    "https://akoladirectory.in/agri": (200, """<html><title>Akola Business Directory - Agriculture</title><body>
        <p>Agricultural suppliers in Akola</p><a href="/add">Add your business</a></body></html>"""),
    "https://akolanews.in/story": (200, """<html><title>Akola Times: Farmers flock to Gawande Krushi Kendra</title><body>
        <p>Gawande Krushi Kendra in Akola held a seed fair.</p>
        <a rel="nofollow" href="https://www.gkk.example/">their website</a></body></html>"""),
    "https://linkfarm.biz/x": (200, "<html><title>Akola links</title><body>Buy high quality backlinks today! agricultural</body></html>"),
    "https://dead.in/page": (404, "gone"),
    "https://unrelated.in/p": (200, "<html><title>Some page</title><body>nothing about the business</body></html>"),
}


class FakeSearch:
    name = "fakesearch"

    def __init__(self):
        self.calls = []

    def search(self, query, *, max_results=10, country=None):
        self.calls.append(query)
        if query.startswith('"Gawande'):
            return [{"url": "https://akolanews.in/story", "title": "News"}, {"url": "https://unrelated.in/p", "title": "x"},
                    {"url": "https://www.gkk.example/about", "title": "own site"}]
        return [{"url": "https://akoladirectory.in/agri", "title": "Dir"}, {"url": "https://linkfarm.biz/x", "title": "spam"},
                {"url": "https://dead.in/page", "title": "dead"}, {"url": "ftp://bad", "title": "bad"}]


def page_fetcher(pages):
    def handler(request):
        # The fetcher connects to the pinned IP; the Host header holds the real site
        url = f"https://{request.headers['host']}{request.url.path}"
        status, body = pages.get(url, (404, "not found"))
        return httpx.Response(status, headers={"content-type": "text/html"}, content=body.encode())

    return lambda: SafeFetcher(user_agent="t", transport=httpx.MockTransport(handler), resolver=lambda h, p: ["93.184.216.34"])


@pytest.fixture(autouse=True)
def stubs(monkeypatch):
    monkeypatch.setattr(routes, "resolve_target", fake_resolve)
    monkeypatch.setattr(jobs, "crawler_factory", lambda: FakeCrawler())
    monkeypatch.setattr(backlink_routes, "fetcher_factory", page_fetcher(PAGES))
    yield
    registry.override_provider("search", None)


def project(client):
    return client.post("/api/projects", json={"website_url": "gkk.example", "brand_name": "Gawande Krushi Kendra",
                                               "industry": "agricultural supplies store", "city": "Akola", "country": "IN"}).json()["id"]


def items_by_url(client, pid):
    return {i["url"]: i for i in client.get(f"/api/projects/{pid}/backlinks").json()["items"]}


def test_queries_and_classification():
    qs = build_queries(DiscoveryProfile(brand="GKK", domain="gkk.example", category="agri store", city="Akola", country="IN"))
    assert ("mention", '"GKK"') in qs and any("Akola" in q and "directory" in q for _, q in qs)
    assert classify("https://x.in/", "Akola Chamber of Commerce", "") == "chamber_association"
    assert classify("https://justdial.com/x", "Shops", "") == "directory"


def test_discovery_requires_a_search_api(client):
    pid = project(client)
    body = client.get(f"/api/projects/{pid}/backlinks").json()
    assert body["search_configured"] is False and "BRAVE_API_KEY" in body["setup"]
    r = client.post(f"/api/projects/{pid}/backlinks/discover")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "search_not_configured"


def test_discovery_verifies_pages_and_separates_existing_from_opportunities(client):
    search = FakeSearch()
    registry.override_provider("search", search)
    pid = project(client)
    r = client.post(f"/api/projects/{pid}/backlinks/discover")
    assert r.status_code == 200, r.text
    items = items_by_url(client, pid)
    # Only pages that loaded and are legitimate: no spam, no 404, no own site, no non-mentioning "mention" hits
    assert set(items) == {"https://akolanews.in/story", "https://akoladirectory.in/agri"}
    news = items["https://akolanews.in/story"]
    assert news["kind"] == "existing" and news["status"] == "found"
    assert news["value_type"] == "both" and news["link_rel"] == "nofollow"  # read from the page's <a rel>
    assert any("Links to you" in e for e in news["evidence"]) and news["category"] == "news"
    d = items["https://akoladirectory.in/agri"]
    assert d["kind"] == "opportunity" and d["status"] == "suggested" and d["category"] == "directory"
    assert d["submission_url"] == "https://akoladirectory.in/add" and d["link_rel"] == "unknown"
    assert "Akola" in d["relevance"] and d["outreach"] and d["why_it_helps"]
    # Recommendations pick it up
    recs = {x["key"]: x for x in client.get(f"/api/projects/{pid}/recommendations").json()}
    assert recs["backlinks:opportunities"]["group"] == "backlinks"

    # Re-running doesn't duplicate, and search results come from the cache
    n_calls = len(search.calls)
    client.post(f"/api/projects/{pid}/backlinks/discover")
    assert len(items_by_url(client, pid)) == 2 and len(search.calls) == n_calls


def test_opportunity_lifecycle_completed_then_verified_or_not_found(client, monkeypatch):
    registry.override_provider("search", FakeSearch())
    pid = project(client)
    client.post(f"/api/projects/{pid}/backlinks/discover")
    opp = items_by_url(client, pid)["https://akoladirectory.in/agri"]
    assert client.patch(f"/api/backlinks/{opp['id']}", json={"status": "verified"}).status_code == 422  # can't self-verify
    r = client.patch(f"/api/backlinks/{opp['id']}", json={"status": "completed", "note": "Submitted listing"})
    assert r.json()["status"] == "completed" and r.json()["note"] == "Submitted listing"

    # Not live yet: verification says so
    r = client.post(f"/api/backlinks/{opp['id']}/verify").json()
    assert r["status"] == "not_found" and "no link or mention" in r["evidence"][0]

    # Listing goes live with a followed link: verified, with the evidence
    live = dict(PAGES)
    live["https://akoladirectory.in/agri"] = (200, '<html><title>Dir</title><body>Gawande Krushi Kendra, Akola '
                                                   '<a href="https://gkk.example/">Website</a></body></html>')
    monkeypatch.setattr(backlink_routes, "fetcher_factory", page_fetcher(live))
    r = client.post(f"/api/backlinks/{opp['id']}/verify").json()
    assert r["status"] == "verified" and r["link_rel"] == "follow" and r["verified_at"] and r["kind"] == "opportunity"


def test_existing_items_are_updated_by_checks_not_by_hand(client):
    registry.override_provider("search", FakeSearch())
    pid = project(client)
    client.post(f"/api/projects/{pid}/backlinks/discover")
    news = items_by_url(client, pid)["https://akolanews.in/story"]
    assert client.patch(f"/api/backlinks/{news['id']}", json={"status": "completed"}).status_code == 400


def test_manual_add_and_isolation(client, other_client):
    pid = project(client)
    r = client.post(f"/api/projects/{pid}/backlinks", json={"url": "https://akolanews.in/story"})
    assert r.status_code == 201 and r.json()["kind"] == "existing"
    assert client.post(f"/api/projects/{pid}/backlinks", json={"url": "https://akolanews.in/story"}).status_code == 409
    assert client.post(f"/api/projects/{pid}/backlinks", json={"url": "https://dead.in/page"}).status_code == 422
    assert client.post(f"/api/projects/{pid}/backlinks", json={"url": "http://localhost/admin"}).status_code == 422
    item = r.json()["id"]
    assert other_client.get(f"/api/projects/{pid}/backlinks").status_code == 404
    assert other_client.post(f"/api/backlinks/{item}/verify").status_code == 404
    assert other_client.patch(f"/api/backlinks/{item}", json={"note": "x"}).status_code == 404


def test_discovery_quota(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "quota_backlink_discoveries_per_user_per_day", 1)
    registry.override_provider("search", FakeSearch())
    pid = project(client)
    assert client.post(f"/api/projects/{pid}/backlinks/discover").status_code == 200
    assert client.post(f"/api/projects/{pid}/backlinks/discover").status_code == 429


def test_brave_search_request_and_parsing():
    def handler(request):
        assert request.headers["x-subscription-token"] == "brave-key"
        assert request.url.params["q"] == "akola directory" and request.url.params["country"] == "IN"
        return httpx.Response(200, json={"web": {"results": [{"url": "https://a.in/", "title": "A", "description": "d"}]}})

    b = BraveSearch(Settings(_env_file=None, brave_api_key="brave-key"), transport=httpx.MockTransport(handler))
    assert b.search("akola directory", country="in") == [{"url": "https://a.in/", "title": "A", "snippet": "d"}]
