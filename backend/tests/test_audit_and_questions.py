import httpx

from app.analysis.audit import evaluate
from app.analysis.extract import extract_page
from app.crawler.crawler import CrawledPage, CrawlResult, SiteCrawler
from app.crawler.fetcher import SafeFetcher
from app.providers.base import AIProvider, ProviderAnswer, ProviderError
from app.questions.generator import CATEGORIES, QuestionContext, generate_questions, template_questions

GOOD_HTML = """
<html lang="en"><head>
<title>Acme - Project management for small teams</title>
<meta name="description" content="Acme helps small teams plan projects, track tasks and ship on time with simple boards and timelines.">
<link rel="canonical" href="https://acme.com/">
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Organization","name":"Acme"},
 {"@type":"FAQPage","mainEntity":[{"@type":"Question","name":"Is Acme free?"}]}]}</script>
<script>var x = "should not be text";</script>
</head><body>
<nav><a href="/pricing">Pricing</a> <a href="https://twitter.com/acme">Twitter</a> <a href="mailto:a@b.c">Mail</a></nav>
<h1>Acme</h1><h2>Features</h2><p>""" + ("word " * 300) + """</p>
<h2>FAQ</h2><h3>Is Acme free?</h3><p>Yes.</p><h3>Does Acme integrate with Slack?</h3>
</body></html>
"""

BAD_HTML = "<html><head></head><body><p>Hello</p><script type='application/ld+json'>{broken</script></body></html>"


def test_extract_page():
    page = extract_page("https://acme.com/", GOOD_HTML)
    assert page.title == "Acme - Project management for small teams"
    assert page.meta_description.startswith("Acme helps")
    assert page.canonical == "https://acme.com/"
    assert page.lang == "en"
    assert page.h1 == ["Acme"]
    assert {"Organization", "FAQPage", "Question"} <= set(page.schema_types)
    assert page.has_faq
    assert "Is Acme free?" in page.faq_questions
    assert page.internal_links == ["https://acme.com/pricing"]
    assert page.external_links == ["https://twitter.com/acme"]
    assert "should not be text" not in page.text
    assert page.word_count > 300


def test_extract_page_flags_invalid_json_ld():
    page = extract_page("https://acme.com/x", BAD_HTML)
    assert page.schema_errors and not page.schema_types and not page.has_faq
    assert page.title is None


def _crawl(*pages, robots=None, sitemap=None, https=True):
    return CrawlResult(
        start_url="https://acme.com/",
        root_url="https://acme.com/",
        pages=[CrawledPage(extract_page(url, html), 200) for url, html in pages],
        robots=robots or {"found": True, "ai_crawlers": {"GPTBot": {"allowed": True}}},
        sitemap=sitemap or {"found": True, "url_count": 3},
        https=https,
    )


def test_audit_score_is_weighted_average_of_checks():
    outcome = evaluate(_crawl(("https://acme.com/", GOOD_HTML)), "Acme")
    checks = {c["id"]: c for c in outcome.checks}
    expected = 100 * sum(c["weight"] * c["score"] for c in outcome.checks) / sum(c["weight"] for c in outcome.checks)
    assert outcome.score == round(expected, 1)
    assert checks["titles"]["passed"] and checks["org_schema"]["passed"] and checks["faq_content"]["passed"]


def test_audit_detects_problems_with_evidence():
    robots = {"found": True, "ai_crawlers": {"GPTBot": {"allowed": False}, "ClaudeBot": {"allowed": True}}}
    good = evaluate(_crawl(("https://acme.com/", GOOD_HTML)), "Acme")
    bad = evaluate(
        _crawl(("https://acme.com/", GOOD_HTML), ("https://acme.com/x", BAD_HTML), robots=robots, sitemap={"found": False}, https=False),
        "Acme",
    )
    checks = {c["id"]: c for c in bad.checks}
    assert bad.score < good.score
    assert checks["ai_crawler_access"]["evidence"] == ["GPTBot"]
    assert checks["titles"]["evidence"] == ["https://acme.com/x"]
    assert checks["titles"]["score"] == 0.5
    assert not checks["valid_schema"]["passed"]
    assert not checks["sitemap"]["passed"] and not checks["https"]["passed"]
    codes = {i["code"] for i in bad.page_issues["https://acme.com/x"]}
    assert {"missing_title", "missing_meta_description", "missing_h1", "thin_content", "invalid_structured_data"} <= codes
    gaps = {g["topic"]: g for g in bad.content_gaps}
    assert gaps["features"]["covered"] and not gaps["pricing"]["covered"]


