"""Proactive client-side rate limiting for github-mcp.

Previously client.py only reacted to GitHub's 403 rate-limit response after
the request had already gone out (`_is_rate_limit_response`). A runaway loop
-- an LLM retrying `search_repos`/`list_issues` in a tight loop, say -- could
burn the full hourly quota or trip GitHub's secondary abuse-detection
heuristics with no backoff, risking a temporary token ban.

This module adds two proactive layers, both consulted from client.request()
before every outgoing request:

1. TokenBucket burst cap -- mirrors desktop-mcp's `config.TokenBucket`
   (thread-safe, continuous refill). Throttles raw request rate before any
   GitHub quota data exists, so a tight retry loop never fires faster than
   `max_requests_per_sec`.
2. Adaptive header-based backoff -- GitHub attaches X-RateLimit-Remaining
   and X-RateLimit-Reset to every core REST response, success or failure.
   RateLimiter remembers the latest values; once remaining quota drops to or
   below LOW_WATER_MARK, it spreads the remaining budget evenly across the
   time left until reset instead of letting the caller burn through the last
   few requests in a burst that trips secondary abuse detection.

Both layers sleep synchronously (this is a sync httpx client) via injectable
clock/sleep hooks so tests can simulate elapsed time without ever actually
blocking.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable

DEFAULT_MAX_REQUESTS_PER_SEC = 5.0
LOW_WATER_MARK = 10          # start adaptive backoff once remaining <= this
MAX_ADAPTIVE_DELAY_S = 20.0  # cap on any single proactive delay


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        val = float(raw)
        return val if val > 0 else default
    except ValueError:
        return default


def get_max_requests_per_sec() -> float:
    return _env_float("GITHUB_MCP_MAX_REQUESTS_PER_SEC", DEFAULT_MAX_REQUESTS_PER_SEC)


@dataclass
class TokenBucket:
    """Simple token-bucket rate limiter (mirrors desktop-mcp's
    config.TokenBucket). Capacity == rate_per_sec, refills continuously at
    rate_per_sec tokens/sec. Thread-safe; a monotonic clock is injected so
    tests can simulate elapsed time deterministically."""

    rate_per_sec: float
    clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)
    _lock: Lock = field(init=False, default_factory=Lock, repr=False)

    def __post_init__(self) -> None:
        self._tokens = float(self.rate_per_sec)
        self._last_refill = self.clock()

    def _refill(self) -> None:
        now = self.clock()
        elapsed = now - self._last_refill
        self._last_refill = now
        self._tokens = min(self.rate_per_sec, self._tokens + elapsed * self.rate_per_sec)

    def try_acquire(self) -> tuple[bool, float]:
        """Attempt to consume one token. Returns (allowed, retry_after_s)."""
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True, 0.0
            deficit = 1.0 - self._tokens
            retry_after = deficit / self.rate_per_sec if self.rate_per_sec > 0 else float("inf")
            return False, retry_after

    def reset(self) -> None:
        with self._lock:
            self._tokens = float(self.rate_per_sec)
            self._last_refill = self.clock()


@dataclass
class _QuotaState:
    remaining: int | None = None
    reset_epoch: int | None = None

    def update(self, remaining: int, reset_epoch: int) -> None:
        self.remaining = remaining
        self.reset_epoch = reset_epoch

    def clear(self) -> None:
        self.remaining = None
        self.reset_epoch = None


class RateLimiter:
    """Gate consulted before every outgoing request. Combines a burst-cap
    TokenBucket with adaptive header-based backoff. `clock`/`wall_clock`/
    `sleep` are injectable so tests never actually block."""

    def __init__(
        self,
        *,
        max_requests_per_sec: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._clock = clock
        self._wall_clock = wall_clock
        self._sleep = sleep
        self._rate = max_requests_per_sec or get_max_requests_per_sec()
        self._bucket = TokenBucket(rate_per_sec=self._rate, clock=clock)
        self._quota = _QuotaState()
        self._quota_lock = Lock()

    def before_request(self) -> None:
        """Block (via the injected sleep hook) until both the burst cap and
        the adaptive header-based backoff allow the next request through."""
        allowed, retry_after = self._bucket.try_acquire()
        while not allowed:
            self._sleep(retry_after)
            allowed, retry_after = self._bucket.try_acquire()

        delay = self._adaptive_delay()
        if delay > 0:
            self._sleep(delay)

    def _adaptive_delay(self) -> float:
        with self._quota_lock:
            remaining, reset_epoch = self._quota.remaining, self._quota.reset_epoch
        if remaining is None or reset_epoch is None or remaining > LOW_WATER_MARK:
            return 0.0
        time_left = reset_epoch - self._wall_clock()
        if time_left <= 0:
            return 0.0
        per_request = time_left / max(remaining, 1)
        return min(per_request, MAX_ADAPTIVE_DELAY_S)

    def record_response(self, headers) -> None:
        """Remember the quota state GitHub reported on the response that just
        came back (present on every core REST response, success or 4xx)."""
        remaining = headers.get("X-RateLimit-Remaining")
        reset_epoch = headers.get("X-RateLimit-Reset")
        if remaining is None or reset_epoch is None:
            return
        if not (remaining.isdigit() and reset_epoch.isdigit()):
            return
        with self._quota_lock:
            self._quota.update(int(remaining), int(reset_epoch))

    def reset(self) -> None:
        """Test helper: clear bucket + quota state so tests never leak
        throttling state into each other."""
        self._bucket.reset()
        with self._quota_lock:
            self._quota.clear()


# Module-level singleton consulted by every client.request() call.
RATE_LIMITER = RateLimiter()
