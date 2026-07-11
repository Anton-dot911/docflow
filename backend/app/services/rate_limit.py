"""Conservative per-IP rate limiter for public demo endpoints (T9).

In-memory sliding-window counter — no new infra (Redis) for a portfolio demo;
counters reset on process restart, which is acceptable (see docs/decisions.md).
Applied only to requests that touch the fixed demo dataset (`app/demo_data.py`),
never to normal traffic, so it cannot throttle real customers.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from app.config import DEMO_RATE_LIMIT_MAX_REQUESTS, DEMO_RATE_LIMIT_WINDOW_SECONDS

_hits: dict[str, deque[float]] = defaultdict(deque)


class RateLimitExceeded(Exception):
    """`key` made too many demo requests within the sliding window."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"rate limit exceeded for {key}")


def check_rate_limit(
    key: str,
    *,
    max_requests: int = DEMO_RATE_LIMIT_MAX_REQUESTS,
    window_seconds: float = DEMO_RATE_LIMIT_WINDOW_SECONDS,
    now: float | None = None,
) -> None:
    """Record one hit for `key`; raise RateLimitExceeded if over the limit.

    Sliding window: hits older than `window_seconds` are dropped before
    counting, so the limit is "at most `max_requests` in the last
    `window_seconds`" rather than a fixed-bucket approximation.
    """
    now = now if now is not None else time.monotonic()
    window_start = now - window_seconds
    hits = _hits[key]
    while hits and hits[0] < window_start:
        hits.popleft()
    if len(hits) >= max_requests:
        raise RateLimitExceeded(key)
    hits.append(now)


def reset_rate_limits() -> None:
    """Test helper: clear all counters between tests."""
    _hits.clear()
