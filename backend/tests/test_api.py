import pytest

from app.api import routes
from app.crawler.crawler import CrawledPage, CrawlResult
from app.crawler.fetcher import FetchError
from app.crawler.url_safety import ResolvedTarget, UnsafeURLError, normalize_url
from app.analysis.extract import extract_page
from app.providers import registry
from app.providers.base import AIProvider, ProviderAnswer, ProviderError
from app.services import jobs

HOME = """<html><head><title>Acme - Project management for small teams</title>
<meta name="description" content="Acme helps small teams plan projects, track tasks and ship on time with boards.">
</head><body><h1>Acme</h1><h2>Features</h2><p>""" + "word " * 300 + "</p></body></html>"


def fake_resolve(url):
    normalized = normalize_url(url)
    host = normalized.split("/")[2]
    if host.startswith("private."):
        raise UnsafeURLError("Hostname resolves to a non-public address")
    return ResolvedTarget(url=normalized, scheme="https", host=host, port=443, ip="93.184.216.34")


class FakeCrawler:
    def __init__(self, fail=False):
        self.fail = fail

    def crawl(self, url, progress=None):
        progress and progress("Fetching homepage")
        if self.fail:
            raise FetchError(
                "The website refused access to our crawler (HTTP 403).", code="blocked", url="https://acme.com/", status_code=403
            )
        return CrawlResult(
            start_url=url, root_url=url, pages=[CrawledPage(extract_page(url, HOME), 200)],
            robots={"found": True, "ai_crawlers": {}}, sitemap={"found": False}, https=True,
        )

    def close(self):
        pass


class FakeProvider(AIProvider):
    name = "anthropic"
    display_name = "Fake Claude"

    def __init__(self, fatal_on=None):
        self.fatal_on = fatal_on

    def is_configured(self):
        return True

    def setup_instructions(self):
        return ""

    @property
    def model(self):
        return "fake-model"

    def answer(self, question):
        if "free" in question.lower():
            raise ProviderError("The request to Anthropic timed out.", retryable=True)
        if self.fatal_on and self.fatal_on in question:
            raise ProviderError("Anthropic rejected the API key (authentication failed).", fatal=True)
        if "alternatives" in question.lower():
            return ProviderAnswer(text="Try Globex or Initech.", model="fake-model", sources=[{"url": "https://globex.io", "type": "cited"}])
        return ProviderAnswer(
            text="Acme is a solid choice; Globex is also popular.",
            model="fake-model",
            sources=[{"url": "https://acme.com/pricing", "type": "cited", "title": "Pricing"}],
        )

    def complete_json(self, system, prompt, schema):
        raise ProviderError("not used")


@pytest.fixture(autouse=True)
def stubs(monkeypatch):
    monkeypatch.setattr(routes, "resolve_target", fake_resolve)
    monkeypatch.setattr(jobs, "crawler_factory", lambda: FakeCrawler())
    yield
    registry.override_provider("anthropic", None)


def create(client, **overrides):
    body = {"website_url": "acme.com", "brand_name": "Acme", "industry": "project management software",
            "competitors": [{"name": "Globex", "website_url": "globex.io"}, "Initech", "acme"]}
    body.update(overrides)
    return client.post("/api/projects", json=body)


def test_create_project_validates_input(client):
    assert create(client, website_url="http://localhost:3000").status_code == 422
    assert create(client, website_url="ftp://acme.com").status_code == 422
    assert create(client, website_url="https://private.acme.com").status_code == 422
    assert create(client, brand_name="   ").status_code == 422
    r = create(client, website_url="http://10.0.0.1/")
    assert r.status_code == 422 and "not allowed" in r.json()["detail"]


def test_create_project_normalizes_and_dedupes(client):
    r = create(client)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["website_url"] == "https://acme.com/"
    assert data["domain"] == "acme.com"
    assert [c["name"] for c in data["competitors"]] == ["Globex", "Initech"]  # brand name dropped
    assert client.get("/api/projects").json()[0]["id"] == data["id"]


def test_providers_report_not_configured(client):
    status = {p["name"]: p for p in client.get("/api/providers").json()}
    assert list(status) == ["openai", "anthropic", "gemini", "perplexity"]
    assert [p["assistant"] for p in status.values()] == ["ChatGPT", "Claude", "Gemini", "Perplexity"]
    for name, env in [("openai", "OPENAI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY"), ("gemini", "GEMINI_API_KEY"), ("perplexity", "PERPLEXITY_API_KEY")]:
        assert status[name]["configured"] is False and env in status[name]["setup_instructions"]
        assert "not identical" in status[name]["experience"]  # API results are labelled as such


