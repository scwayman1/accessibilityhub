"""Pilot hardening for the staging service: rate limits, HSTS, request logs.

* ``RateLimiter`` — a small in-process sliding window. The service runs one
  gunicorn worker (render.yaml), so process memory is the whole picture; a
  multi-worker deployment needs a shared store instead.
* ``harden`` — WSGI middleware that adds HSTS in hosted environments and
  writes one structured log line per request: method, path, status, and
  duration. Never query strings, form bodies, cookies, filenames, or document
  content.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import deque
from typing import Any, Callable

LOGGER = logging.getLogger("hub.request")
HSTS_VALUE = "max-age=31536000; includeSubDomains"


class RateLimiter:
    """Allow at most ``limit`` events per ``window`` seconds for each key."""

    def __init__(self, limit: int, window: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window = window
        self.clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> float | None:
        """Record one event. Returns None when allowed, else seconds until the next slot."""
        now = self.clock()
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and now - events[0] >= self.window:
                events.popleft()
            if len(events) >= self.limit:
                return max(self.window - (now - events[0]), 1.0)
            events.append(now)
            if len(self._events) > 10_000:  # bound memory under key churn
                for stale in [k for k, v in self._events.items() if not v or now - v[-1] >= self.window]:
                    del self._events[stale]
            return None


def client_address(environ: dict[str, Any], trust_proxy: bool) -> str:
    """The client IP. Behind Render's proxy the last X-Forwarded-For hop is the
    one the proxy itself appended; earlier hops are client-supplied."""
    if trust_proxy:
        forwarded = [part.strip() for part in str(environ.get("HTTP_X_FORWARDED_FOR") or "").split(",") if part.strip()]
        if forwarded:
            return forwarded[-1]
    return str(environ.get("REMOTE_ADDR") or "unknown")


def harden(app: Callable, hosted: bool) -> Callable:
    def application(environ: dict[str, Any], start_response: Callable):
        started = time.monotonic()
        request_id = uuid.uuid4().hex[:12]
        captured: dict[str, str] = {}

        def hardened_start_response(status: str, headers: list[tuple[str, str]], exc_info: Any = None):
            captured["status"] = status.split(" ", 1)[0]
            headers = list(headers)
            if hosted and not any(name.lower() == "strict-transport-security" for name, _ in headers):
                headers.append(("Strict-Transport-Security", HSTS_VALUE))
            return start_response(status, headers, exc_info) if exc_info else start_response(status, headers)

        try:
            return app(environ, hardened_start_response)
        finally:
            LOGGER.info(json.dumps({
                "request_id": request_id,
                "method": environ.get("REQUEST_METHOD"),
                "path": str(environ.get("PATH_INFO") or "")[:200],
                "status": captured.get("status", "error"),
                "ms": round((time.monotonic() - started) * 1000, 1),
            }))

    return application
