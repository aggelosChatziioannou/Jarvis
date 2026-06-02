"""Shared SSRF-safe HTTP fetch helpers for builtin tools.

One audited implementation of the public-URL check + redirect-revalidating,
byte-capped fetch, shared by ``webSearch`` and ``fetchWebPage`` so a fix to
the SSRF guard covers both tools at once.

Untrusted URLs (including those surfaced by web content the model was steered
to fetch) must never reach private / loopback / link-local / cloud-metadata
addresses. ``data privacy comes first, always``.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests

from ...debug import debug_log

# Max redirects to follow manually (so we can re-validate each hop).
MAX_REDIRECTS = 3
# Max bytes pulled from a single page before giving up. Caps prompt-injection
# surface and protects against hostile servers streaming forever.
MAX_FETCH_BYTES = 512 * 1024


class UnsafeURLError(ValueError):
    """Raised when a URL (or a redirect hop) targets a non-public address."""


def is_public_url(url: str) -> bool:
    """Reject non-http(s) schemes and URLs pointing to private/loopback IPs.

    Defence against SSRF: a URL (or a redirect chain from one) could point at
    127.0.0.1, 169.254.169.254 (cloud metadata), 10.x/192.168.x, or
    file:///etc/passwd. We resolve the hostname and check every A/AAAA record
    against ``ipaddress`` private/loopback/link-local/reserved/multicast
    before issuing the request.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    # Literal IP in the URL — check directly, don't resolve.
    try:
        ip = ipaddress.ip_address(host)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast or ip.is_unspecified)
    except ValueError:
        pass
    # Hostname — resolve all addresses and reject if any is non-public. This is
    # stricter than checking only the first A record: a hostile DNS could
    # return [1.1.1.1, 127.0.0.1] and some clients would try both.
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception as e:
        debug_log(f"DNS lookup failed for {host}: {e}", "web")
        return False
    for info in infos:
        try:
            addr = info[4][0]
            ip = ipaddress.ip_address(addr)
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
                debug_log(f"Rejecting {url}: resolves to non-public {addr}", "web")
                return False
        except Exception:
            return False
    return True


def safe_fetch(
    url: str,
    *,
    headers: Optional[dict] = None,
    timeout: float = 15.0,
    max_bytes: int = MAX_FETCH_BYTES,
    max_redirects: int = MAX_REDIRECTS,
) -> Tuple[str, bytes]:
    """SSRF-validated, redirect-revalidating, byte-capped GET.

    Validates the initial URL and every redirect hop against ``is_public_url``,
    following redirects MANUALLY (``allow_redirects=False``) so each hop is
    re-checked, and stream-reads the body with a hard byte cap.

    Returns ``(final_url, body_bytes)``. Raises :class:`UnsafeURLError` if the
    initial URL or any redirect hop is non-public; propagates ``requests``
    exceptions on transport/HTTP failure.
    """
    if not is_public_url(url):
        raise UnsafeURLError(f"refusing to fetch non-public URL: {url}")

    current_url = url
    response: Optional[requests.Response] = None
    for _ in range(max_redirects + 1):
        response = requests.get(
            current_url, headers=headers, timeout=timeout,
            allow_redirects=False, stream=True,
        )
        if response.is_redirect or response.is_permanent_redirect:
            next_url = response.headers.get("Location", "")
            response.close()
            if not next_url:
                break
            next_url = urljoin(current_url, next_url)
            if not is_public_url(next_url):
                raise UnsafeURLError(f"refusing redirect to non-public URL: {next_url}")
            current_url = next_url
            continue
        break

    if response is None:  # pragma: no cover - loop always assigns
        raise requests.exceptions.RequestException("no response")
    response.raise_for_status()

    # Stream-read with a byte cap so a hostile server can't exhaust memory.
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=8192):
        if not chunk:
            continue
        chunks.append(chunk)
        total += len(chunk)
        if total >= max_bytes:
            break
    response.close()
    return current_url, b"".join(chunks)