def test_full_workflow(client):
    pid = create(client).json()["id"]

    # Audit runs in a background task (synchronously under TestClient)
    r = client.post(f"/api/projects/{pid}/audits")
    assert r.status_code == 202
    audit = client.get(f"/api/audits/{r.json()['id']}").json()
    assert audit["status"] == "completed"
    assert 0 <= audit["score"] <= 100 and audit["pages_crawled"] == 1
    page = audit["pages"][0]
    assert page["title"].startswith("Acme")
    assert page["meta_description"].startswith("Acme helps")
    assert [h["text"] for h in page["headings"]] == ["Acme", "Features"]
    assert page["text_excerpt"].startswith("Acme Features word")
    assert audit["site_info"]["root_url"] == "https://acme.com/"

    # Without provider credentials: template questions, and runs are refused with setup info
    q = client.post(f"/api/projects/{pid}/questions/generate").json()
    assert q["source"] == "template" and len(q["questions"]) == 20
    r = client.post(f"/api/projects/{pid}/runs", json={})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "provider_not_configured"
    recs = client.get(f"/api/projects/{pid}/recommendations").json()
    assert recs and all(rec["evidence"] is not None for rec in recs)
    assert any("FAQ" in rec["issue"] for rec in recs)

    # With a (fake) configured provider
    registry.override_provider("anthropic", FakeProvider())
    r = client.post(f"/api/projects/{pid}/runs", json={"provider": "anthropic"})
    assert r.status_code == 202, r.text
    run = client.get(f"/api/runs/{r.json()['id']}").json()
    assert run["status"] == "completed"
    m = run["metrics"]
    answers = run["answers"]
    assert len(answers) == 20
    failed = [a for a in answers if a["error"]]
    ok = [a for a in answers if not a["error"]]
    assert m["questions_failed"] == len(failed) > 0
    assert m["questions_tested"] == len(ok)
    mentioned = sum(a["brand_mentioned"] for a in ok)
    assert m["brand_mention_rate"] == round(100 * mentioned / len(ok), 1)
    assert m["website_citation_rate"] == round(100 * sum(a["website_cited"] for a in ok) / len(ok), 1)
    sample = next(a for a in ok if a["brand_mentioned"])
    kinds = {(mm["entity_name"], mm["kind"]) for mm in sample["mentions"]}
    assert ("Acme", "mention") in kinds and ("Acme", "citation") in kinds and ("Globex", "mention") in kinds
    assert sample["mentions"][0]["evidence"]
    assert run["conditions"]["competitors"][0]["domain"] == "globex.io"

    dash = client.get(f"/api/projects/{pid}/dashboard").json()
    assert dash["latest_run_metrics"]["brand_mention_rate"] == m["brand_mention_rate"]
    assert dash["latest_audit"]["score"] == audit["score"]
    assert len(client.get(f"/api/projects/{pid}/audits").json()) == 1
    assert len(client.get(f"/api/projects/{pid}/runs").json()) == 1


def test_fatal_provider_error_fails_run(client):
    pid = create(client).json()["id"]
    client.post(f"/api/projects/{pid}/questions/generate")
    registry.override_provider("anthropic", FakeProvider(fatal_on="Acme"))
    r = client.post(f"/api/projects/{pid}/runs", json={})
    run = client.get(f"/api/runs/{r.json()['id']}").json()
    assert run["status"] == "failed"
    assert "authentication" in run["error"]


def test_run_requires_questions_and_audit_failure_is_recorded(client, monkeypatch):
    pid = create(client).json()["id"]
    registry.override_provider("anthropic", FakeProvider())
    r = client.post(f"/api/projects/{pid}/runs", json={})
    assert r.status_code == 400 and "Generate questions" in r.json()["detail"]

    monkeypatch.setattr(jobs, "crawler_factory", lambda: FakeCrawler(fail=True))
    r = client.post(f"/api/projects/{pid}/audits")
    audit = client.get(f"/api/audits/{r.json()['id']}").json()
    assert audit["status"] == "failed" and "refused access" in audit["error"]
    # A failed fetch never looks like a successful audit
    assert audit["score"] is None and audit["pages"] == [] and audit["checks"] == []
    assert audit["site_info"]["error"] == {
        "code": "blocked", "message": audit["error"], "url": "https://acme.com/", "status_code": 403,
    }
    dash = client.get(f"/api/projects/{pid}/dashboard").json()
    assert dash["latest_audit"] is None  # failed audits are not reported as the latest result


