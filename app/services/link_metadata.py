"""Fetch a human-readable title for a URL. Best-effort, never raises."""
from __future__ import annotations

import re
from html import unescape

import httpx

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_OG_TITLE_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
UA = "Mozilla/5.0 (GetChatBot/1.0)"


async def _oembed_youtube(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await client.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
            timeout=10.0,
        )
        if r.status_code == 200:
            return (r.json().get("title") or "").strip() or None
    except Exception:
        return None
    return None


async def _html_title(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await client.get(url, headers={"User-Agent": UA}, timeout=10.0, follow_redirects=True)
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
    async with httpx.AsyncClient() as client:
        if kind == "youtube":
            t = await _oembed_youtube(client, url)
            if t:
                return t
        return await _html_title(client, url)
