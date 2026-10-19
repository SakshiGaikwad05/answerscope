"""Render JavaScript-only pages in a headless browser, safely.

Used only when a page's HTML is an empty app shell. A browser makes its own
network requests, so it gets its own SSRF guards:

* Every request is intercepted. Only http(s) requests to the audited site (its
  host, www variant or subdomains) are allowed, after the same public-IP check
  the fetcher uses. Third-party requests, images, media and fonts are blocked.
* The audited host is pinned to its vetted IP with Chromium's host-resolver-rules,
  so DNS can't be re-pointed at an internal address after the check.
* Service workers are blocked and every page has a hard timeout.
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

from app.crawler.url_safety import UnsafeURLError, is_same_site, resolve_public_target

logger = logging.getLogger(__name__)
BLOCKED_RESOURCE_TYPES = {"image", "media", "font", "websocket", "eventsource", "manifest", "other"}


class RenderError(Exception):
    pass


def browser_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


class PageRenderer:
    """One headless browser for the duration of a crawl. Use as a context manager."""

    def __init__(self, root_host: str, *, user_agent: str, timeout: float = 20.0, resolver=None) -> None:
        self.root_host = root_host
        self.user_agent = user_agent
        self.timeout_ms = int(timeout * 1000)
        self._resolver_kwargs = {"resolver": resolver} if resolver else {}
        self._allowed_hosts: dict[str, bool] = {}
        self._pw = self._browser = self._context = None

    def __enter__(self) -> "PageRenderer":
        from playwright.sync_api import sync_playwright

        target = resolve_public_target(f"https://{self.root_host}/", **self._resolver_kwargs)
        rules = f"MAP {target.host} {target.ip}"
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(
                headless=True,
                args=[f"--host-resolver-rules={rules}", "--disable-dev-shm-usage", "--no-first-run"],
            )
            self._context = self._browser.new_context(
                user_agent=self.user_agent, service_workers="block", java_script_enabled=True, ignore_https_errors=False
            )
            self._context.route("**/*", self._guard)
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc) -> None:
        for closer in (self._context, self._browser):
            try:
                if closer is not None:
                    closer.close()
            except Exception:  # noqa: BLE001
                pass
        if self._pw is not None:
            self._pw.stop()

    def _host_allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not is_same_site(url, self.root_host):
            return False
        host = parts.hostname or ""
        if host not in self._allowed_hosts:
            try:
                resolve_public_target(url, **self._resolver_kwargs)
                self._allowed_hosts[host] = True
            except UnsafeURLError:
                self._allowed_hosts[host] = False
        return self._allowed_hosts[host]

    def _guard(self, route) -> None:
        request = route.request
        if request.resource_type in BLOCKED_RESOURCE_TYPES or not self._host_allowed(request.url):
            route.abort()
        else:
            route.continue_()

    def render(self, url: str) -> tuple[str, str]:
        """Return (final_url, rendered_html)."""
        if not self._host_allowed(url):
            raise RenderError(f"Refusing to render {url}")
        page = self._context.new_page()
        page.set_default_timeout(self.timeout_ms)
        try:
            try:
                page.goto(url, wait_until="networkidle", timeout=self.timeout_ms)
            except Exception as exc:  # noqa: BLE001 - slow pages: keep whatever has rendered
                if "Timeout" not in type(exc).__name__ and "timeout" not in str(exc).lower():
                    raise RenderError(f"Could not render {url}: {type(exc).__name__}") from exc
            if not self._host_allowed(page.url):
                raise RenderError(f"Rendering left the audited site ({page.url})")
            return page.url, page.content()
        finally:
            page.close()
