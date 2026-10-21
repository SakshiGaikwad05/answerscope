"""Local business audit, consistency checks, and new technical checks."""

import httpx

from app.analysis.audit import evaluate, is_generic_title
from app.analysis.extract import extract_page
from app.analysis.local import evaluate_local, phone_key
from app.crawler.crawler import CrawledPage, CrawlResult, SiteCrawler
from app.crawler.fetcher import SafeFetcher

LOCAL_HTML = """<html lang="en"><head><title>Gawande Krushi Kendra - Seeds & Fertilizers in Akola</title>
<meta name="description" content="Agricultural supplies store in Akola, Maharashtra: seeds, fertilizers, pesticides and expert crop advice.">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Store","name":"Gawande Krushi Kendra",
"telephone":"+91 98765 43210","address":{"@type":"PostalAddress","streetAddress":"Station Road","addressLocality":"Akola","postalCode":"444001"},
"openingHours":"Mo-Sa 09:00-19:00"}</script></head>
<body><h1>Gawande Krushi Kendra</h1><h2>Seeds</h2><h2>Fertilizers</h2><h2>Contact us</h2>
<p>Visit us at Station Road, Akola 444001. Call <a href="tel:+919876543210">+91 98765 43210</a>.
Open Monday to Saturday, 9:00 am to 7:00 pm.</p>
<a href="https://maps.app.goo.gl/abc">Find us on Google Maps</a> <a href="https://instagram.com/gkk">Instagram</a>
<p>""" + "word " * 260 + "</p></body></html>"

PROFILE = {"brand": "Gawande Krushi Kendra", "city": "Akola", "phone": "098765 43210", "address": "Station Road, Akola 444001",
           "services": ["Seeds", "Fertilizers", "Drip irrigation"], "profile_urls": []}


def page(html=LOCAL_HTML, url="https://gkk.example/"):
    return extract_page(url, html)


def by_id(result):
    return {c["id"]: c for c in result["checks"]}


def test_phone_key_ignores_formatting_and_country_code():
    assert phone_key("+91 98765-43210") == phone_key("098765 43210") == "9876543210"
    assert phone_key("12") == ""


def test_complete_local_site_passes_with_evidence():
    r = evaluate_local([page()], PROFILE)
    c = by_id(r)
    for cid in ("local_phone", "local_city", "local_address", "local_contact_page", "local_schema", "local_hours", "local_gbp", "local_profiles"):
        assert c[cid]["status"] == "pass", (cid, c[cid])
    assert c["local_services"]["status"] == "fail" and "Drip irrigation" in c["local_services"]["detail"]
    assert r["score"] is not None and 80 < r["score"] < 100 and r["unknown"] == 0


def test_inconsistent_phone_in_structured_data_is_flagged():
    r = evaluate_local([page()], {**PROFILE, "phone": "+91 91111 22222"})
    c = by_id(r)
    assert c["local_phone"]["status"] == "fail" and "9876543210" in c["local_phone"]["evidence"][0]
    assert c["local_schema"]["status"] == "fail" and "differs from your profile" in c["local_schema"]["detail"]
    assert r["inconsistencies"]


def test_missing_information_is_unknown_not_zero():
    bare = "<html><head><title>Shop</title></head><body><p>Hello</p></body></html>"
    r = evaluate_local([page(bare)], {"brand": "Shop"})
    c = by_id(r)
    assert c["local_city"]["status"] == "unknown" and c["local_services"]["status"] == "unknown"
    assert c["local_schema"]["status"] == "fail" and c["local_gbp"]["status"] == "fail"
    # A JavaScript shell that couldn't be read: content checks are unknown rather than failed
    spa = '<html><head><title>gkk</title><script src="/a.js"></script></head><body><div id="root"></div></body></html>'
    r = evaluate_local([page(spa)], PROFILE, content_readable=False)
    c = by_id(r)
    assert c["local_phone"]["status"] == c["local_city"]["status"] == c["local_services"]["status"] == "unknown"
    assert r["unknown"] >= 4 and r["score"] is not None  # score only over what could be measured


def test_no_measurable_checks_gives_no_score():
    r = evaluate_local([], {"brand": "X"}, content_readable=False)
    measured = [c for c in r["checks"] if c["status"] != "unknown"]
    assert (r["score"] is None) == (not measured)


def test_generic_titles():
    assert is_generic_title("gkk", "gawandekrushikendra", "www.gawandekrushikendra.store")
    assert is_generic_title("Home", "Acme", "acme.com")
    assert is_generic_title("sakshii.tech", "sakshi", "www.sakshii.tech")
    assert not is_generic_title("Gawande Krushi Kendra - Seeds in Akola", "Gawande Krushi Kendra", "gkk.store")


