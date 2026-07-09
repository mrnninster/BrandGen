"""Log HTTP requests to stdout (visible in Render web service logs)."""

from __future__ import annotations

import logging
import time

logger = logging.getLogger("brandgen.request")

_SKIP_PREFIXES = ("/static/", "/favicon.ico", "/api/jobs/", "/healthz")


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.get_full_path()
        if path.startswith(_SKIP_PREFIXES):
            return self.get_response(request)

        started = time.monotonic()
        logger.info("→ %s %s", request.method, path)
        try:
            response = self.get_response(request)
        except Exception:
            logger.exception("Unhandled exception %s %s", request.method, path)
            raise

        duration_ms = (time.monotonic() - started) * 1000
        level = logging.ERROR if response.status_code >= 500 else logging.INFO
        logger.log(
            level,
            "← %s %s status=%s duration=%.0fms",
            request.method,
            path,
            response.status_code,
            duration_ms,
        )
        return response