def test_unsafe_redirect_during_audit_is_recorded(client, monkeypatch):
    class RedirectsToPrivate(FakeCrawler):
        def crawl(self, url, progress=None):
            raise UnsafeURLError("Hostname 'internal.acme.com' resolves to a non-public address")

    pid = create(client).json()["id"]
    monkeypatch.setattr(jobs, "crawler_factory", lambda: RedirectsToPrivate())
    audit = client.get(f"/api/audits/{client.post(f'/api/projects/{pid}/audits').json()['id']}").json()
    assert audit["status"] == "failed" and audit["site_info"]["error"]["code"] == "unsafe_url"
    assert "non-public" in audit["error"]


def test_api_errors_are_json_with_detail(client):
    r = create(client, website_url="not a url")
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)
    r = client.post("/api/projects/12345/audits")
    assert r.status_code == 404 and r.json() == {"detail": "Project not found"}


def test_unknown_resources_404(client):
    assert client.get("/api/projects/999").status_code == 404
    assert client.get("/api/audits/999").status_code == 404
    assert client.get("/api/runs/999").status_code == 404


def test_recover_interrupted_jobs(client, engine):
    from app.db import session_scope
    from app.models import WebsiteAudit

    pid = create(client).json()["id"]
    with session_scope() as db:
        db.add(WebsiteAudit(project_id=pid, status="running"))
        db.commit()
        jobs.recover_interrupted_jobs(db)
        audit = db.query(WebsiteAudit).one()
        assert audit.status == "failed" and "restarted" in audit.error


def test_run_api_flags_branded_questions_and_unknown_brand(client):
    class NotFoundProvider(FakeProvider):
        def answer(self, question):
            if "Acme" in question:
                return ProviderAnswer(text="I couldn't find any reliable information about Acme.", model="fake-model")
            return ProviderAnswer(text="Popular choices are Globex and Initech.", model="fake-model")

    pid = create(client).json()["id"]
    client.post(f"/api/projects/{pid}/questions/generate")
    registry.override_provider("anthropic", NotFoundProvider())
    run = client.get(f"/api/runs/{client.post(f'/api/projects/{pid}/runs', json={}).json()['id']}").json()
    m = run["metrics"]
    branded = [a for a in run["answers"] if a["branded_question"]]
    assert branded and all(a["brand_unknown"] and "couldn't find" in a["brand_unknown_evidence"] for a in branded)
    assert m["brand_mentions"] == 0 and m["brand_mention_rate"] == 0.0  # "couldn't find Acme" is not a mention
    assert m["unbranded_mention_rate"] == 0.0 and m["branded_unknown"] == len(branded)
    recs = client.get(f"/api/projects/{pid}/recommendations").json()
    unknown = next(r for r in recs if r["key"] == "visibility:brand-unknown")
    assert "can't find information about Acme" in unknown["issue"] and unknown["priority"] == "high"
    assert unknown["verify"] and unknown["status"] == "open" and unknown["detected"]


# ----------------------------------------------------------------- action plan
FIXED_HOME = HOME.replace("<h2>Features</h2>", "<h2>Features</h2><h2>FAQ</h2><h3>Is Acme free?</h3><h3>Does Acme work offline?</h3><h3>Who is Acme for?</h3>")


class SwitchableCrawler(FakeCrawler):
    html = HOME

    def crawl(self, url, progress=None):
        result = super().crawl(url, progress)
        result.pages = [CrawledPage(extract_page(url, SwitchableCrawler.html), 200)]
        return result


def _recs_by_key(client, pid):
    return {r["key"]: r for r in client.get(f"/api/projects/{pid}/recommendations").json()}