def test_crawler_respects_robots_and_stays_on_site():
    pages = {
        "/robots.txt": ("text/plain", "User-agent: *\nDisallow: /private\nSitemap: https://acme.com/sitemap.xml"),
        "/sitemap.xml": ("application/xml", "<urlset><url><loc>https://acme.com/pricing</loc></url><url><loc>https://acme.com/private/x</loc></url></urlset>"),
        "/": ("text/html", '<html><title>Acme home</title><a href="/about">About</a><a href="https://other.org/">x</a></html>'),
        "/pricing": ("text/html", "<html><title>Pricing</title></html>"),
        "/about": ("text/html", "<html><title>About</title></html>"),
    }
    requested = []

    def handler(request):
        requested.append(request.url.path)
        ct, body = pages.get(request.url.path, ("text/html", "nope"))
        status = 200 if request.url.path in pages else 404
        return httpx.Response(status, headers={"content-type": ct}, content=body.encode())

    fetcher = SafeFetcher(user_agent="AEOAuditBot/0.1", transport=httpx.MockTransport(handler), resolver=lambda h, p: ["93.184.216.34"])
    crawler = SiteCrawler(user_agent="AEOAuditBot/0.1", max_pages=10, fetcher=fetcher, sleep=lambda s: None)
    result = crawler.crawl("acme.com")
    urls = [p.data.url for p in result.pages]
    assert urls[0] == "https://acme.com/"
    assert "https://acme.com/pricing" in urls and "https://acme.com/about" in urls
    assert "/private/x" not in requested
    assert result.skipped_by_robots == ["https://acme.com/private/x"]
    assert result.sitemap["found"] and result.robots["found"]


# ----------------------------------------------------------------- questions
CTX = QuestionContext(brand="Acme", industry="project management software", competitors=["Globex", "Initech"], website_url="https://acme.com/")


def test_template_questions_are_deterministic_and_cover_categories():
    qs = template_questions(CTX)
    assert len(qs) == 20
    assert qs == template_questions(CTX)
    assert {q.category for q in qs} == set(CATEGORIES)
    assert all(q.source == "template" for q in qs)
    assert any("Globex" in q.text for q in qs)
    assert len({q.text for q in qs}) == 20


def test_template_questions_without_industry_or_competitors():
    qs = template_questions(QuestionContext(brand="Acme", industry=None, competitors=[], website_url="https://acme.com"))
    assert len(qs) == 20 and all("None" not in q.text for q in qs)


class FakeJSONProvider(AIProvider):
    name = "fake"

    def __init__(self, payload=None, error=None, configured=True):
        self.payload, self.error, self.configured = payload, error, configured

    def is_configured(self):
        return self.configured

    def setup_instructions(self):
        return "set FAKE_KEY"

    @property
    def model(self):
        return "fake-1"

    def answer(self, question):
        return ProviderAnswer(text="", model="fake-1")

    def complete_json(self, system, prompt, schema):
        if self.error:
            raise self.error
        return self.payload


def test_generate_questions_uses_llm_when_configured():
    payload = {"questions": [{"text": f"LLM question {i}?", "category": CATEGORIES[i % len(CATEGORIES)]} for i in range(20)]}
    qs, note = generate_questions(CTX, FakeJSONProvider(payload))
    assert note is None and len(qs) == 20 and all(q.source == "llm" for q in qs)