def test_audit_includes_local_and_technical_checks():
    other = page(LOCAL_HTML.replace("Seeds & Fertilizers in Akola", "x").replace('"@type":"Store"', '"@type":"Thing"'), "https://gkk.example/about")
    crawl = CrawlResult(start_url="https://gkk.example/", root_url="https://gkk.example/",
                        pages=[CrawledPage(page(), 200), CrawledPage(page(LOCAL_HTML.replace("<head>", '<head><link rel="canonical" href="https://other.example/">'), "https://gkk.example/b"), 200)],
                        robots={"found": True, "ai_crawlers": {}}, sitemap={"found": True}, https=True,
                        link_check={"checked": 3, "broken": [{"url": "https://gkk.example/old", "status": "HTTP 404", "found_on": "https://gkk.example/"}]})
    out = evaluate(crawl, "Gawande Krushi Kendra", PROFILE)
    checks = {c["id"]: c for c in out.checks}
    assert not checks["broken_links"]["passed"] and "linked from https://gkk.example/" in checks["broken_links"]["evidence"][0]
    assert not checks["canonical_valid"]["passed"] and "other.example" in checks["canonical_valid"]["evidence"][0]
    assert not checks["title_quality"]["passed"] and "Duplicate" in checks["title_quality"]["detail"]
    assert out.site_info["local"]["score"] is not None and out.site_info["local"]["checks"]
    assert other  # constructed to make sure extraction of non-local types works


def test_crawler_checks_uncrawled_internal_links():
    pages = {
        "/": (200, '<html><title>Home page of Acme</title><a href="/ok">ok</a><a href="/missing">gone</a></html>'),
        "/ok": (200, "<html><title>OK page</title></html>"),
    }

    def handler(request):
        status, body = pages.get(request.url.path, (404, "not found"))
        return httpx.Response(status, headers={"content-type": "text/html"}, content=body.encode())

    fetcher = SafeFetcher(user_agent="t", transport=httpx.MockTransport(handler), resolver=lambda h, p: ["93.184.216.34"])
    result = SiteCrawler(user_agent="t", fetcher=fetcher, sleep=lambda s: None, max_pages=1).crawl("acme.com")
    broken = result.link_check["broken"]
    assert result.link_check["checked"] == 2
    assert [b["url"] for b in broken] == ["https://acme.com/missing"] and broken[0]["found_on"] == "https://acme.com/"


# ----------------------------------------------------------------- LocalBusiness draft + local recommendations
import json as _json

from app.fixes.generator import SiteContext, _local_business
from app.recommendations.engine import RecInput, build_recommendations


def _ctx(profile, found=None, industry="agricultural supplies store"):
    return SiteContext(brand="Gawande Krushi Kendra", website_url="https://gkk.example/", domain="gkk.example", industry=industry,
                       competitors=[], pages=[page()], site_text="", profile=profile, local_found=found or {})


def test_local_business_draft_uses_only_verified_facts():
    d = _local_business(_ctx({"city": "Akola", "region": "Maharashtra", "country": "IN", "address": "Station Road", "phone": "+91 98765 43210",
                              "opening_hours": "Mo-Sa 09:00-19:00", "service_area": "Akola district", "profile_urls": ["https://g.page/r/abc"]}))
    data = _json.loads(d.content.split(">", 1)[1].rsplit("<", 1)[0])
    assert data["@type"] == "Store" and data["telephone"] == "+91 98765 43210" and data["openingHours"] == "Mo-Sa 09:00-19:00"
    assert data["address"] == {"@type": "PostalAddress", "streetAddress": "Station Road", "addressLocality": "Akola",
                               "addressRegion": "Maharashtra", "addressCountry": "IN"}
    assert data["sameAs"] == ["https://g.page/r/abc"] and d.placeholders == [] and "telephone: your profile" in d.notes
    assert "geo" not in data and "aggregateRating" not in data  # nothing invented


def test_local_business_draft_uses_placeholders_when_unknown():
    d = _local_business(_ctx({"opening_hours": "9am to 7pm, closed Sunday"}, industry=None))
    data = _json.loads(d.content.split(">", 1)[1].rsplit("<", 1)[0])
    assert data["@type"] == "LocalBusiness" and data["telephone"].startswith("[ADD:")
    assert "9am to 7pm" in data["openingHours"] and data["openingHours"].startswith("[ADD:")
    assert {"Phone number", "Street address", "Opening hours", "Official profile URLs"} <= set(d.placeholders)


def test_local_findings_become_grouped_recommendations():
    local = evaluate_local([page("<html><head><title>gkk</title></head><body><p>Seeds</p></body></html>")],
                           {"brand": "Gawande Krushi Kendra", "city": "Akola", "phone": "+91 98765 43210"})
    recs = {r["key"]: r for r in build_recommendations(RecInput(brand="Gawande Krushi Kendra", domain="gkk.example", competitors=[],
                                                                audit_checks=[{"id": "titles", "passed": True, "score": 1}], local=local))}
    for key in ("local:phone", "local:city", "local:gbp", "local:schema", "local:complete-profile"):
        assert key in recs, key
    assert recs["local:phone"]["priority"] == "high" and recs["local:phone"]["verify"]
    assert any("Can't check" in e for e in recs["local:complete-profile"]["evidence"])
