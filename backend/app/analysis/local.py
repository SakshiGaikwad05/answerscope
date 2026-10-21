"""Local business checks: is the business's key information on its own website, and consistent?

Compares the owner's profile (city, phone, address, hours, services, official profiles)
with what the crawl actually found. Each check is "pass", "fail" or "unknown":
"unknown" means there was nothing to compare against (e.g. no city on file, or the
site's content couldn't be read) and it is excluded from the local score rather than
counted as zero.
"""

from __future__ import annotations

import re

from app.analysis.extract import PageData

_DAYS = re.compile(r"\b(mon(day)?|tue(s(day)?)?|wed(nesday)?|thu(rs(day)?)?|fri(day)?|sat(urday)?|sun(day)?)\b", re.I)
_TIME = re.compile(r"\b\d{1,2}(:\d{2})?\s?(am|pm)\b|\b\d{1,2}:\d{2}\b", re.I)
_PHONE_CANDIDATE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
GBP_HINTS = ("google.com/maps", "maps.google.", "g.page", "goo.gl/maps", "maps.app.goo.gl", "business.google.com", "business.site")


def digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def phone_key(s: str | None) -> str:
    """Compare phone numbers by their last 10 digits (ignores country code and formatting)."""
    d = digits(s)
    return d[-10:] if len(d) >= 7 else ""


def _check(cid, label, status, detail, why, weight=1, evidence=None, fix_hint=None) -> dict:
    return {"id": cid, "label": label, "status": status, "passed": status == "pass", "detail": detail, "why": why,
            "weight": weight, "evidence": [e for e in (evidence or []) if e][:10], "fix_hint": fix_hint}