def test_generate_questions_tops_up_and_filters_malformed_items():
    payload = {"questions": [{"text": "Good?", "category": "pricing"}, {"text": "Bad cat", "category": "nope"}, "junk", {"text": "good?", "category": "pricing"}]}
    qs, note = generate_questions(CTX, FakeJSONProvider(payload))
    assert len(qs) == 20 and qs[0].source == "llm" and sum(q.source == "llm" for q in qs) == 1
    assert "fewer than 20" in note


def test_generate_questions_falls_back_on_error_or_missing_config():
    qs, note = generate_questions(CTX, FakeJSONProvider(error=ProviderError("rate limited")))
    assert all(q.source == "template" for q in qs) and "rate limited" in note
    qs, note = generate_questions(CTX, None)
    assert len(qs) == 20 and "No AI provider" in note


# ----------------------------------------------------------------- homepage failures & fetch details
import pytest  # noqa: E402

from app.crawler.fetcher import FetchError  # noqa: E402


def _site_crawler(routes, **kwargs):
    """Crawler whose every request is answered from `routes`: path -> (status, content-type, body)."""

    def handler(request):
        status, ct, body = routes.get(request.url.path, (404, "text/html", "<html><title>Not found</title></html>"))
        return httpx.Response(status, headers={"content-type": ct}, content=body.encode())

    fetcher = SafeFetcher(user_agent="AEOAuditBot/0.1", transport=httpx.MockTransport(handler), resolver=lambda h, p: ["93.184.216.34"])
    return SiteCrawler(user_agent="AEOAuditBot/0.1", fetcher=fetcher, sleep=lambda s: None, **kwargs)


@pytest.mark.parametrize(
    "status, code, phrase",
    [(403, "blocked", "refused access"), (401, "blocked", "refused access"), (429, "rate_limited", "rate-limiting"),
     (404, "http_error", "not found"), (503, "http_error", "server error")],
)
def test_homepage_http_errors_fail_with_specific_codes(status, code, phrase):
    crawler = _site_crawler({"/": (status, "text/html", "<html><title>Error</title></html>")})
    with pytest.raises(FetchError) as exc:
        crawler.crawl("acme.com")
    assert exc.value.code == code and exc.value.status_code == status
    assert phrase in exc.value.message


def test_bot_protection_page_is_not_treated_as_content():
    challenge = '<html><head><title>Just a moment...</title></head><body><script src="/cdn-cgi/challenge-platform/x.js"></script></body></html>'
    crawler = _site_crawler({"/": (200, "text/html", challenge)})
    with pytest.raises(FetchError) as exc:
        crawler.crawl("acme.com")
    assert exc.value.code == "bot_protection"


def test_non_html_homepage_and_robots_disallow_fail_clearly():
    crawler = _site_crawler({"/": (200, "application/pdf", "%PDF")})
    with pytest.raises(FetchError) as exc:
        crawler.crawl("acme.com")
    assert exc.value.code == "not_html"
    crawler = _site_crawler({"/robots.txt": (200, "text/plain", "User-agent: *\nDisallow: /"), "/": (200, "text/html", "<html></html>")})
    with pytest.raises(FetchError) as exc:
        crawler.crawl("acme.com")
    assert exc.value.code == "robots_disallowed"


def test_successful_fetch_returns_final_url_title_description_headings_and_text():
    def handler(request):
        if request.url.path == "/":
            return httpx.Response(301, headers={"location": "https://www.acme.com/home"})
        if request.url.path == "/home":
            return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=GOOD_HTML.encode())
        return httpx.Response(404)

    fetcher = SafeFetcher(user_agent="t", transport=httpx.MockTransport(handler), resolver=lambda h, p: ["93.184.216.34"])
    result = SiteCrawler(user_agent="t", fetcher=fetcher, sleep=lambda s: None, max_pages=1).crawl("acme.com")
    page = result.pages[0].data
    assert result.root_url == "https://www.acme.com/home"
    assert page.url == "https://www.acme.com/home"
    assert page.title.startswith("Acme")
    assert page.meta_description.startswith("Acme helps")
    assert [h["text"] for h in page.headings][:2] == ["Acme", "Features"]
    assert "word word" in page.text