def test_action_plan_status_survives_reaudit_and_tracks_resolution(client, monkeypatch):
    SwitchableCrawler.html = HOME
    monkeypatch.setattr(jobs, "crawler_factory", lambda: SwitchableCrawler())
    pid = create(client).json()["id"]
    client.post(f"/api/projects/{pid}/audits")
    recs = _recs_by_key(client, pid)
    faq, sitemap = recs["content:faq"], recs["crawl:sitemap"]
    assert faq["status"] == "open" and faq["detected"] and faq["verify"] and faq["effort"] in ("low", "medium", "high")

    # The user plans one item and marks another completed
    r = client.patch(f"/api/recommendations/{faq['id']}", json={"status": "in_progress", "note": "Drafting FAQ"})
    assert r.status_code == 200 and r.json()["status"] == "in_progress" and r.json()["status_updated_at"]
    client.patch(f"/api/recommendations/{sitemap['id']}", json={"status": "completed"})

    # Re-audit after the FAQ was added (the sitemap is still missing)
    SwitchableCrawler.html = FIXED_HOME
    client.post(f"/api/projects/{pid}/audits")
    recs = _recs_by_key(client, pid)
    assert recs["content:faq"]["id"] == faq["id"]  # same item, not a new one
    assert recs["content:faq"]["detected"] is False and recs["content:faq"]["resolved_at"]
    assert recs["content:faq"]["status"] == "in_progress" and recs["content:faq"]["note"] == "Drafting FAQ"
    # Marked completed but still detected: the UI warns about this
    assert recs["crawl:sitemap"]["status"] == "completed" and recs["crawl:sitemap"]["detected"] is True
    assert recs["crawl:sitemap"]["last_detected_at"] > recs["crawl:sitemap"]["status_updated_at"]

    dash = client.get(f"/api/projects/{pid}/dashboard").json()
    assert dash["action_plan"]["no_longer_detected"] >= 1 and dash["action_plan"]["completed"] == 1

    # If the problem comes back, the same item is detected again
    SwitchableCrawler.html = HOME
    client.post(f"/api/projects/{pid}/audits")
    again = _recs_by_key(client, pid)["content:faq"]
    assert again["id"] == faq["id"] and again["detected"] is True and again["resolved_at"] is None


def test_items_not_rechecked_are_not_marked_resolved(client, monkeypatch):
    SwitchableCrawler.html = HOME
    monkeypatch.setattr(jobs, "crawler_factory", lambda: SwitchableCrawler())
    pid = create(client).json()["id"]
    client.post(f"/api/projects/{pid}/audits")
    assert _recs_by_key(client, pid)["content:faq"]["detected"]
    # Site becomes a JavaScript shell: content checks can't be evaluated, so the FAQ item stays open
    SwitchableCrawler.html = '<html><head><title>Acme</title><script src="/a.js"></script></head><body><div id="root"></div></body></html>'
    client.post(f"/api/projects/{pid}/audits")
    recs = _recs_by_key(client, pid)
    assert recs["crawl:js-rendering"]["blocking"] and recs["crawl:js-rendering"]["detected"]
    assert recs["content:faq"]["detected"] is True  # not falsely "resolved"
    # The blocking root cause is listed first
    assert client.get(f"/api/projects/{pid}/recommendations").json()[0]["key"] == "crawl:js-rendering"


def test_recommendation_update_validation(client):
    assert client.patch("/api/recommendations/999", json={"status": "completed"}).status_code == 404
    pid = create(client).json()["id"]
    client.post(f"/api/projects/{pid}/audits")
    rec = client.get(f"/api/projects/{pid}/recommendations").json()[0]
    assert client.patch(f"/api/recommendations/{rec['id']}", json={"status": "bogus"}).status_code == 422
    r = client.patch(f"/api/recommendations/{rec['id']}", json={"note": "   "})
    assert r.status_code == 200 and r.json()["note"] is None and r.json()["status"] == "open"


def test_local_profile_create_validate_and_partial_update(client):
    r = create(client, city="Akola", region="Maharashtra", country="in", phone="+91 98765 43210",
               services=["Seeds", "seeds", "Fertilizers"], profile_urls=["https://g.page/r/abc", "https://g.page/r/abc"])
    assert r.status_code == 201, r.text
    p = r.json()
    assert (p["city"], p["country"], p["services"], p["profile_urls"]) == ("Akola", "IN", ["Seeds", "Fertilizers"], ["https://g.page/r/abc"])
    assert create(client, country="India").status_code == 422
    assert create(client, phone="call me").status_code == 422
    assert create(client, profile_urls=["javascript:alert(1)"]).status_code == 422
    # Updating only competitors must not wipe the local profile
    r = client.put(f"/api/projects/{p['id']}", json={"competitors": ["Globex"]})
    assert r.json()["city"] == "Akola" and r.json()["phone"] == "+91 98765 43210"
    r = client.put(f"/api/projects/{p['id']}", json={"city": "Amravati", "phone": None})
    assert r.json()["city"] == "Amravati" and r.json()["phone"] is None and [c["name"] for c in r.json()["competitors"]] == ["Globex"]
