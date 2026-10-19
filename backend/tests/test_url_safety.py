import httpx
import pytest

from app.crawler.fetcher import SafeFetcher
from app.crawler.url_safety import UnsafeURLError, is_public_ip, is_same_site, normalize_url, resolve_public_target


def public_resolver(host, port):
    return ["93.184.216.34"]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("example.com", "https://example.com/"),
        ("https://Example.COM/path?q=1#frag", "https://example.com/path?q=1"),
        ("http://example.com:8080", "http://example.com:8080/"),
        ("  https://www.example.com  ", "https://www.example.com/"),
    ],
)
def test_normalize_url_accepts_public_urls(raw, expected):
    assert normalize_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "ftp://example.com/file",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://localhost:8000",
        "http://foo.localhost/",
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://0.0.0.0/",
        "http://user:pass@example.com/",
        "http://intranet/",
        "http://metadata.google.internal/",
        "http://exa mple.com/",
    ],
)
def test_normalize_url_rejects_unsafe_urls(raw):
    with pytest.raises(UnsafeURLError):
        normalize_url(raw)


def test_is_public_ip():
    assert is_public_ip("93.184.216.34")
    assert is_public_ip("2606:4700::1111")
    for ip in ["127.0.0.1", "10.1.1.1", "172.16.0.1", "192.168.0.1", "169.254.169.254", "::1", "fc00::1", "::ffff:127.0.0.1", "100.64.0.1"]:
        assert not is_public_ip(ip), ip


def test_resolve_rejects_hostnames_pointing_to_private_ips():
    with pytest.raises(UnsafeURLError, match="non-public"):
        resolve_public_target("https://evil.example.com", resolver=lambda h, p: ["10.0.0.1"])
    # Any private address among several answers is enough to reject
    with pytest.raises(UnsafeURLError):
        resolve_public_target("https://evil.example.com", resolver=lambda h, p: ["93.184.216.34", "127.0.0.1"])


def test_resolve_returns_pinned_ip():
    target = resolve_public_target("https://example.com/a", resolver=public_resolver)
    assert target.ip == "93.184.216.34"
    assert target.host == "example.com"
    assert target.port == 443


def test_same_site():
    assert is_same_site("https://www.example.com/x", "example.com")
    assert not is_same_site("https://example.org/", "example.com")
    assert not is_same_site("https://example.com.evil.org/", "example.com")


def test_fetcher_pins_ip_and_sends_host_header():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["host"] = request.headers["host"]
        seen["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html></html>")

    with SafeFetcher(user_agent="t", transport=httpx.MockTransport(handler), resolver=public_resolver) as f:
        res = f.fetch("https://example.com/page")
    assert seen["url"] == "https://93.184.216.34/page"
    assert seen["host"] == "example.com"
    assert seen["sni"] == "example.com"
    assert res.final_url == "https://example.com/page"
    assert res.is_html


def test_fetcher_blocks_redirect_to_private_address():
    def resolver(host, port):
        return ["127.0.0.1"] if host == "internal.example.com" else ["93.184.216.34"]

    def handler(request):
        return httpx.Response(302, headers={"location": "http://internal.example.com/admin"})

    with SafeFetcher(user_agent="t", transport=httpx.MockTransport(handler), resolver=resolver) as f:
        with pytest.raises(UnsafeURLError):
            f.fetch("https://example.com/")


def test_fetcher_blocks_redirect_to_non_http_scheme():
    def handler(request):
        return httpx.Response(302, headers={"location": "file:///etc/passwd"})

    with SafeFetcher(user_agent="t", transport=httpx.MockTransport(handler), resolver=public_resolver) as f:
        with pytest.raises(UnsafeURLError):
            f.fetch("https://example.com/")


def test_fetcher_enforces_domain_restriction_and_redirect_limit():
    def handler(request):
        return httpx.Response(302, headers={"location": "https://example.com/loop"})

    with SafeFetcher(user_agent="t", transport=httpx.MockTransport(handler), resolver=public_resolver, max_redirects=3) as f:
        with pytest.raises(Exception, match="Too many redirects"):
            f.fetch("https://example.com/")
        f.restrict_to_host = "example.com"
        with pytest.raises(UnsafeURLError, match="leave the audited site"):
            f.fetch("https://other.org/")


def test_fetcher_truncates_large_responses():
    def handler(request):
        size = 15_000 if request.url.path == "/" else 50_000
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"a" * size)

    with SafeFetcher(user_agent="t", transport=httpx.MockTransport(handler), resolver=public_resolver, max_bytes=10_000) as f:
        res = f.fetch("https://example.com/")
        assert res.truncated and len(res.content) == 10_000
        with pytest.raises(Exception, match="too large"):
            f.fetch("https://example.com/huge")


def test_same_site_includes_subdomains_of_the_root_site():
    assert is_same_site("https://en.wikipedia.org/wiki/X", "www.wikipedia.org")
    assert is_same_site("https://docs.example.com/", "example.com")
    assert not is_same_site("https://tiangolo.com/", "fastapi.tiangolo.com")  # parent domain is a different site
    assert not is_same_site("https://notexample.com/", "example.com")


def _raising_transport(exc_cls):
    def handler(request):
        raise exc_cls("boom", request=request)

    return httpx.MockTransport(handler)


def test_fetcher_reports_timeouts_with_code():
    from app.crawler.fetcher import FetchError

    with SafeFetcher(user_agent="t", transport=_raising_transport(httpx.ReadTimeout), resolver=public_resolver) as f:
        with pytest.raises(FetchError) as exc:
            f.fetch("https://example.com/")
    assert exc.value.code == "timeout"
    assert exc.value.as_dict()["url"] == "https://example.com/"


def test_fetcher_reports_connection_failures_with_code():
    from app.crawler.fetcher import FetchError

    with SafeFetcher(user_agent="t", transport=_raising_transport(httpx.ConnectError), resolver=public_resolver) as f:
        with pytest.raises(FetchError) as exc:
            f.fetch("https://example.com/")
    assert exc.value.code == "connection"
    assert "example.com" in exc.value.message


def test_unresolvable_hostname_is_rejected_cleanly():
    import socket

    def resolver(host, port):
        raise socket.gaierror("Name or service not known")

    with pytest.raises(UnsafeURLError, match="Could not resolve"):
        resolve_public_target("https://does-not-exist.example", resolver=resolver)
