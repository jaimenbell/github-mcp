from __future__ import annotations

import httpx
import respx

from github_mcp import client, ratelimit


class _FakeClock:
    """Deterministic monotonic/wall clock + sleep that advances itself --
    lets tests assert on backoff behavior without ever really blocking."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start
        self.sleep_calls: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self.now += seconds


class TestTokenBucket:
    def test_allows_up_to_capacity_then_blocks(self):
        fc = _FakeClock()
        bucket = ratelimit.TokenBucket(rate_per_sec=3, clock=fc.clock)
        for _ in range(3):
            allowed, retry_after = bucket.try_acquire()
            assert allowed is True
            assert retry_after == 0.0
        allowed, retry_after = bucket.try_acquire()
        assert allowed is False
        assert retry_after > 0.0

    def test_refills_over_time(self):
        fc = _FakeClock()
        bucket = ratelimit.TokenBucket(rate_per_sec=2, clock=fc.clock)
        bucket.try_acquire()
        bucket.try_acquire()
        allowed, _ = bucket.try_acquire()
        assert allowed is False
        fc.now += 1.0  # full refill at rate_per_sec=2
        allowed, _ = bucket.try_acquire()
        assert allowed is True

    def test_reset_refills_to_full(self):
        fc = _FakeClock()
        bucket = ratelimit.TokenBucket(rate_per_sec=1, clock=fc.clock)
        bucket.try_acquire()
        allowed, _ = bucket.try_acquire()
        assert allowed is False
        bucket.reset()
        allowed, _ = bucket.try_acquire()
        assert allowed is True


class TestRateLimiterBurstCap:
    def test_before_request_sleeps_when_bucket_exhausted(self):
        fc = _FakeClock()
        limiter = ratelimit.RateLimiter(
            max_requests_per_sec=1, clock=fc.clock, wall_clock=fc.clock, sleep=fc.sleep
        )
        limiter.before_request()  # consumes the single starting token
        assert fc.sleep_calls == []
        limiter.before_request()  # bucket empty -> must sleep for a refill
        assert len(fc.sleep_calls) == 1
        assert fc.sleep_calls[0] > 0.0


class TestRateLimiterAdaptiveBackoff:
    def test_no_delay_when_no_quota_data_yet(self):
        fc = _FakeClock()
        limiter = ratelimit.RateLimiter(
            max_requests_per_sec=1000, clock=fc.clock, wall_clock=fc.clock, sleep=fc.sleep
        )
        limiter.before_request()
        assert fc.sleep_calls == []

    def test_no_delay_when_remaining_above_low_water_mark(self):
        fc = _FakeClock()
        limiter = ratelimit.RateLimiter(
            max_requests_per_sec=1000, clock=fc.clock, wall_clock=fc.clock, sleep=fc.sleep
        )
        limiter.record_response(
            httpx.Headers({"X-RateLimit-Remaining": "500", "X-RateLimit-Reset": str(int(fc.now) + 3600)})
        )
        limiter.before_request()
        assert fc.sleep_calls == []

    def test_low_remaining_quota_triggers_proportional_delay(self):
        """Remaining=2, 20s until reset -> ~10s/request, well under the cap."""
        fc = _FakeClock()
        limiter = ratelimit.RateLimiter(
            max_requests_per_sec=1000, clock=fc.clock, wall_clock=fc.clock, sleep=fc.sleep
        )
        limiter.record_response(
            httpx.Headers({"X-RateLimit-Remaining": "2", "X-RateLimit-Reset": str(int(fc.now) + 20)})
        )
        limiter.before_request()
        assert len(fc.sleep_calls) == 1
        assert 9.0 < fc.sleep_calls[0] <= 10.0

    def test_adaptive_delay_capped_at_max(self):
        """Remaining=1 an hour out would compute a huge delay -- must clamp
        to MAX_ADAPTIVE_DELAY_S rather than blocking the caller for ~1hr."""
        fc = _FakeClock()
        limiter = ratelimit.RateLimiter(
            max_requests_per_sec=1000, clock=fc.clock, wall_clock=fc.clock, sleep=fc.sleep
        )
        limiter.record_response(
            httpx.Headers({"X-RateLimit-Remaining": "1", "X-RateLimit-Reset": str(int(fc.now) + 3600)})
        )
        limiter.before_request()
        assert fc.sleep_calls == [ratelimit.MAX_ADAPTIVE_DELAY_S]

    def test_no_delay_once_reset_has_passed(self):
        fc = _FakeClock()
        limiter = ratelimit.RateLimiter(
            max_requests_per_sec=1000, clock=fc.clock, wall_clock=fc.clock, sleep=fc.sleep
        )
        limiter.record_response(
            httpx.Headers({"X-RateLimit-Remaining": "1", "X-RateLimit-Reset": str(int(fc.now) - 5)})
        )
        limiter.before_request()
        assert fc.sleep_calls == []

    def test_malformed_or_missing_headers_ignored(self):
        fc = _FakeClock()
        limiter = ratelimit.RateLimiter(
            max_requests_per_sec=1000, clock=fc.clock, wall_clock=fc.clock, sleep=fc.sleep
        )
        limiter.record_response(httpx.Headers({}))
        limiter.record_response(httpx.Headers({"X-RateLimit-Remaining": "not-a-number"}))
        limiter.before_request()
        assert fc.sleep_calls == []

    def test_reset_clears_quota_state(self):
        fc = _FakeClock()
        limiter = ratelimit.RateLimiter(
            max_requests_per_sec=1000, clock=fc.clock, wall_clock=fc.clock, sleep=fc.sleep
        )
        limiter.record_response(
            httpx.Headers({"X-RateLimit-Remaining": "1", "X-RateLimit-Reset": str(int(fc.now) + 3600)})
        )
        limiter.reset()
        limiter.before_request()
        assert fc.sleep_calls == []


class TestClientIntegration:
    @respx.mock
    def test_request_consults_and_updates_singleton_rate_limiter(self, monkeypatch):
        fc = _FakeClock()
        test_limiter = ratelimit.RateLimiter(
            max_requests_per_sec=1000, clock=fc.clock, wall_clock=fc.clock, sleep=fc.sleep
        )
        monkeypatch.setattr(ratelimit, "RATE_LIMITER", test_limiter)
        monkeypatch.setattr(client, "ratelimit", ratelimit)

        respx.get("https://api.github.com/repos/o/r").mock(
            return_value=httpx.Response(
                200,
                json={"full_name": "o/r"},
                headers={"X-RateLimit-Remaining": "1", "X-RateLimit-Reset": str(int(fc.now) + 3600)},
            )
        )
        result = client.get("get_repo", "/repos/o/r")
        assert result["ok"] is True

        # Quota state from the response was recorded onto the limiter.
        assert test_limiter._quota.remaining == 1

        # A second call should now hit the adaptive low-water-mark backoff.
        respx.get("https://api.github.com/repos/o/r2").mock(return_value=httpx.Response(200, json={}))
        client.get("get_repo", "/repos/o/r2")
        assert len(fc.sleep_calls) == 1
        assert fc.sleep_calls[0] == ratelimit.MAX_ADAPTIVE_DELAY_S
