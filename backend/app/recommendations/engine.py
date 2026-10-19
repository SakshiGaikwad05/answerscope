"""Evidence-based recommendations from the latest audit and visibility run.

Each rule fires only when the collected data supports it, and attaches the data
as evidence. Wording avoids promising outcomes: changes can improve the odds of
being understood and cited, never guarantee it.

Every recommendation has a stable `key` (so its status survives re-audits), an
impact (`priority`), `effort`, `confidence`, and a `verify` step that says how
a retest will show whether the fix worked.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from app.visibility.detection import domain_of

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
IMPACT_POINTS = {"high": 3.0, "medium": 2.0, "low": 1.0}
CONFIDENCE_FACTOR = {"high": 1.0, "medium": 0.75, "low": 0.5}
EFFORT_DIVISOR = {"low": 1.0, "medium": 1.5, "high": 2.5}
# Checks that fail only because a JavaScript-only page has no HTML content
JS_SHELL_SYMPTOM_CHECKS = {"content_depth", "h1", "brand_on_homepage", "faq_content", "faq_schema", "topic_coverage"}
# Recommendation keys that can't be evaluated while the homepage is an empty JavaScript shell
JS_SHELL_UNEVALUATED_PREFIXES = ("content:", "structure:", "meta:brand-homepage", "schema:faq")
UNBRANDED_CATEGORIES = {"best_in_category", "use_case", "beginner", "features"}


@dataclass
class RecInput:
    brand: str
    domain: str
    competitors: list[str]
    audit_checks: list[dict] | None = None
    content_gaps: list[dict] | None = None
    page_issues: dict[str, list[dict]] = field(default_factory=dict)
    run_metrics: dict | None = None
    # answers: {question, category, brand_mentioned, website_cited, error, sources, competitors_mentioned: [names]}
    answers: list[dict] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    # Homepage content is unmeasurable: an empty JavaScript shell that couldn't be rendered
    js_shell_homepage: bool = False
    # Homepage HTML is an empty JavaScript shell (true even when we rendered it in a browser)
    homepage_js_only: bool = False


def score_for(priority: str, confidence: str, effort: str, blocking: bool = False) -> float:
    """Ordering score: impact × confidence ÷ effort. Blocking root causes always come first."""
    base = IMPACT_POINTS[priority] * CONFIDENCE_FACTOR[confidence] / EFFORT_DIVISOR[effort]
    return round(base + (10.0 if blocking else 0.0), 3)


def _rec(key, category, priority, issue, why, action, evidence, source, *, effort, confidence, verify, blocking=False) -> dict:
    return {
        "key": key,
        "category": category,
        "priority": priority,  # impact
        "effort": effort,
        "confidence": confidence,
        "blocking": blocking,
        "score": score_for(priority, confidence, effort, blocking),
        "issue": issue,
        "why_it_matters": why,
        "action": action,
        "verify": verify,
        "evidence": [e for e in evidence if e][:12],
        "source": source,  # "audit" | "visibility"
    }


def _check(checks: list[dict], cid: str) -> dict | None:
    return next((c for c in checks if c["id"] == cid), None)


def _audit_verify(check_label: str) -> str:
    return f"Re-run the website audit. The check \"{check_label}\" should pass."


def audit_recommendations(inp: RecInput) -> list[dict]:
    checks = inp.audit_checks or []
    recs: list[dict] = []
    if not checks:
        return recs

    def failing(cid):
        c = _check(checks, cid)
        if inp.js_shell_homepage and cid in JS_SHELL_SYMPTOM_CHECKS:
            return None  # an artifact of the empty shell; covered by the JavaScript recommendation
        return c if c and not c["passed"] else None

    if (inp.js_shell_homepage or inp.homepage_js_only) and (c := _check(checks, "js_rendering")):
        measured = (
            "We rendered your pages in a browser to analyze their content, so the other recommendations reflect what "
            "visitors see, but AI crawlers still receive the empty shell."
            if not inp.js_shell_homepage else
            "Content checks (word count, headings, FAQ, topic coverage) were left out of these recommendations because "
            "they can't be measured until content is in the HTML."
        )
        recs.append(_rec(
            "crawl:js-rendering", "crawlability", "high",
            "Your site's content only appears after JavaScript runs, so crawlers see an empty page.",
            "Most AI crawlers (GPTBot, ClaudeBot, PerplexityBot) and some search crawlers don't run JavaScript. They "
            "receive an empty app shell: no text, no headings and no links to your other pages. To them your site "
            "has no content to understand, cite or recommend.",
            "Serve real HTML: pre-render or statically generate your pages (e.g. Next.js, Astro, Vite SSG or a "
            "prerendering service) so each page's text, headings and links are in the HTML the server sends. Then "
            "re-run this audit. " + measured,
            c["evidence"], "audit", effort="high", confidence="high", blocking=True,
            verify="Re-run the website audit. \"Content is visible without JavaScript\" should pass and the homepage "
            "should show a real word count, headings and links to your other pages.",
        ))
    elif c := failing("js_rendering"):
        recs.append(_rec(
            "crawl:js-rendering-pages", "crawlability", "medium", f"Some pages only render their content with JavaScript: {c['detail']}",
            "Crawlers that don't run JavaScript see these pages as empty.",
            "Pre-render or server-render these pages so their content is in the HTML.",
            c["evidence"], "audit", effort="medium", confidence="high", verify=_audit_verify(c["label"]),
        ))

    if c := failing("ai_crawler_access"):
        recs.append(_rec(
            "crawl:ai-crawlers-blocked", "crawlability", "high",
            f"robots.txt blocks AI crawlers: {', '.join(c['evidence'])}.",
            "Answer engines generally cannot read or cite pages their crawlers are blocked from. "
            "Blocking training crawlers is a legitimate choice, but blocking search/answer crawlers limits visibility.",
            "Review your robots.txt. If you want to appear in AI answers, allow the search-oriented agents "
            "(e.g. OAI-SearchBot, Claude-SearchBot, PerplexityBot) even if you keep training crawlers blocked.",
            [f"Blocked agent: {a}" for a in c["evidence"]], "audit", effort="low", confidence="high",
            verify=_audit_verify(c["label"]),
        ))
    if c := failing("indexable"):
        recs.append(_rec(
            "crawl:noindex", "crawlability", "high", "Some pages are marked noindex.",
            "Pages excluded from search indexes are much less likely to be found by answer engines that rely on them.",
            "Remove the noindex directive from pages you want to be discoverable.",
            c["evidence"], "audit", effort="low", confidence="high", verify=_audit_verify(c["label"]),
        ))
    if c := failing("https"):
        recs.append(_rec("crawl:https", "crawlability", "high", "The site is not served over HTTPS.",
                         "HTTPS is a baseline trust signal for search engines and users.",
                         "Serve all pages over HTTPS and redirect HTTP to HTTPS.", c["evidence"], "audit",
                         effort="medium", confidence="high", verify=_audit_verify(c["label"])))
    for cid, label, key in (("titles", "page titles", "meta:titles"), ("meta_descriptions", "meta descriptions", "meta:descriptions")):
        if c := failing(cid):
            examples = []
            for url in c["evidence"][:6]:
                code_part = "title" if cid == "titles" else "description"
                msgs = [i["message"] for i in inp.page_issues.get(url, []) if code_part in i["code"]]
                examples.append(f"{url} — {msgs[0]}" if msgs else url)
            recs.append(_rec(
                key, "metadata", "high" if c["score"] < 0.5 else "medium",
                f"Missing or poorly sized {label}: {c['detail']}",
                f"Clear {label} help crawlers and models understand what each page is about and when it is relevant.",
                f"Write a unique, descriptive {label[:-1]} for each important page that names {inp.brand} and the page's topic.",
                examples, "audit", effort="low", confidence="high", verify=_audit_verify(c["label"]),
            ))
    if c := failing("faq_content"):
        sample = inp.questions[:5] or [g["example_question"] for g in (inp.content_gaps or [])][:5]
        recs.append(_rec(
            "content:faq", "content", "high", "No FAQ-style content was found on the crawled pages.",
            "Customers ask AI assistants direct questions. Pages with clear question-and-answer content are easy for models to quote.",
            f"Create an FAQ page (or FAQ sections on key pages) that directly answers the questions customers ask about {inp.brand}, "
            "with short factual answers. Mark it up with FAQPage schema where appropriate.",
            [f"Question to answer: {q}" for q in sample], "audit", effort="medium", confidence="medium",
            verify=_audit_verify(c["label"]) + " Then re-run the visibility test with the same questions.",
        ))
    if c := failing("faq_schema"):
        recs.append(_rec("schema:faq", "structured_data", "low", "FAQ content has no FAQPage structured data.",
                         "Markup makes the question/answer pairs explicit to machines.",
                         "Add FAQPage JSON-LD that mirrors the visible questions and answers exactly.", c["evidence"], "audit",
                         effort="low", confidence="high", verify=_audit_verify(c["label"])))
    if c := failing("org_schema"):
        recs.append(_rec(
            "schema:organization", "structured_data", "medium", "No Organization / Product structured data was found.",
            "Entity markup states your official name, URL, logo and profiles in a machine-readable form, helping models connect your brand to your website.",
            f"Add Organization JSON-LD on the homepage (name \"{inp.brand}\", url, logo, sameAs links to official profiles) "
            "and Product or SoftwareApplication markup on product pages. Validate it with a schema validator.",
            [f"Schema types found: {', '.join(c['evidence']) or 'none'}"], "audit", effort="low", confidence="high",
            verify=_audit_verify(c["label"]),
        ))
    if c := failing("valid_schema"):
        recs.append(_rec("schema:invalid", "structured_data", "medium", "Some JSON-LD blocks fail to parse.",
                         "Invalid structured data is ignored by parsers.",
                         "Fix the JSON syntax of these blocks and re-validate.", c["evidence"], "audit",
                         effort="low", confidence="high", verify=_audit_verify(c["label"])))
    if c := failing("sitemap"):
        recs.append(_rec("crawl:sitemap", "crawlability", "medium", "No XML sitemap was found.",
                         "Sitemaps help crawlers discover all important pages, including new ones.",
                         "Publish /sitemap.xml listing your important pages and reference it from robots.txt.", [], "audit",
                         effort="low", confidence="high", verify=_audit_verify(c["label"])))
    if c := failing("brand_on_homepage"):
        recs.append(_rec("meta:brand-homepage", "metadata", "medium", f"\"{inp.brand}\" is not in the homepage title or H1.",
                         "Consistently pairing your brand name with your domain helps models associate the two.",
                         f"Include \"{inp.brand}\" in the homepage title and main heading, alongside what you do.", c["evidence"], "audit",
                         effort="low", confidence="high", verify=_audit_verify(c["label"])))
    if (c := failing("content_depth")) and c["score"] < 0.7:
        recs.append(_rec("content:thin", "content", "medium", f"Thin content: {c['detail']}",
                         "Short pages give models little factual material to draw on. If content is rendered only by JavaScript, crawlers may also see it as thin.",
                         "Expand key pages with specific facts (who it's for, features, pricing, limits, examples). Make sure core content is present in the HTML.",
                         c["evidence"], "audit", effort="medium", confidence="medium", verify=_audit_verify(c["label"])))
    if (c := failing("h1")) and c["score"] < 0.7:
        recs.append(_rec("structure:headings", "structure", "low", f"Heading structure issues: {c['detail']}",
                         "A single clear H1 per page signals its main topic.",
                         "Give each page one descriptive H1 and organize sections with H2/H3.", c["evidence"], "audit",
                         effort="low", confidence="high", verify=_audit_verify(c["label"])))
    if c := failing("robots_txt"):
        recs.append(_rec("crawl:robots-txt", "crawlability", "low", "No robots.txt file was found.",
                         "Without robots.txt, crawlers assume everything is allowed, which is fine, but you lose a place to point to your sitemap.",
                         "Add a robots.txt that references your sitemap and states your crawler policy explicitly.", [], "audit",
                         effort="low", confidence="high", verify=_audit_verify(c["label"])))

    # Topic gaps (not measurable while the homepage is an empty JavaScript shell)
    comps = inp.competitors
    gap_verify = "Re-run the website audit: this topic should show as covered under \"Questions your site answers\"."
    for gap in [] if inp.js_shell_homepage else inp.content_gaps or []:
        if gap["covered"]:
            continue
        topic = gap["topic"]
        if topic == "comparison":
            target = _top_competitor(inp) or (comps[0] if comps else None)
            if target:
                recs.append(_rec(
                    f"content:comparison:{target.lower()}", "content", "high", f"No comparison page found (e.g. {inp.brand} vs {target}).",
                    "People ask AI assistants to compare options. Without a page that compares you, models rely entirely on third-party descriptions.",
                    f"Publish a fair, factual \"{inp.brand} vs {target}\" page with a feature/pricing table and clear guidance on who each option suits.",
                    [f"Example question: {inp.brand} vs {target}: which is better?"] + _competitor_evidence(inp, target), "audit",
                    effort="medium", confidence="medium",
                    verify=gap_verify + f" Then re-run the visibility test and check answers to comparison questions about {target}.",
                ))
            else:
                recs.append(_rec("content:comparison", "content", "medium", "No comparison content found.",
                                 "Comparison questions are common in AI search; models need material to compare you fairly.",
                                 f"Add a page explaining how {inp.brand} differs from typical alternatives.",
                                 [gap["example_question"]], "audit", effort="medium", confidence="medium", verify=gap_verify))
        elif topic == "pricing":
            recs.append(_rec("content:pricing", "content", "high", "No pricing information was found on the crawled pages.",
                             "Pricing questions are among the most common purchase questions. Without an official source, AI answers may be vague or outdated.",
                             "Publish a crawlable pricing page (plans, what's included, free trial/plan), or explain how pricing works if it is quote-based.",
                             [gap["example_question"]], "audit", effort="medium", confidence="medium", verify=gap_verify))
        else:
            priority = "medium" if topic in {"alternatives", "use_cases", "features"} else "low"
            if topic == "faq" and _check(checks, "faq_content") and not _check(checks, "faq_content")["passed"]:
                continue  # covered by the FAQ recommendation
            recs.append(_rec(f"content:topic:{topic}", "content", priority, f"No page covers: {gap['label']}.",
                             "Models can only draw on your site for questions it actually answers.",
                             f"Add a clear section or page that answers \"{gap['example_question']}\"",
                             [gap["example_question"]], "audit", effort="medium", confidence="medium", verify=gap_verify))
    return recs


def _top_competitor(inp: RecInput) -> str | None:
    if not inp.run_metrics:
        return None
    comps = [e for e in inp.run_metrics.get("entities", []) if e["entity_type"] == "competitor" and e["answers_mentioning"] > 0]
    if not comps:
        return None
    return max(comps, key=lambda e: e["answers_mentioning"])["name"]


def _competitor_evidence(inp: RecInput, competitor: str) -> list[str]:
    if not inp.run_metrics:
        return []
    for e in inp.run_metrics.get("entities", []):
        if e["name"] == competitor and e["entity_type"] == "competitor":
            return [f"{competitor} was mentioned in {e['answers_mentioning']} of {inp.run_metrics['questions_tested']} tested answers"]
    return []


def visibility_recommendations(inp: RecInput) -> list[dict]:
    m = inp.run_metrics
    if not m or not m.get("questions_tested"):
        return []
    recs: list[dict] = []
    tested = [a for a in inp.answers if not a.get("error")]
    n = m["questions_tested"]
    brand = next(e for e in m["entities"] if e["entity_type"] == "brand")
    retest = "Re-run the visibility test with the same questions and model, then compare runs."

    unknown = [a for a in tested if a.get("brand_unknown")]
    if unknown:
        branded_total = sum(1 for a in tested if a.get("branded_question"))
        recs.append(_rec(
            "visibility:brand-unknown", "visibility", "high",
            f"AI answers say they can't find information about {inp.brand} "
            f"({len(unknown)} answer{'s' if len(unknown) != 1 else ''}"
            + (f", including {sum(1 for a in unknown if a.get('branded_question'))} of {branded_total} questions that name you" if branded_total else "")
            + ").",
            "Even when asked about you by name, the AI couldn't find reliable information. It can't recommend or describe "
            "a brand it can't find, so this usually has to be fixed before other visibility work pays off.",
            "Make sure your site can be crawled and indexed: serve real HTML content (not only JavaScript), publish a "
            "sitemap.xml, submit the site to Google Search Console and Bing Webmaster Tools, and use your brand name "
            "consistently in your page titles and headings. Profiles on reputable third-party sites (directories, "
            "LinkedIn, review sites) help models confirm who you are. No change guarantees inclusion.",
            [f"\"{a['question']}\" → {a['brand_unknown_evidence']}" for a in unknown[:5]],
            "visibility", effort="high", confidence="high" if len(unknown) >= 3 else "medium",
            verify=retest + f" Answers to questions that name {inp.brand} should stop saying the AI can't find you. "
            "Search indexes can take days to weeks to pick up changes.",
        ))

    unbranded = [
        a for a in tested
        if a["category"] in UNBRANDED_CATEGORIES
        and not a.get("branded_question", inp.brand.lower() in a["question"].lower())
    ]
    unbranded_hits = [a for a in unbranded if a["brand_mentioned"]]
    if unbranded and len(unbranded_hits) / len(unbranded) < 0.3:
        missed = [a for a in unbranded if not a["brand_mentioned"]]
        recs.append(_rec(
            "visibility:unprompted", "visibility", "high",
            f"{inp.brand} rarely appears in answers to general category questions "
            f"({len(unbranded_hits)} of {len(unbranded)} unbranded questions).",
            "These are the questions where new customers discover options. If you are absent, they are shown competitors instead.",
            "Publish authoritative category content (what the product does, who it is for, how it compares) on your site, "
            "and make sure it is crawlable. Being described accurately on reputable third-party sites (reviews, directories, "
            "industry publications) can also help. No change guarantees inclusion.",
            [f"Not mentioned: \"{a['question']}\"" + (f" (mentioned instead: {', '.join(a['competitors_mentioned'])})" if a["competitors_mentioned"] else "") for a in missed[:6]],
            "visibility", effort="high", confidence="medium",
            verify=retest + " Track the unprompted mention rate. A single run is a small sample, so look for a consistent change across runs.",
        ))

    for comp in [e for e in m["entities"] if e["entity_type"] == "competitor"]:
        if comp["answers_mentioning"] > brand["answers_mentioning"] and comp["answers_mentioning"] >= 2:
            examples = [a["question"] for a in tested if comp["name"] in a["competitors_mentioned"] and not a["brand_mentioned"]][:5]
            recs.append(_rec(
                f"competitors:{comp['name'].lower()}", "competitors", "high",
                f"{comp['name']} is mentioned more often than {inp.brand} "
                f"({comp['answers_mentioning']} vs {brand['answers_mentioning']} of {n} answers).",
                "When a competitor dominates AI answers for your category, prospects may never hear about you.",
                f"Create a detailed, honest \"{inp.brand} vs {comp['name']}\" comparison page and strengthen pages for the "
                f"use cases where {comp['name']} is recommended instead of you.",
                [f"{comp['name']} mentioned, {inp.brand} not: \"{q}\"" for q in examples],
                "visibility", effort="medium", confidence="medium",
                verify=retest + f" Compare how often {inp.brand} and {comp['name']} are mentioned on the same questions.",
            ))

    mentioned_not_cited = [a for a in tested if a["brand_mentioned"] and not a["website_cited"]]
    if brand["answers_mentioning"] and len(mentioned_not_cited) / brand["answers_mentioning"] >= 0.5:
        cited_domains = Counter(
            d for a in mentioned_not_cited for s in a.get("sources", []) if s.get("type") == "cited" and (d := domain_of(s.get("url")))
        )
        recs.append(_rec(
            "citations:other-sources", "citations", "medium",
            f"AI answers mention {inp.brand} but usually cite other websites "
            f"({len(mentioned_not_cited)} of {brand['answers_mentioning']} answers that mention you don't cite your site).",
            "Citations send traffic and signal which sources the model trusts for facts about you.",
            "Make sure your site has clear, specific, up-to-date pages for the facts these answers cover (pricing, features, "
            "comparisons) so they are a credible source to cite. Review the sources cited instead; inaccurate third-party "
            "information is worth correcting at the source.",
            [f"Cited instead: {d} ({c}×)" for d, c in cited_domains.most_common(6)]
            + [f"Mentioned but not cited: \"{a['question']}\"" for a in mentioned_not_cited[:3]],
            "visibility", effort="medium", confidence="medium", verify=retest + " Track the website citation rate.",
        ))

    factual = [a for a in tested if a["category"] in {"pricing", "features"} and a["brand_mentioned"]]
    if factual:
        recs.append(_rec(
            "consistency:facts", "consistency", "medium",
            f"{len(factual)} AI answers make claims about {inp.brand}'s pricing or features.",
            "Models can repeat outdated or inconsistent facts. Keeping the same facts consistent across your own pages makes accurate answers more likely.",
            "Read these answers (Results tab) and check them against your current pricing and feature pages. Fix any inconsistencies "
            "across your site, and update third-party listings that contradict it.",
            [f"Check answer to: \"{a['question']}\"" for a in factual[:6]],
            "visibility", effort="low", confidence="medium",
            verify=retest + " Read the new answers to the pricing and feature questions and confirm the facts match your site.",
        ))
    failed = m.get("questions_failed", 0)
    if failed:
        recs.append(_rec(
            "data:failed-questions", "data_quality", "low", f"{failed} question(s) failed during the last visibility run.",
            "Metrics are computed only from successful answers, so failed questions reduce the sample size.",
            "Re-run the visibility test later; failures are often rate limits or timeouts.", [], "visibility",
            effort="low", confidence="high", verify="The next visibility run should have no failed questions.",
        ))
    return recs


def is_evaluated(key: str, inp: RecInput) -> bool:
    """Whether the latest data could have produced this recommendation.

    Used so a recommendation is only marked "no longer detected" when the data
    that would detect it was actually checked (not, for example, skipped because
    the homepage is a JavaScript shell or no visibility run exists yet).
    """
    source_is_visibility = key.startswith(("visibility:", "competitors:", "citations:", "consistency:", "data:"))
    if source_is_visibility:
        return bool(inp.run_metrics and inp.run_metrics.get("questions_tested"))
    if not inp.audit_checks:
        return False
    if inp.js_shell_homepage and key.startswith(JS_SHELL_UNEVALUATED_PREFIXES):
        return False
    return True


def build_recommendations(inp: RecInput) -> list[dict]:
    recs = visibility_recommendations(inp) + audit_recommendations(inp)
    out, seen = [], set()
    # Highest score first: blocking root causes, then impact × confidence ÷ effort.
    for r in sorted(recs, key=lambda r: (-r["score"], PRIORITY_ORDER[r["priority"]])):
        if r["key"] in seen:
            continue
        seen.add(r["key"])
        out.append(r)
    return out
