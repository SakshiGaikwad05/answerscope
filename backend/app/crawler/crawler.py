"""Small, polite site crawler: robots.txt + sitemap.xml + prioritized internal links."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

from app.analysis.extract import PageData, extract_page, normalize_link
from app.crawler.fetcher import FetchError, FetchResult, SafeFetcher
from app.crawler.url_safety import UnsafeURLError, is_same_site, normalize_url

logger = logging.getLogger(__name__)

# User agents of AI crawlers / answer engines whose access we report on.
AI_CRAWLERS: dict[str, str] = {
    "GPTBot": "OpenAI model training crawler",
    "OAI-SearchBot": "ChatGPT search indexing",
    "ChatGPT-User": "ChatGPT user-initiated browsing",
    "ClaudeBot": "Anthropic model training crawler",
    "Claude-SearchBot": "Claude search indexing",
    "Claude-User": "Claude user-initiated fetching",
    "PerplexityBot": "Perplexity search indexing",
    "Google-Extended": "Gemini / Google AI training control",
    "CCBot": "Common Crawl (used by many AI datasets)",
    "Bingbot": "Bing search (powers Copilot and others)",
}

# Path keywords that indicate pages answer engines tend to rely on.
PRIORITY_KEYWORDS = [
    ("pricing", 10), ("price", 9), ("faq", 10), ("about", 8), ("compare", 9), ("comparison", 9),
    ("-vs-", 9), ("/vs", 8), ("alternative", 9), ("feature", 8), ("product", 6), ("solution", 6),
    ("use-case", 7), ("customers", 5), ("case-stud", 5), ("how-it-works", 7), ("help", 4),
    ("support", 4), ("docs", 3), ("contact", 3), ("security", 3), ("integrations", 5),
]
MAX_SITEMAP_URLS = 500
MAX_CHILD_SITEMAPS = 3

# Signatures of bot-protection / challenge interstitials served instead of content.
_CHALLENGE_MARKERS = (
    "cf-browser-verification", "challenge-platform", "cf_chl_opt", "__cf_chl",
    "_incapsula_resource", "px-captcha", "captcha-delivery.com", "/_sec/cp_challenge",
)
_CHALLENGE_TITLES = ("just a moment", "attention required", "access denied", "are you a robot", "verify you are human", "security check")


def detect_bot_protection(res: FetchResult) -> bool:
    """True if the response looks like a bot challenge page rather than the real site."""
    if not res.is_html:
        return False
    head = res.content[:200_000].decode("utf-8", errors="ignore").lower()
    if any(marker in head for marker in _CHALLENGE_MARKERS):
        return True
    start = head.find("<title")
    title = head[start : head.find("</title>", start)] if start != -1 else ""
    return any(t in title for t in _CHALLENGE_TITLES) and len(head) < 50_000


def homepage_http_error(status: int, url: str) -> FetchError:
    if status in (401, 403):
        return FetchError(
            f"The website refused access to our crawler (HTTP {status}). It may block automated requests "
            "or require a login, so it could not be audited.",
            code="blocked", url=url, status_code=status,
        )
    if status == 429:
        return FetchError(
            "The website is rate-limiting requests (HTTP 429). Wait a few minutes and run the audit again.",
            code="rate_limited", url=url, status_code=status,
        )
    if status == 404:
        return FetchError(f"The homepage was not found (HTTP 404) at {url}. Check the URL.", code="http_error", url=url, status_code=status)
    if status >= 500:
        return FetchError(f"The website returned a server error (HTTP {status}). Try again later.", code="http_error", url=url, status_code=status)
    return FetchError(f"The homepage returned HTTP {status}.", code="http_error", url=url, status_code=status)


@dataclass
class CrawledPage:
    data: PageData
    status_code: int


@dataclass
class CrawlResult:
    start_url: str
    root_url: str
    pages: list[CrawledPage] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)
    skipped_by_robots: list[str] = field(default_factory=list)
    robots: dict = field(default_factory=dict)
    sitemap: dict = field(default_factory=dict)
    https: bool = False
    stopped_early: str | None = None  # why the crawl ended before max_pages, if it did
    rendered_pages: list[str] = field(default_factory=list)  # pages rendered in a headless browser
    render_error: str | None = None


def _origin(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, "", "", ""))


def _priority(url: str) -> int:
    path = urlsplit(url).path.lower()
    score = 0
    for keyword, weight in PRIORITY_KEYWORDS:
        if keyword in path:
            score = max(score, weight)
    depth = path.strip("/").count("/")
    return score * 10 - depth


def _canonical_key(url: str) -> str:
    p = urlsplit(url)
    path = p.path.rstrip("/") or "/"
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return f"{host}{path}?{p.query}" if p.query else f"{host}{path}"


class SiteCrawler:
    def __init__(
        self,
        *,
        user_agent: str,
        max_pages: int = 15,
        timeout: float = 10.0,
        max_bytes: int = 2_000_000,
        max_redirects: int = 5,
        fetcher: SafeFetcher | None = None,
        sleep: Callable[[float], None] = time.sleep,
        politeness_delay: float = 0.25,
        max_seconds: float = 120.0,
        renderer_factory: Callable[[str], object] | None = None,
        render_max_pages: int = 8,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.user_agent = user_agent
        self.robots_token = user_agent.split("/")[0]
        self.max_pages = max_pages
        self.fetcher = fetcher or SafeFetcher(
            user_agent=user_agent, timeout=timeout, max_bytes=max_bytes, max_redirects=max_redirects
        )
        self.sleep = sleep
        self.delay = politeness_delay
        self.max_seconds = max_seconds
        self.clock = clock
        # renderer_factory(root_host) -> context manager with .render(url) -> (final_url, html)
        self.renderer_factory = renderer_factory
        self.render_max_pages = render_max_pages

    # -- robots.txt -------------------------------------------------------
    def _load_robots(self, origin: str) -> tuple[RobotFileParser | None, dict]:
        info: dict = {"url": origin + "/robots.txt", "found": False, "sitemaps": [], "ai_crawlers": {}}
        try:
            res = self.fetcher.fetch(origin + "/robots.txt", accept="text/plain,*/*;q=0.5")
        except (FetchError, UnsafeURLError) as exc:
            info["error"] = str(exc)
            return None, info
        info["status_code"] = res.status_code
        if res.status_code >= 400 or res.is_html:
            # Missing robots.txt (or an HTML error page served in its place): everything is allowed.
            return None, info
        parser = RobotFileParser()
        lines = res.text.splitlines()
        parser.parse(lines)
        info["found"] = True
        info["sitemaps"] = [
            line.split(":", 1)[1].strip() for line in lines if line.lower().startswith("sitemap:")
        ][:10]
        homepage = origin + "/"
        info["ai_crawlers"] = {
            agent: {"allowed": parser.can_fetch(agent, homepage), "description": desc}
            for agent, desc in AI_CRAWLERS.items()
        }
        delay = parser.crawl_delay(self.robots_token) or parser.crawl_delay("*")
        if delay:
            info["crawl_delay"] = float(delay)
            self.delay = min(max(self.delay, float(delay)), 2.0)
        return parser, info

    # -- sitemap.xml ------------------------------------------------------
    def _load_sitemap(self, origin: str, declared: list[str]) -> tuple[list[str], dict]:
        candidates = declared or [origin + "/sitemap.xml"]
        info: dict = {"found": False, "url": None, "url_count": 0}
        urls: list[str] = []
        for sm_url in candidates[:3]:
            locs, is_index = self._fetch_sitemap(sm_url)
            if locs is None:
                continue
            info.update(found=True, url=sm_url)
            if is_index:
                info["index"] = True
                for child in locs[:MAX_CHILD_SITEMAPS]:
                    child_locs, _ = self._fetch_sitemap(child)
                    urls.extend(child_locs or [])
            else:
                urls.extend(locs)
            break
        urls = list(dict.fromkeys(urls))[:MAX_SITEMAP_URLS]
        info["url_count"] = len(urls)
        return urls, info

    def _fetch_sitemap(self, url: str) -> tuple[list[str] | None, bool]:
        try:
            res = self.fetcher.fetch(url, accept="application/xml,text/xml,*/*;q=0.5")
        except (FetchError, UnsafeURLError) as exc:
            logger.info("Sitemap fetch failed for %s: %s", url, exc)
            return None, False
        if res.status_code != 200 or res.is_html:
            return None, False
        soup = BeautifulSoup(res.content, "xml")
        is_index = soup.find("sitemapindex") is not None
        locs = [loc.get_text(strip=True) for loc in soup.find_all("loc")]
        if not locs and soup.find("urlset") is None and not is_index:
            return None, False
        return locs, is_index

    # -- crawl ------------------------------------------------------------
    def crawl(self, url: str, progress: Callable[[str], None] | None = None) -> CrawlResult:
        report = progress or (lambda _msg: None)
        start = normalize_url(url)
        origin = _origin(start)
        result = CrawlResult(start_url=start, root_url=start)

        report("Checking robots.txt")
        robots, result.robots = self._load_robots(origin)
        started = self.clock()
        if robots and not robots.can_fetch(self.robots_token, start):
            result.skipped_by_robots.append(start)
            raise FetchError(
                "robots.txt disallows crawling this website's homepage for our crawler, so it was not audited.",
                code="robots_disallowed", url=start,
            )

        report("Fetching homepage")
        home = self.fetcher.fetch(start)
        logger.info(
            "homepage %s -> %s HTTP %s %s (%d bytes)",
            start, home.final_url, home.status_code, home.content_type or "-", len(home.content),
        )
        result.root_url = home.final_url
        root_host = urlsplit(home.final_url).hostname or ""
        result.https = home.final_url.startswith("https://")
        if _origin(home.final_url) != origin:
            # Homepage redirected (e.g. to www. or a new domain): use that site's robots.txt.
            origin = _origin(home.final_url)
            robots, result.robots = self._load_robots(origin)
        self.fetcher.restrict_to_host = root_host

        if detect_bot_protection(home):
            raise FetchError(
                "The website served a bot-protection challenge (e.g. Cloudflare) instead of its content, "
                "so it could not be audited. Results would describe the challenge page, not your site.",
                code="bot_protection", url=home.final_url, status_code=home.status_code,
            )
        if home.status_code >= 400:
            raise homepage_http_error(home.status_code, home.final_url)
        if not home.is_html:
            raise FetchError(
                f"The homepage is not an HTML page (content-type: {home.content_type or 'unknown'}).",
                code="not_html", url=home.final_url, status_code=home.status_code,
            )

        home_page = extract_page(home.final_url, home.content)
        renderer = None
        if home_page.js_shell and self.renderer_factory is not None:
            try:
                renderer = self.renderer_factory(root_host)
                renderer.__enter__()
            except Exception as exc:  # noqa: BLE001 - rendering is best effort
                logger.warning("could not start the browser renderer: %s", exc)
                result.render_error = "JavaScript rendering is unavailable on this server."
                renderer = None
        try:
            return self._crawl_from_home(home, home_page, renderer, root_host, origin, start, robots, result, report, started)
        finally:
            if renderer is not None:
                renderer.__exit__(None, None, None)

    def _render(self, renderer, url: str, raw: PageData, result: CrawlResult) -> PageData:
        """Render an empty JavaScript shell page; fall back to the raw page on failure."""
        if renderer is None or len(result.rendered_pages) >= self.render_max_pages:
            return raw
        try:
            final_url, html = renderer.render(url)
        except Exception as exc:  # noqa: BLE001
            logger.info("render failed for %s: %s", url, exc)
            result.render_error = f"Could not render {url} in a browser."
            return raw
        data = extract_page(final_url, html)
        # What crawlers that don't run JavaScript see is still an empty shell.
        data.js_shell, data.js_shell_evidence, data.rendered = True, raw.js_shell_evidence, True
        result.rendered_pages.append(final_url)
        return data

    def _crawl_from_home(self, home, home_page, renderer, root_host, origin, start, robots, result, report, started) -> CrawlResult:
        if renderer is not None:
            report("Rendering JavaScript in a browser")
            home_page = self._render(renderer, home.final_url, home_page, result)
        result.pages.append(CrawledPage(home_page, home.status_code))
        seen = {_canonical_key(start), _canonical_key(home.final_url)}

        report("Reading sitemap.xml")
        sitemap_urls, result.sitemap = self._load_sitemap(origin, result.robots.get("sitemaps", []))

        candidates: dict[str, str] = {}
        for link in sitemap_urls + home_page.internal_links:
            norm = normalize_link(home.final_url, link)
            if norm and is_same_site(norm, root_host):
                candidates.setdefault(_canonical_key(norm), norm)
        queue = sorted(
            (u for k, u in candidates.items() if k not in seen), key=lambda u: (-_priority(u), len(u))
        )

        while queue and len(result.pages) < self.max_pages:
            if self.clock() - started > self.max_seconds:
                result.stopped_early = f"time limit of {int(self.max_seconds)}s reached"
                logger.info("crawl of %s stopped early: %s", start, result.stopped_early)
                break
            page_url = queue.pop(0)
            key = _canonical_key(page_url)
            if key in seen:
                continue
            seen.add(key)
            if robots and not robots.can_fetch(self.robots_token, page_url):
                result.skipped_by_robots.append(page_url)
                continue
            report(f"Crawling page {len(result.pages) + 1} of up to {self.max_pages}")
            self.sleep(self.delay)
            try:
                res = self.fetcher.fetch(page_url)
            except (FetchError, UnsafeURLError) as exc:
                result.failures.append({"url": page_url, "error": str(exc)})
                continue
            if _canonical_key(res.final_url) in seen and res.final_url != page_url:
                continue
            seen.add(_canonical_key(res.final_url))
            if res.status_code >= 400:
                result.failures.append({"url": page_url, "error": f"HTTP {res.status_code}"})
                continue
            if not res.is_html:
                continue
            if detect_bot_protection(res):
                result.failures.append({"url": page_url, "error": "Bot-protection challenge served instead of content"})
                continue
            data = extract_page(res.final_url, res.content)
            if data.js_shell:
                data = self._render(renderer, res.final_url, data, result)
            result.pages.append(CrawledPage(data, res.status_code))
            # Discover a few more links from important pages
            for link in data.internal_links:
                k = _canonical_key(link)
                if k not in seen and k not in candidates:
                    candidates[k] = link
                    queue.append(link)
            queue.sort(key=lambda u: (-_priority(u), len(u)))
        return result

    def close(self) -> None:
        self.fetcher.close()
