from app.visibility.detection import EntitySpec, analyze_answer, build_aliases, extract_urls, find_mentions
from app.visibility.metrics import AnswerRecord, compute_run_metrics


def test_aliases_include_compact_form_and_domain():
    assert build_aliases("Acme Corp", "www.acme.com") == ["Acme Corp", "AcmeCorp", "acme.com"]


def test_mentions_respect_word_boundaries():
    assert find_mentions("We like Acme and ACME tools", ["Acme"])  # case-insensitive with capital
    assert not find_mentions("The acmetools package", ["Acme"])
    assert not find_mentions("Notacme is different", ["Acme"])


def test_single_word_names_require_capitalization():
    assert not find_mentions("I ate an apple today.", ["Apple"])
    assert len(find_mentions("Apple and apple.com both count.", ["Apple", "apple.com"])) == 2


def test_multi_word_names_are_case_insensitive():
    assert find_mentions("try monday.com work management", ["monday.com"])
    assert find_mentions("we use hub spot crm", ["Hub Spot"])


def test_citation_detection_uses_cited_sources_and_links_not_search_results():
    brand = EntitySpec(name="Acme", entity_type="brand", domain="acme.com")
    comp = EntitySpec(name="Globex", entity_type="competitor", domain="globex.io", competitor_id=7)
    text = "Acme is popular. Globex is cheaper, see https://www.globex.io/pricing."
    sources = [
        {"url": "https://docs.acme.com/start", "type": "cited", "title": "Acme docs"},
        {"url": "https://acme.com/about", "type": "search_result"},
    ]
    result = analyze_answer(text, sources, brand, [comp])
    assert result.brand_mentioned and result.website_cited
    by_key = {(d["entity_name"], d["kind"]): d for d in result.detections}
    assert by_key[("Acme", "citation")]["evidence"] == [
        {"type": "cited_source", "url": "https://docs.acme.com/start", "title": "Acme docs"}
    ]
    assert by_key[("Globex", "citation")]["evidence"][0]["type"] == "linked_in_answer"
    assert by_key[("Globex", "mention")]["competitor_id"] == 7
    assert "Acme is popular" in by_key[("Acme", "mention")]["evidence"][0]["text"]


def test_search_result_alone_is_not_a_citation():
    brand = EntitySpec(name="Acme", entity_type="brand", domain="acme.com")
    result = analyze_answer("No brands here.", [{"url": "https://acme.com", "type": "search_result"}], brand, [])
    assert not result.brand_mentioned and not result.website_cited


def test_lookalike_domains_do_not_count():
    brand = EntitySpec(name="Acme", entity_type="brand", domain="acme.com")
    result = analyze_answer("See https://acme.com.evil.net and https://notacme.com", [], brand, [])
    assert not result.website_cited


def test_extract_urls_strips_trailing_punctuation():
    assert extract_urls("Visit https://a.com/x. Or (https://b.com/y)") == ["https://a.com/x", "https://b.com/y"]


def _rec(cat, mentioned, cited, comps=(), error=None):
    det = {("competitor", c, "mention") for c in comps}
    if mentioned:
        det.add(("brand", "Acme", "mention"))
    if cited:
        det.add(("brand", "Acme", "citation"))
    return AnswerRecord(category=cat, error=error, brand_mentioned=mentioned, website_cited=cited, detections=det)


def test_metrics_use_only_successful_answers():
    records = [
        _rec("pricing", True, True),
        _rec("pricing", True, False, comps=["Globex"]),
        _rec("comparison", False, False, comps=["Globex"]),
        _rec("comparison", False, False),
        _rec("features", False, False, error="timeout"),
    ]
    m = compute_run_metrics(records, "Acme", ["Globex", "Initech"])
    assert m["total_questions"] == 5
    assert m["questions_tested"] == 4
    assert m["questions_failed"] == 1
    assert m["brand_mention_rate"] == 50.0
    assert m["website_citation_rate"] == 25.0
    assert m["answers_with_competitor_but_not_brand"] == 1
    ents = {e["name"]: e for e in m["entities"]}
    assert ents["Globex"]["mention_rate"] == 50.0
    assert ents["Initech"]["mention_rate"] == 0.0
    # share of voice: brand 2 of (2 + 2 + 0)
    assert ents["Acme"]["share_of_voice"] == 50.0
    cats = {c["category"]: c for c in m["by_category"]}
    assert cats["pricing"]["mention_rate"] == 100.0
    assert "features" not in cats


