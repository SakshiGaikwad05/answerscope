"""Extract audit-relevant facts from an HTML page."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup

from app.crawler.url_safety import is_same_site

_WS = re.compile(r"\s+")
_NON_CONTENT_TAGS = ["script", "style", "noscript", "template", "svg", "iframe", "canvas"]
_SKIP_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".zip", ".mp4", ".mp3",
    ".css", ".js", ".ico", ".xml", ".json", ".woff", ".woff2", ".ttf", ".dmg", ".exe",
)


_APP_MOUNT_IDS = re.compile(r"^(root|app|__next|__nuxt|svelte|q-app|main-app|application)$", re.I)
JS_SHELL_MAX_WORDS = 80


def clean(text: str | None) -> str:
    return _WS.sub(" ", text or "").strip()


@dataclass
class PageData:
    url: str
    title: str | None = None
    meta_description: str | None = None
    canonical: str | None = None
    lang: str | None = None
    h1: list[str] = field(default_factory=list)
    headings: list[dict] = field(default_factory=list)
    internal_links: list[str] = field(default_factory=list)
    external_links: list[str] = field(default_factory=list)
    text: str = ""
    word_count: int = 0
    schema_types: list[str] = field(default_factory=list)
    schema_errors: list[str] = field(default_factory=list)
    has_faq: bool = False
    faq_questions: list[str] = field(default_factory=list)
    has_open_graph: bool = False
    meta_robots: str | None = None
    # The HTML is an empty app shell whose content only appears after JavaScript runs.
    js_shell: bool = False
    js_shell_evidence: str | None = None
    # Content was extracted from a headless-browser render of a JavaScript shell
    rendered: bool = False


def _collect_schema_types(node, out: list[str]) -> None:
    if isinstance(node, list):
        for item in node:
            _collect_schema_types(item, out)
    elif isinstance(node, dict):
        t = node.get("@type")
        if isinstance(t, str):
            out.append(t)
        elif isinstance(t, list):
            out.extend(x for x in t if isinstance(x, str))
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                _collect_schema_types(node[key], out)


def _faq_questions_from_schema(node, out: list[str]) -> None:
    if isinstance(node, list):
        for item in node:
            _faq_questions_from_schema(item, out)
    elif isinstance(node, dict):
        types = node.get("@type")
        types = [types] if isinstance(types, str) else (types or [])
        if "Question" in types and isinstance(node.get("name"), str):
            out.append(clean(node["name"]))
        for key in ("@graph", "mainEntity"):
            if key in node:
                _faq_questions_from_schema(node[key], out)


def normalize_link(base_url: str, href: str) -> str | None:
    href = (href or "").strip()
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return None
    absolute, _frag = urldefrag(urljoin(base_url, href))
    parts = urlsplit(absolute)
    if parts.scheme not in ("http", "https"):
        return None
    if parts.path.lower().endswith(_SKIP_EXTENSIONS):
        return None
    return absolute


def extract_page(url: str, html: str | bytes) -> PageData:
    soup = BeautifulSoup(html, "lxml")
    page = PageData(url=url)
    root_host = urlsplit(url).hostname or ""

    if soup.title:
        page.title = clean(soup.title.get_text()) or None

    desc = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    if desc and desc.get("content"):
        page.meta_description = clean(desc["content"]) or None
    robots = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
    if robots and robots.get("content"):
        page.meta_robots = clean(robots["content"]).lower()
    canonical = soup.find("link", rel=lambda v: v and "canonical" in [x.lower() for x in (v if isinstance(v, list) else [v])])
    if canonical and canonical.get("href"):
        page.canonical = urljoin(url, canonical["href"])
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        page.lang = clean(html_tag["lang"])[:50]
    page.has_open_graph = bool(soup.find("meta", attrs={"property": re.compile(r"^og:", re.I)}))

    # Structured data (JSON-LD + microdata)
    schema_types: list[str] = []
    faq_from_schema: list[str] = []
    for tag in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        raw = tag.string or tag.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            page.schema_errors.append("Invalid JSON-LD block (could not be parsed)")
            continue
        _collect_schema_types(data, schema_types)
        _faq_questions_from_schema(data, faq_from_schema)
    for tag in soup.find_all(attrs={"itemtype": True}):
        itemtype = str(tag["itemtype"]).rstrip("/").rsplit("/", 1)[-1]
        if itemtype:
            schema_types.append(itemtype)
    page.schema_types = sorted(set(schema_types))

    # Links (collected before stripping nav/footer)
    internal, external = [], []
    for a in soup.find_all("a", href=True):
        link = normalize_link(url, a["href"])
        if not link:
            continue
        (internal if is_same_site(link, root_host) else external).append(link)
    page.internal_links = list(dict.fromkeys(internal))
    page.external_links = list(dict.fromkeys(external))

    # Signals for JavaScript-only rendering, gathered before scripts are stripped.
    script_count = len(soup.find_all("script", src=True))
    mount = soup.find(id=_APP_MOUNT_IDS)
    mount_empty = mount is not None and not clean(mount.get_text(" "))
    noscript_js = any(re.search(r"javascript", ns.get_text(" "), re.I) for ns in soup.find_all("noscript"))

    for tag in soup(_NON_CONTENT_TAGS):
        tag.decompose()

    ordered = []
    for h in soup.find_all(re.compile(r"^h[1-6]$")):
        text = clean(h.get_text(" "))
        if text:
            ordered.append({"level": int(h.name[1]), "text": text[:300]})
    page.headings = ordered
    page.h1 = [h["text"] for h in ordered if h["level"] == 1]

    body = soup.body or soup
    page.text = clean(body.get_text(" "))
    page.word_count = len(page.text.split())
    if page.word_count < JS_SHELL_MAX_WORDS and script_count and (mount_empty or noscript_js):
        page.js_shell = True
        where = f"an empty <div id=\"{mount['id']}\">" if mount_empty else "a page that asks visitors to enable JavaScript"
        page.js_shell_evidence = (
            f"The HTML contains only {page.word_count} words of text and {where}; "
            f"the content is added later by {script_count} JavaScript file(s)."
        )

    # FAQ detection: FAQPage schema, question-style headings, <details>/<summary>
    question_headings = [h["text"] for h in ordered if h["text"].endswith("?") and h["level"] >= 2]
    summaries = [clean(s.get_text(" ")) for s in soup.find_all("summary")]
    summary_questions = [s for s in summaries if s.endswith("?")]
    faq_heading = any(re.search(r"\b(faq|frequently asked)", h["text"], re.I) for h in ordered)
    faq_questions = list(dict.fromkeys(faq_from_schema + question_headings + summary_questions))
    page.faq_questions = faq_questions[:50]
    page.has_faq = (
        "FAQPage" in page.schema_types
        or len(faq_questions) >= 3
        or (faq_heading and len(faq_questions) >= 1)
    )
    return page
