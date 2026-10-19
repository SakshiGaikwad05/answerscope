"""Safe HTTP fetcher used by the crawler.

- Validates every URL (including each redirect hop) with `resolve_public_target`.
- Connects to the vetted IP address directly, sending the original Host header
  and TLS SNI, so DNS rebinding can't redirect a request to an internal address.
- Enforces timeouts, a maximum response size and a redirect limit.
- Optionally restricts fetches to a single site (domain restriction).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from app.crawler.url_safety import ResolvedTarget, UnsafeURLError, is_same_site, resolve_public_target

logger = logging.getLogger(__name__)

REDIRECT_CODES = {301, 302, 303, 307, 308}


class FetchError(Exception):
    """A fetch failed for a reason worth reporting (timeout, too large, blocked, ...).

    `code` is a stable machine-readable reason shown alongside the message:
    timeout, connection, too_large, too_many_redirects, http_error, blocked,
    rate_limited, bot_protection, not_html, robots_disallowed.
    """

    def __init__(self, message: str, *, code: str = "fetch_error", url: str | None = None, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.url = url
        self.status_code = status_code

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "url": self.url, "status_code": self.status_code}


@dataclass
class FetchResult:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    content: bytes
    headers: dict[str, str] = field(default_factory=dict)
    truncated: bool = False

    @property
    def text(self) -> str:
        charset = "utf-8"
        for part in self.content_type.split(";")[1:]:
            key, _, value = part.strip().partition("=")
            if key.lower() == "charset" and value:
                charset = value.strip().strip('"')
        try:
            return self.content.decode(charset, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")

    @property
    def is_html(self) -> bool:
        ct = self.content_type.lower()
        return "text/html" in ct or "application/xhtml" in ct


def _pinned_request_url(target: ResolvedTarget) -> tuple[str, str]:
    """Return (url with IP as host, Host header value)."""
    parts = urlsplit(target.url)
    ip_host = f"[{target.ip}]" if ":" in target.ip else target.ip
    default_port = 443 if target.scheme == "https" else 80
    netloc = ip_host if target.port == default_port else f"{ip_host}:{target.port}"
    host_header = target.host if target.port == default_port else f"{target.host}:{target.port}"
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, "")), host_header


class SafeFetcher:
    def __init__(
        self,
        *,
        user_agent: str,
        timeout: float = 10.0,
        max_bytes: int = 2_000_000,
        max_redirects: int = 5,
        restrict_to_host: str | None = None,
        transport: httpx.BaseTransport | None = None,
        resolver=None,
    ) -> None:
        self.user_agent = user_agent
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.restrict_to_host = restrict_to_host
        self._resolver_kwargs = {"resolver": resolver} if resolver else {}
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,
            transport=transport,
            trust_env=False,  # never route through env-configured proxies
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SafeFetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def fetch(self, url: str, accept: str = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5") -> FetchResult:
        current = url
        for _hop in range(self.max_redirects + 1):
            target = resolve_public_target(current, **self._resolver_kwargs)
            if self.restrict_to_host and not is_same_site(target.url, self.restrict_to_host):
                raise UnsafeURLError(f"Refusing to leave the audited site ({target.host})")
            request_url, host_header = _pinned_request_url(target)
            headers = {"Host": host_header, "User-Agent": self.user_agent, "Accept": accept}
            extensions = {"sni_hostname": target.host} if target.scheme == "https" else {}
            try:
                with self._client.stream("GET", request_url, headers=headers, extensions=extensions) as resp:
                    logger.debug("GET %s -> HTTP %s", target.url, resp.status_code)
                    if resp.status_code in REDIRECT_CODES:
                        location = resp.headers.get("location")
                        if not location:
                            raise FetchError(
                                f"Redirect without Location header from {target.url}",
                                code="http_error", url=target.url, status_code=resp.status_code,
                            )
                        current = urljoin(target.url, location)
                        continue
                    content, truncated = self._read_limited(resp, target.url)
                    return FetchResult(
                        requested_url=url,
                        final_url=target.url,
                        status_code=resp.status_code,
                        content_type=resp.headers.get("content-type", ""),
                        content=content,
                        headers={k.lower(): v for k, v in resp.headers.items()},
                        truncated=truncated,
                    )
            except httpx.TimeoutException as exc:
                raise FetchError(
                    f"The website did not respond in time ({target.url}).", code="timeout", url=target.url
                ) from exc
            except httpx.ConnectError as exc:
                raise FetchError(
                    f"Could not connect to {target.host} (connection refused or unreachable).",
                    code="connection", url=target.url,
                ) from exc
            except httpx.HTTPError as exc:
                raise FetchError(
                    f"Could not fetch {target.url} ({exc.__class__.__name__}).", code="connection", url=target.url
                ) from exc
        raise FetchError(f"Too many redirects starting at {url}", code="too_many_redirects", url=url)

    def _read_limited(self, resp: httpx.Response, url: str) -> tuple[bytes, bool]:
        declared = resp.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self.max_bytes * 4:
            raise FetchError(f"Response too large ({declared} bytes)", code="too_large", url=url)
        buf = bytearray()
        for chunk in resp.iter_bytes():
            buf.extend(chunk)
            if len(buf) > self.max_bytes:
                return bytes(buf[: self.max_bytes]), True
        return bytes(buf), False