def test_crawl_time_budget_stops_early_but_keeps_results():
    ticks = iter(range(0, 1000, 50))
    home = '<html><title>Acme home page</title><a href="/a">a</a><a href="/b">b</a></html>'
    crawler = _site_crawler(
        {"/": (200, "text/html", home), "/a": (200, "text/html", "<html><title>A</title></html>"), "/b": (200, "text/html", "<html></html>")},
        max_pages=10, max_seconds=60, clock=lambda: next(ticks),
    )
    result = crawler.crawl("acme.com")
    assert len(result.pages) == 2  # homepage + one page before the budget ran out
    assert "time limit" in result.stopped_early


# ----------------------------------------------------------------- JavaScript-only sites
from app.recommendations.engine import RecInput, build_recommendations  # noqa: E402

SPA_HTML = """<!doctype html><html lang="en"><head><title>acme.io</title>
<script type="module" src="/assets/index-abc.js"></script></head>
<body><div id="root"></div></body></html>"""


def test_js_shell_detection():
    page = extract_page("https://acme.io/", SPA_HTML)
    assert page.js_shell and 'id="root"' in page.js_shell_evidence
    assert not extract_page("https://acme.com/", GOOD_HTML).js_shell
    # A small static page without scripts is not an app shell
    assert not extract_page("https://example.com/", "<html><body><div id='app'></div><p>Hi</p></body></html>").js_shell
    noscript = "<html><body><noscript>You need to enable JavaScript to run this app.</noscript><script src='/a.js'></script></body></html>"
    assert extract_page("https://acme.io/", noscript).js_shell


def test_js_shell_audit_check_and_collapsed_recommendations():
    outcome = evaluate(_crawl(("https://acme.io/", SPA_HTML)), "Acme")
    check = next(c for c in outcome.checks if c["id"] == "js_rendering")
    assert not check["passed"] and check["evidence"][0].startswith("The HTML contains only 0 words")
    assert outcome.site_info["js_rendered_shell"] is True
    assert any(i["code"] == "js_rendered" for i in outcome.page_issues["https://acme.io/"])

    inp = RecInput(brand="Acme", domain="acme.io", competitors=["Globex"], audit_checks=outcome.checks,
                   content_gaps=outcome.content_gaps, js_shell_homepage=True)
    recs = build_recommendations(inp)
    assert recs[0]["priority"] == "high" and "JavaScript" in recs[0]["issue"]
    issues = " | ".join(r["issue"] for r in recs)
    for symptom in ("FAQ", "pricing", "Thin content", "comparison", "Heading structure", "No page covers"):
        assert symptom not in issues, symptom
    assert "meta description" in issues  # real <head> problems are still reported

    # Without the shell flag, the same audit reports the individual gaps
    inp.js_shell_homepage = False
    assert any("pricing" in r["issue"] for r in build_recommendations(inp))


def test_js_shell_recommendation_outranks_visibility_findings():
    outcome = evaluate(_crawl(("https://acme.io/", SPA_HTML)), "Acme")
    metrics = {"questions_tested": 2, "entities": [{"name": "Acme", "entity_type": "brand", "answers_mentioning": 0}]}
    answers = [{"question": "Is Acme good?", "category": "recommendation", "brand_mentioned": False, "website_cited": False,
                "error": None, "sources": [], "competitors_mentioned": [], "branded_question": True,
                "brand_unknown": True, "brand_unknown_evidence": "I couldn't find any information about Acme."}]
    recs = build_recommendations(RecInput(brand="Acme", domain="acme.io", competitors=[], audit_checks=outcome.checks,
                                          content_gaps=outcome.content_gaps, js_shell_homepage=True,
                                          run_metrics=metrics, answers=answers))
    assert "JavaScript" in recs[0]["issue"] and recs[0]["blocking"]
    assert any(r["key"] == "visibility:brand-unknown" for r in recs)
    assert [r["score"] for r in recs] == sorted((r["score"] for r in recs), reverse=True)


# ----------------------------------------------------------------- JavaScript rendering
RENDERED_HOME = GOOD_HTML.replace('<a href="/pricing">Pricing</a>', '<a href="/pricing">Pricing</a><a href="/about">About</a>')


