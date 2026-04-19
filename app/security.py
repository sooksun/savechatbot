"""Cross-cutting HTTP security: Origin/Referer CSRF check + rate limiting."""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# Paths exempt from CSRF (server-to-server callers that verify signatures themselves).
_CSRF_EXEMPT_PREFIXES = ("/webhook",)


def _allowed_origin_hosts() -> set[str]:
    hosts: set[str] = set()
    try:
        u = urlparse(settings.APP_BASE_URL)
        if u.hostname:
            hosts.add(u.hostname.lower())
    except Exception:
        pass
    return hosts


class CSRFGuardMiddleware(BaseHTTPMiddleware):
    """Double-check Origin/Referer on unsafe requests.

    Session cookie is SameSite=Lax, so cross-site POSTs are already blocked in
    modern browsers. This middleware is a second line of defence: when an
    Origin/Referer header is present on an unsafe method, its host MUST match
    APP_BASE_URL. Missing headers (e.g. from server-side callers) are allowed
    only when the request also lacks the session cookie — authenticated
    browser requests always send at least Referer.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method in _UNSAFE_METHODS and not request.url.path.startswith(_CSRF_EXEMPT_PREFIXES):
            allowed = _allowed_origin_hosts()
            origin = request.headers.get("origin") or ""
            referer = request.headers.get("referer") or ""
            header_host = None
            source = origin or referer
            if source:
                try:
                    header_host = (urlparse(source).hostname or "").lower()
                except Exception:
                    header_host = None
            has_session = bool(request.cookies.get("session"))
            if has_session and allowed and header_host not in allowed:
                log.warning(
                    "CSRF block: method=%s path=%s origin=%s referer=%s",
                    request.method, request.url.path, origin, referer,
                )
                return JSONResponse({"detail": "CSRF check failed"}, status_code=403)
        return await call_next(request)
