"""Unit tests for the T9 demo rate limiter (app/services/rate_limit.py).

Pure function, no I/O — the sliding window is driven entirely by an injected
`now`, so these tests never sleep.
"""

from __future__ import annotations

import pytest

from app.services.rate_limit import RateLimitExceeded, check_rate_limit, reset_rate_limits


@pytest.fixture(autouse=True)
def _clean_limiter() -> None:
    reset_rate_limits()


def test_allows_up_to_max_requests_in_window() -> None:
    for i in range(5):
        check_rate_limit("ip:1", max_requests=5, window_seconds=60.0, now=float(i))
    with pytest.raises(RateLimitExceeded):
        check_rate_limit("ip:1", max_requests=5, window_seconds=60.0, now=5.0)


def test_keys_are_independent() -> None:
    for i in range(5):
        check_rate_limit("ip:1", max_requests=5, window_seconds=60.0, now=float(i))
    # A different key has its own budget.
    check_rate_limit("ip:2", max_requests=5, window_seconds=60.0, now=0.0)


def test_old_hits_fall_out_of_the_sliding_window() -> None:
    for i in range(5):
        check_rate_limit("ip:1", max_requests=5, window_seconds=60.0, now=float(i))
    # 61s later, all 5 earlier hits are outside the window -> allowed again.
    check_rate_limit("ip:1", max_requests=5, window_seconds=60.0, now=61.0)


def test_rate_limit_exceeded_carries_the_key() -> None:
    check_rate_limit("ip:9", max_requests=1, window_seconds=60.0, now=0.0)
    with pytest.raises(RateLimitExceeded) as excinfo:
        check_rate_limit("ip:9", max_requests=1, window_seconds=60.0, now=0.0)
    assert excinfo.value.key == "ip:9"
