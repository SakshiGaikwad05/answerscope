"""URL validation and SSRF protection.

Every outbound request made by the crawler goes through `resolve_public_target`,
which rejects non-HTTP(S) schemes, credentials in URLs, local hostnames and any
hostname that resolves to a non-public IP address. The fetcher then connects to
the vetted IP directly (pinning) so a DNS answer cannot change between the check
and the connection.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".intranet", ".corp")
BLOCKED_HOSTS = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback", "metadata.google.internal"}
MAX_URL_LENGTH = 2048


class UnsafeURLError(ValueError):
    """Raised when a URL is malformed or points somewhere we refuse to fetch."""


@dataclass(frozen=True)
class ResolvedTarget:
    url: str
    scheme: str
    host: str
    port: int
    ip: str


def is_public_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(
        ip.is_global
        and not ip.is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_multicast
        and not ip.is_reserved
        and not ip.is_unspecified
    )


def normalize_url(raw: str) -> str:
    """Validate the *syntax* of a user-supplied URL and return a normalized form.

    Adds https:// when no scheme is given. Does not perform DNS resolution.
    """
    if raw is None:
        raise UnsafeURLError("URL is required")
    candidate = raw.strip()
    if not candidate:
        raise UnsafeURLError("URL is required")
    if len(candidate) > MAX_URL_LENGTH:
        raise UnsafeURLError("URL is too long")
    if any(ch.isspace() for ch in candidate) or any(ord(ch) < 32 for ch in candidate):
        raise UnsafeURLError("URL must not contain whitespace or control characters")
    if "://" not in candidate:
        if ":" in candidate.split("/")[0] and not candidate.split("/")[0].rsplit(":", 1)[-1].isdigit():
            # e.g. "javascript:alert(1)" or "file:/etc/passwd"
            raise UnsafeURLError("Only http and https URLs are allowed")
        candidate = "https://" + candidate

    parts = urlsplit(candidate)
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError("Only http and https URLs are allowed")
    if parts.username or parts.password:
        raise UnsafeURLError("URLs with embedded credentials are not allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeURLError("URL must include a hostname")
    try:
        port = parts.port
    except ValueError as exc:
        raise UnsafeURLError("URL has an invalid port") from exc

    check_hostname(host)

    try:
        host_idna = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UnsafeURLError("URL has an invalid hostname") from exc

    netloc = f"[{host_idna}]" if ":" in host_idna else host_idna
    if port is not None:
        netloc += f":{port}"
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def check_hostname(host: str) -> None:
    """Reject hostnames that are obviously local or are non-public IP literals."""
    if host in BLOCKED_HOSTS or host.endswith(BLOCKED_HOST_SUFFIXES):
        raise UnsafeURLError("Local or internal hostnames are not allowed")
    literal = host.strip("[]")
    try:
        ipaddress.ip_address(literal)
    except ValueError:
        if "." not in host:
            raise UnsafeURLError("Hostname must be a fully qualified public domain") from None
        return
    if not is_public_ip(literal):
        raise UnsafeURLError("Private, loopback, link-local and reserved IP addresses are not allowed")


def _default_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(info[4][0] for info in infos))


def resolve_public_target(url: str, resolver=_default_resolver) -> ResolvedTarget:
    """Normalize the URL, resolve its hostname and require every address to be public."""
    normalized = normalize_url(url)
    parts = urlsplit(normalized)
    host = (parts.hostname or "").lower()
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        ips = resolver(host, port)
    except (socket.gaierror, UnicodeError, OSError) as exc:
        raise UnsafeURLError(f"Could not resolve hostname {host!r}") from exc
    if not ips:
        raise UnsafeURLError(f"Could not resolve hostname {host!r}")
    for ip in ips:
        if not is_public_ip(ip):
            raise UnsafeURLError(f"Hostname {host!r} resolves to a non-public address")
    return ResolvedTarget(url=normalized, scheme=parts.scheme, host=host, port=port, ip=ips[0])


def site_key(host: str) -> str:
    """Host with a leading 'www.' stripped; used for same-site comparisons."""
    host = host.lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def is_same_site(url: str, root_host: str) -> bool:
    """True for the root host, its www. variant and its subdomains.

    e.g. root www.wikipedia.org accepts en.wikipedia.org (where its sitemap lives),
    but example.com never accepts example.com.evil.org.
    """
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return False
    host, root = site_key(host), site_key(root_host)
    return host == root or host.endswith("." + root)