def evaluate_local(pages: list[PageData], profile: dict, *, content_readable: bool = True) -> dict:
    brand = profile.get("brand") or ""
    city = profile.get("city")
    service_area = profile.get("service_area")
    phone = profile.get("phone")
    address = profile.get("address")
    hours = profile.get("opening_hours")
    services = profile.get("services") or []
    profile_urls = profile.get("profile_urls") or []

    all_text = "\n".join(" ".join(filter(None, [p.title, p.meta_description, " ".join(h["text"] for h in p.headings), p.text])) for p in pages)
    text_lower = all_text.lower()
    text_digits = digits(all_text)
    schema_nodes = [n | {"page": p.url} for p in pages for n in p.local_schema]
    tel_links = sorted({t for p in pages for t in p.tel_links})
    site_profiles = sorted({l for p in pages for l in p.profile_links})
    checks: list[dict] = []
    unreadable = "Your pages' content couldn't be read (JavaScript-only site), so this can't be checked yet."

    def pages_mentioning(term: str) -> list[str]:
        rx = re.compile(r"(?<![\w])" + re.escape(term.lower()) + r"(?![\w])")
        return [p.url for p in pages if rx.search(" ".join([p.title or "", p.meta_description or "", p.text or ""]).lower())]

    # 1. Phone number
    found_keys = {phone_key(t) for t in tel_links} | {phone_key(n.get("telephone")) for n in schema_nodes if n.get("telephone")}
    found_keys |= {phone_key(m) for m in _PHONE_CANDIDATE.findall(all_text) if len(digits(m)) >= 10}
    found_keys.discard("")
    if phone:
        key = phone_key(phone)
        if key and key in found_keys:
            checks.append(_check("local_phone", "Phone number is on the website", "pass", f"{phone} appears on your site.",
                                 "AI assistants and search engines read contact details from your site to describe and recommend you.", 3,
                                 [f"tel: links: {', '.join(tel_links)}" if tel_links else None]))
        elif not content_readable:
            checks.append(_check("local_phone", "Phone number is on the website", "unknown", unreadable, "", 3))
        else:
            checks.append(_check("local_phone", "Phone number is on the website", "fail", f"{phone} (from your profile) wasn't found on any crawled page.",
                                 "If your phone number isn't on your own site, AI assistants can't confirm how to contact you.", 3,
                                 [f"Other numbers found: {', '.join(sorted(found_keys))}" if found_keys else "No phone numbers found on the site"],
                                 "Show the phone number as text in the header or footer of every page, as a tel: link."))
    elif found_keys:
        checks.append(_check("local_phone", "Phone number is on the website", "pass", f"Found on the site: {', '.join(sorted(found_keys))}. Add it to your project profile to check consistency.",
                             "AI assistants read contact details from your site.", 3))
    else:
        checks.append(_check("local_phone", "Phone number is on the website", "unknown" if not content_readable else "fail",
                             unreadable if not content_readable else "No phone number was found on the site, and none is on your profile.",
                             "A visible phone number is basic, verifiable business information.", 3))

    # 2. City / service area
    if not city and not service_area:
        checks.append(_check("local_city", "Your city or service area is mentioned", "unknown", "Add your city to the project profile to check this.",
                             "Local questions name a place; your site needs to say where you operate.", 3))
    elif not content_readable:
        checks.append(_check("local_city", "Your city or service area is mentioned", "unknown", unreadable, "", 3))
    else:
        hits = pages_mentioning(city) if city else []
        area_hits = pages_mentioning(service_area) if service_area else []
        ok = bool(hits or area_hits)
        checks.append(_check("local_city", "Your city or service area is mentioned", "pass" if ok else "fail",
                             f"'{city or service_area}' appears on {len(set(hits + area_hits))} crawled page(s)." if ok
                             else f"'{city or service_area}' doesn't appear on any crawled page.",
                             "When someone asks for a business 'in " + (city or "your city") + "', AI answers favour sources that clearly state that location.", 3,
                             (hits + area_hits)[:5], "Mention your city and service area in the homepage title, headings and contact details."))

    # 3. Address
    if address:
        tokens = [t for t in re.findall(r"\d{5,6}|[A-Za-z]{4,}", address) if t.lower() not in {"road", "street", "near", "india", "opposite"}]
        present = [t for t in tokens if t.lower() in text_lower]
        if not content_readable:
            checks.append(_check("local_address", "Address is on the website", "unknown", unreadable, "", 2))
        else:
            ok = bool(tokens) and len(present) >= max(1, len(tokens) // 2)
            checks.append(_check("local_address", "Address is on the website", "pass" if ok else "fail",
                                 "Your address appears on the site." if ok else "Your address (from your profile) wasn't found on the site.",
                                 "A full, consistent address helps maps, search engines and AI assistants place your business.", 2,
                                 [f"Matched: {', '.join(present)}" if present else None], "Add your full address to the contact page and footer."))
    else:
        found = next((n["address"] for n in schema_nodes if n.get("address")), None)
        checks.append(_check("local_address", "Address is on the website", "pass" if found else "unknown",
                             f"Found in structured data: {found}" if found else "Add your address to the project profile to check this.",
                             "A consistent address helps place your business.", 2))

    # 4. Contact page
    contact = [p.url for p in pages if re.search(r"contact|reach-us|visit|location", p.url.lower())
               or any(re.search(r"\bcontact\b|\bvisit us\b|\bfind us\b", h["text"], re.I) for h in p.headings)]
    checks.append(_check("local_contact_page", "Has a contact / location page", "pass" if contact else ("unknown" if not content_readable else "fail"),
                         f"Found: {', '.join(contact[:3])}" if contact else (unreadable if not content_readable else "No contact or location page was found."),
                         "A dedicated contact page is where crawlers and people look for your address, phone and hours.", 2, contact[:3],
                         "Create a /contact page with address, phone, hours, a map link and directions."))

    # 5. LocalBusiness structured data (+ consistency)
    if schema_nodes:
        node = schema_nodes[0]
        problems = []
        if phone and node.get("telephone") and phone_key(node["telephone"]) != phone_key(phone):
            problems.append(f"Structured data phone {node['telephone']} differs from your profile ({phone})")
        if brand and node.get("name") and brand.lower() not in str(node["name"]).lower() and str(node["name"]).lower() not in brand.lower():
            problems.append(f"Structured data name '{node['name']}' differs from '{brand}'")
        if city and node.get("address") and city.lower() not in str(node["address"]).lower():
            problems.append(f"Structured data address '{node['address']}' doesn't include {city}")
        checks.append(_check("local_schema", "LocalBusiness structured data is present and consistent", "fail" if problems else "pass",
                             "; ".join(problems) if problems else f"{node['type']} markup found on {node['page']}.",
                             "Structured data states your official name, address and phone in a machine-readable way.", 2,
                             problems or [node["page"]], "Make the structured data match your real business details exactly."))
    else:
        checks.append(_check("local_schema", "LocalBusiness structured data is present and consistent", "fail",
                             "No LocalBusiness (or more specific type) structured data was found.",
                             "Structured data states your official name, address and phone in a machine-readable way.", 2, [],
                             "Add LocalBusiness JSON-LD to your homepage (a draft is available in the Action plan)."))

    # 6. Opening hours
    has_hours_text = bool(_DAYS.search(all_text) and _TIME.search(all_text))
    if any(n.get("has_hours") for n in schema_nodes) or has_hours_text:
        checks.append(_check("local_hours", "Opening hours are published", "pass", "Opening hours were found on the site.",
                             "Assistants are often asked whether a business is open; published hours let them answer.", 1))
    else:
        checks.append(_check("local_hours", "Opening hours are published", "unknown" if not content_readable else "fail",
                             unreadable if not content_readable else ("Your hours (" + hours + ") aren't shown on the site." if hours else "No opening hours were found on the site."),
                             "Assistants are often asked whether a business is open; published hours let them answer.", 1, [],
                             "Show opening hours on the contact page and in your Google Business Profile."))

    # 7. Google Business Profile / official profiles
    gbp_on_profile = [u for u in profile_urls if any(h in u for h in GBP_HINTS)]
    gbp_on_site = [u for u in site_profiles if any(h in u for h in GBP_HINTS)]
    checks.append(_check("local_gbp", "Google Business Profile is set up and linked", "pass" if (gbp_on_profile or gbp_on_site) else "fail",
                         "Found: " + ", ".join((gbp_on_profile + gbp_on_site)[:3]) if (gbp_on_profile or gbp_on_site)
                         else "No Google Business Profile link was found on your site or in your project profile.",
                         "Your Google Business Profile feeds Google Maps and local search results, which many AI assistants draw on.", 3,
                         gbp_on_profile + gbp_on_site,
                         "Create or claim your Google Business Profile, verify it, and link to it from your site and project profile."))
    checks.append(_check("local_profiles", "Official profiles are linked from the website", "pass" if site_profiles else ("unknown" if not content_readable else "fail"),
                         f"{len(site_profiles)} profile link(s) found." if site_profiles else (unreadable if not content_readable else "No links to your business or social profiles were found."),
                         "Linking your official profiles helps search engines and AI tie them to the same business.", 1, site_profiles[:5],
                         "Link your Google Business Profile and social profiles from the footer."))

    # 8. Services have content
    if not services:
        checks.append(_check("local_services", "Each main service has content on the site", "unknown",
                             "Add your services to the project profile to check this.", "Customers ask about specific services.", 2))
    elif not content_readable:
        checks.append(_check("local_services", "Each main service has content on the site", "unknown", unreadable, "", 2))
    else:
        covered = [s for s in services if pages_mentioning(s)]
        missing = [s for s in services if s not in covered]
        checks.append(_check("local_services", "Each main service has content on the site", "pass" if not missing else "fail",
                             f"{len(covered)} of {len(services)} services are mentioned on the site." + (f" Missing: {', '.join(missing)}." if missing else ""),
                             "Questions like 'who offers X in " + (city or "my city") + "' are answered from pages that mention X.", 2,
                             [f"Not found: {m}" for m in missing], "Give each main service its own page or section, naming the service and your location."))

    measured = [c for c in checks if c["status"] != "unknown"]
    total = sum(c["weight"] for c in measured)
    score = round(100 * sum(c["weight"] for c in measured if c["passed"]) / total, 1) if total else None
    inconsistencies = [e for c in checks if c["id"] == "local_schema" and not c["passed"] for e in c["evidence"] if "differs" in e or "doesn't include" in e]
    return {
        "score": score,  # None when nothing could be measured
        "checks": checks,
        "measured": len(measured),
        "unknown": len(checks) - len(measured),
        "found": {"phones": sorted(found_keys), "tel_links": tel_links, "profiles": site_profiles[:10], "schema": schema_nodes[:3]},
        "inconsistencies": inconsistencies,
    }
