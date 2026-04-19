"""Fetch a human-readable title for a URL. Best-effort, never raises.

Blocks private/loopback targets to prevent SSRF via user-submitted links.
"""
from __future__ import annotations

import ipaddress
import logging
import re
import socket
from html import unescape
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_OG_TITLE_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
UA = "Mozilla/5.0 (GetChatBot/1.0)"

_shared_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": UA},
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _shared_client


async def shutdown() -> None:
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()
    _shared_client = None


def _is_public_url(url: str) -> bool:
    """Return True only if the URL points to a public host reachable safely.

    Blocks: non-http(s), private/loopback/link-local/reserved IPs, and any host
    that resolves to such an address (defense against DNS rebinding for the
    initial request — we still rely on httpx following redirects).
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname
    # Reject explicit IP literals that are private.
    try:
        ip = ipaddress.ip_address(host)
        return _is_public_ip(ip)
    except ValueError:
        pass
    # Resolve hostname and ensure every returned address is public.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if not _is_public_ip(ip):
            return False
    return True


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


async def _oembed_youtube(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await client.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
        )
        if r.status_code == 200:
            return (r.json().get("title") or "").strip() or None
    except Exception:
        return None
    return None


async def _html_title(client: httpx.AsyncClient, url: str) -> str | None:
    if not _is_public_url(url):
        log.info("link_metadata: refusing non-public URL %s", url)
        return None
    try:
        r = await client.get(url)
        if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
            return None
        html = r.text[:200_000]
        m = _OG_TITLE_RE.search(html) or _TITLE_RE.search(html)
        if not m:
            return None
        return unescape(m.group(1)).strip()[:500] or None
    except Exception:
        return None


async def fetch_title(url: str, kind: str) -> str | None:
    client = _get_client()
    if kind == "youtube":
        t = await _oembed_youtube(client, url)
        if t:
            return t
    return await _html_title(client, url)
