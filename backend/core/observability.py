"""Structured logging and lightweight, free request metrics.

- Every log line can be JSON (``CLOUDOPS_LOG_FORMAT=json``, the default on
  Vercel) with the request id, so one request can be followed across lines
  in the Vercel log viewer. Locally the default is readable text.
- Request metrics are counted in process memory: no paid service, no
  database write per request. On serverless each instance keeps its own
  counts, so the ops page labels them "this instance since it started".
- Nothing here logs request bodies, cookies, headers or query strings, so
  passwords, session tokens and API keys cannot end up in logs.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import threading
import time
from collections import Counter, deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, Optional

from core import config

request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("request_id", default=None)

_STANDARD_ATTRS = set(vars(logging.LogRecord("x", 0, "x", 0, "x", None, None))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """One JSON object per line: time, level, logger, message, request id and extras."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id_text = request_id_var.get() or "-"
        return True


_configured = False


def log_format() -> str:
    value = (os.environ.get("CLOUDOPS_LOG_FORMAT") or "").strip().lower()
    if value in ("json", "text"):
        return value
    return "json" if config.is_serverless() else "text"


def configure_logging() -> None:
    """Attach one handler to the ``cloudops`` logger tree. Safe to call twice."""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    if log_format() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.addFilter(_RequestIdFilter())
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id_text)s] %(message)s"))
    root = logging.getLogger("cloudops")
    root.addHandler(handler)
    root.setLevel((os.environ.get("CLOUDOPS_LOG_LEVEL") or "INFO").upper())
    root.propagate = False
    _configured = True


class RequestStats:
    """Counts and recent latencies for this process."""

    def __init__(self, window: int = 500) -> None:
        self._lock = threading.Lock()
        self.started_at = datetime.now(timezone.utc)
        self._started = time.monotonic()
        self.total = 0
        self.by_status: Counter[str] = Counter()
        self.by_route: Counter[str] = Counter()
        self.errors_by_route: Counter[str] = Counter()
        self.unavailable = 0
        self._durations: Deque[float] = deque(maxlen=window)

    def record(self, route: str, status: int, duration_ms: float) -> None:
        with self._lock:
            self.total += 1
            self.by_status["%dxx" % (status // 100)] += 1
            self.by_route[route] += 1
            # 503 is the app's deliberate "AWS or database unavailable" answer,
            # not a crash, so it is counted apart from real server errors.
            if status == 503:
                self.unavailable += 1
            elif status >= 500:
                self.errors_by_route[route] += 1
            self._durations.append(duration_ms)

    @staticmethod
    def _percentile(values: list, fraction: float) -> Optional[float]:
        if not values:
            return None
        ordered = sorted(values)
        index = min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))
        return round(ordered[index], 1)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            durations = list(self._durations)
            return {
                "scope": "this instance since it started",
                "started_at": self.started_at.isoformat(),
                "uptime_seconds": round(time.monotonic() - self._started),
                "total_requests": self.total,
                "by_status_class": dict(self.by_status),
                "server_errors": sum(self.errors_by_route.values()),
                "dependency_unavailable": self.unavailable,
                "latency_ms": {"p50": self._percentile(durations, 0.5), "p95": self._percentile(durations, 0.95),
                               "samples": len(durations)},
                "top_routes": [{"route": r, "requests": n, "server_errors": self.errors_by_route.get(r, 0)}
                               for r, n in self.by_route.most_common(8)],
            }

    def reset(self) -> None:
        self.__init__(self._durations.maxlen or 500)  # type: ignore[misc]


stats = RequestStats()
access_logger = logging.getLogger("cloudops.access")


def record_request(method: str, route: str, status: int, duration_ms: float) -> None:
    stats.record(route, status, duration_ms)
    level = logging.WARNING if status >= 500 and status != 503 else logging.INFO
    if route in ("/health", "/health/ready") and status < 500:
        level = logging.DEBUG
    access_logger.log(level, "%s %s %d %.1fms", method, route, status, duration_ms,
                      extra={"http_method": method, "route": route, "status": status,
                             "duration_ms": round(duration_ms, 1)})


def build_info() -> Dict[str, Any]:
    sha = os.environ.get("VERCEL_GIT_COMMIT_SHA") or os.environ.get("GIT_COMMIT_SHA") or ""
    return {
        "version": os.environ.get("CLOUDOPS_VERSION") or "1.0.0",
        "commit": sha[:7] or None,
        "environment": os.environ.get("VERCEL_ENV") or ("serverless" if config.is_serverless() else "local"),
        "python": "%d.%d.%d" % sys.version_info[:3],
        "log_format": log_format(),
    }