def test_metrics_are_none_without_successful_answers():
    m = compute_run_metrics([_rec("pricing", False, False, error="boom")], "Acme", [])
    assert m["brand_mention_rate"] is None
    assert m["website_citation_rate"] is None
    assert m["entities"][0]["share_of_voice"] is None


def test_domain_inside_url_is_a_citation_not_a_mention():
    brand = EntitySpec(name="Acme", entity_type="brand", domain="acme.com")
    result = analyze_answer("Details: https://acme.com/pricing", [], brand, [])
    assert not result.brand_mentioned and result.website_cited
    result = analyze_answer("Acme (acme.com) is good, see https://acme.com/x", [], brand, [])
    mention = next(d for d in result.detections if d["kind"] == "mention")
    assert mention["occurrences"] == 2


# ----------------------------------------------------------------- branded questions & "AI doesn't know you"
from app.visibility.detection import detect_brand_unknown, question_names_brand  # noqa: E402


def test_question_names_brand():
    brand = EntitySpec(name="Acme", entity_type="brand", domain="acme.com")
    assert question_names_brand("Is acme.com a good choice?", brand)
    assert question_names_brand("Would you recommend Acme's services?", brand)
    assert not question_names_brand("What are the best project tools?", brand)


def test_detect_brand_unknown_flags_not_found_answers_with_evidence():
    brand = EntitySpec(name="Acme", entity_type="brand", domain="acme.com")
    for text in [
        "I couldn't find any reliable information on acme.com, so I can't say.",
        "I'm not familiar with Acme as a software vendor.",
        "My searches didn't turn up the Acme site at all.",
        "I couldn't find anything about Acme.",
    ]:
        evidence = detect_brand_unknown(text, brand)
        assert evidence and len(evidence) < 400, text


def test_detect_brand_unknown_ignores_answers_that_know_the_brand():
    brand = EntitySpec(name="Acme", entity_type="brand", domain="acme.com")
    assert detect_brand_unknown("Acme is a strong pick. I couldn't find any pricing for Acme, but plans start at $10.", brand) is None
    assert detect_brand_unknown("Top tools: Globex, Initech. I couldn't find any information about Hooli.", brand) is None
    assert detect_brand_unknown("I couldn't find any information about Hooli.", brand) is None  # brand not mentioned


def test_metrics_split_branded_unbranded_and_exclude_unknown_mentions():
    def rec(branded, mentioned, unknown=False, error=None):
        det = {("brand", "Acme", "mention")} if mentioned else set()
        return AnswerRecord(category="pricing", error=error, brand_mentioned=mentioned, website_cited=False,
                            detections=det, branded=branded, brand_unknown=unknown)

    records = [
        rec(False, True),            # unprompted mention
        rec(False, False),
        rec(False, False),
        rec(False, False),
        rec(True, True),             # branded, AI knows it
        rec(True, True, unknown=True),  # branded, "couldn't find Acme" -> not a mention
        rec(True, True, unknown=True),
        rec(True, False, error="timeout"),
    ]
    m = compute_run_metrics(records, "Acme", [])
    assert m["unbranded_questions"] == 4 and m["unbranded_mentions"] == 1 and m["unbranded_mention_rate"] == 25.0
    assert m["branded_questions"] == 3 and m["branded_known"] == 1 and m["branded_unknown"] == 2
    assert m["brand_unknown_answers"] == 2
    assert m["brand_mentions"] == 2  # unknown answers don't count
    assert m["brand_mention_rate"] == round(100 * 2 / 7, 1)


def test_gemini_redirect_citation_matches_by_domain_title():
    brand = EntitySpec(name="Gawande Krushi Kendra", entity_type="brand", domain="gawandekrushikendra.store")
    redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc"
    r = analyze_answer("Try Gawande Krushi Kendra.", [{"url": redirect, "title": "gawandekrushikendra.store", "type": "cited"}], brand, [])
    assert r.website_cited
    r = analyze_answer("Try Gawande Krushi Kendra.", [{"url": redirect, "title": "Some article about stores", "type": "cited"}], brand, [])
    assert not r.website_cited
    r = analyze_answer("x", [{"url": redirect, "title": "gawandekrushikendra.store.evil.com", "type": "cited"}], brand, [])
    assert not r.website_cited