class FakeRenderer:
    def __init__(self, pages):
        self.pages, self.rendered, self.closed = pages, [], False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True

    def render(self, url):
        self.rendered.append(url)
        return url, self.pages.get(urlsplit_path(url), "<html><body><p>rendered</p></body></html>")


def urlsplit_path(url):
    from urllib.parse import urlsplit

    return urlsplit(url).path or "/"


def _spa_crawler(renderer, max_render=8):
    routes = {"/": (200, "text/html", SPA_HTML), "/pricing": (200, "text/html", SPA_HTML), "/about": (200, "text/html", "<html><title>About Acme</title><body><h1>About</h1><p>" + "word " * 300 + "</p></body></html>")}
    return _site_crawler(routes, renderer_factory=lambda host: renderer, render_max_pages=max_render, max_pages=5)


def test_js_shell_pages_are_rendered_and_followed():
    renderer = FakeRenderer({"/": RENDERED_HOME, "/pricing": "<html><title>Pricing</title><body><h1>Pricing</h1><p>$10 per month</p></body></html>"})
    result = _spa_crawler(renderer).crawl("acme.com")
    home = result.pages[0].data
    assert home.rendered and home.js_shell and "empty <div" in home.js_shell_evidence
    assert home.title.startswith("Acme") and home.word_count > 300  # content measured from the render
    urls = [p.data.url for p in result.pages]
    assert "https://acme.com/pricing" in urls and "https://acme.com/about" in urls  # links found only after rendering
    about = next(p.data for p in result.pages if p.data.url.endswith("/about"))
    assert not about.rendered and not about.js_shell  # static pages aren't rendered
    assert renderer.rendered == ["https://acme.com/", "https://acme.com/pricing"] and renderer.closed
    assert result.rendered_pages == renderer.rendered


def test_render_page_limit_and_failure_fall_back_to_raw_html():
    renderer = FakeRenderer({"/": RENDERED_HOME})
    result = _spa_crawler(renderer, max_render=1).crawl("acme.com")
    pricing = next(p.data for p in result.pages if p.data.url.endswith("/pricing"))
    assert not pricing.rendered and pricing.js_shell  # over the limit: raw shell kept

    class Broken(FakeRenderer):
        def render(self, url):
            raise RuntimeError("browser crashed")

    result = _spa_crawler(Broken({})).crawl("acme.com")
    assert not result.pages[0].data.rendered and result.render_error


def test_rendered_site_keeps_blocking_js_item_but_measures_content():
    renderer = FakeRenderer({"/": RENDERED_HOME})
    crawl = _spa_crawler(renderer).crawl("acme.com")
    outcome = evaluate(crawl, "Acme")
    assert outcome.site_info["js_rendered_shell"] and outcome.site_info["homepage_rendered"]
    assert not next(c for c in outcome.checks if c["id"] == "js_rendering")["passed"]
    recs = build_recommendations(RecInput(
        brand="Acme", domain="acme.com", competitors=[], audit_checks=outcome.checks, content_gaps=outcome.content_gaps,
        js_shell_homepage=False, homepage_js_only=True,
    ))
    assert recs[0]["key"] == "crawl:js-rendering" and recs[0]["blocking"]
    assert "We rendered your pages in a browser" in recs[0]["action"]
    assert any(r["key"].startswith("content:") for r in recs)  # content now measurable, so content items appear


def test_local_template_questions_name_the_city():
    ctx = QuestionContext(brand="Gawande Krushi Kendra", industry="agricultural store", competitors=["BigHaat"],
                          website_url="https://gkk.example", city="Akola", services=["Seeds"])
    qs = template_questions(ctx)
    assert len(qs) == 20 and len({q.text for q in qs}) == 20 and {q.category for q in qs} == set(CATEGORIES)
    assert sum("Akola" in q.text for q in qs) >= 15
    assert "What is the best agricultural store in Akola?" in [q.text for q in qs]
    assert any("offer Seeds" in q.text for q in qs)
