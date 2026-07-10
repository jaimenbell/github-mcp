"""Thin sync httpx wrapper around api.github.com.

One function per HTTP verb used by the tool groups (get/post/patch). Auth
header injection when a token is present; degrades to GitHub's unauthenticated
60 req/hr tier otherwise. GitHub's 403 primary rate-limit response (hourly
quota, X-RateLimit-Reset) and secondary rate-limit response (abuse-detection
heuristics, Retry-After) both surface as a typed `rate_limited` error; any
other 4xx/5xx surfaces as a typed `github_api_error` -- never a raw
exception/crash. A dedicated httpx.Client is created per call so tests can
respx-mock deterministically without managing a shared client lifecycle
across the process.

Every request also passes through `ratelimit.RATE_LIMITER` (see
ratelimit.py) before it's sent -- a proactive client-side throttle so a
runaway caller can't burn the hourly quota or trip GitHub's secondary
abuse-detection heuristics before a 403 ever comes back.
"""
from __future__ import annotations

import json as json_module
from typing import Any

import httpx

from . import config, ratelimit

DEFAULT_TIMEOUT_S = 10.0


def _headers() -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "github-mcp",
    }
    token = config.get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _rate_limit_error(tool: str, response: httpx.Response) -> dict:
    reset_header = response.headers.get("X-RateLimit-Reset")
    remaining = response.headers.get("X-RateLimit-Remaining")
    retry_after = response.headers.get("Retry-After")
    if reset_header:
        message = f"GitHub API rate limit exceeded. Resets at unix time {reset_header}."
    elif retry_after:
        # GitHub's secondary rate limit: no X-RateLimit-* headers, just Retry-After.
        message = f"GitHub API secondary rate limit exceeded. Retry after {retry_after}s."
    else:
        message = "GitHub API rate limit exceeded."
    return {
        "ok": False,
        "error": {
            "type": "rate_limited",
            "message": message,
            "tool": tool,
            "status_code": response.status_code,
            "reset_time": int(reset_header) if reset_header and reset_header.isdigit() else None,
            "remaining": int(remaining) if remaining and remaining.isdigit() else None,
            "retry_after_s": int(retry_after) if retry_after and retry_after.isdigit() else None,
        },
    }


def _api_error(tool: str, response: httpx.Response) -> dict:
    try:
        body = response.json()
        message = body.get("message", response.text)
    except (json_module.JSONDecodeError, ValueError):
        message = response.text or f"HTTP {response.status_code}"
    return {
        "ok": False,
        "error": {
            "type": "github_api_error",
            "message": message,
            "tool": tool,
            "status_code": response.status_code,
        },
    }


def _is_rate_limit_response(response: httpx.Response) -> bool:
    """True for GitHub's primary rate limit (403 + X-RateLimit-Remaining: 0)
    and its secondary rate limit (403 + Retry-After, no X-RateLimit-Remaining
    -- triggered by abuse-detection/concurrency/rapid-write heuristics rather
    than the hourly quota)."""
    if response.status_code != 403:
        return False
    if response.headers.get("X-RateLimit-Remaining") == "0":
        return True
    return "Retry-After" in response.headers


def _handle_response(tool: str, response: httpx.Response) -> dict:
    if _is_rate_limit_response(response):
        return _rate_limit_error(tool, response)
    if response.status_code >= 400:
        return _api_error(tool, response)
    try:
        data = response.json() if response.content else {}
    except (json_module.JSONDecodeError, ValueError) as exc:
        return {
            "ok": False,
            "error": {
                "type": "decode_error",
                "message": f"GitHub returned non-JSON content: {exc}",
                "tool": tool,
                "status_code": response.status_code,
            },
        }
    return {"ok": True, "data": data, "status_code": response.status_code}


def request(
    tool: str,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
) -> dict:
    """Issue one request to api.github.com and return a structured result:
    {"ok": True, "data": ..., "status_code": ...} on success, or
    {"ok": False, "error": {...}} on any 4xx/5xx/decode failure. Network-level
    exceptions (timeout, connection refused, DNS failure) AND malformed-URL
    errors (e.g. a caller-supplied owner/repo/path containing characters that
    make the assembled URL invalid) are also caught and surfaced as a typed
    error rather than propagating -- the tool caller always gets a dict back,
    never an exception. `httpx.InvalidURL` does not subclass `httpx.HTTPError`
    (it's raised during URL construction, before any network I/O), so it is
    listed explicitly -- omitting it would let a bad path/owner/repo value
    crash the call instead of returning a clean error."""
    url = f"{config.GITHUB_API_BASE}{path}"
    ratelimit.RATE_LIMITER.before_request()
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT_S) as client:
            response = client.request(method, url, headers=_headers(), params=params, json=json)
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        return {
            "ok": False,
            "error": {
                "type": "network_error",
                "message": str(exc),
                "tool": tool,
            },
        }
    ratelimit.RATE_LIMITER.record_response(response.headers)
    return _handle_response(tool, response)


def get(tool: str, path: str, *, params: dict[str, Any] | None = None) -> dict:
    return request(tool, "GET", path, params=params)


def post(tool: str, path: str, *, json: dict[str, Any] | None = None) -> dict:
    return request(tool, "POST", path, json=json)


def patch(tool: str, path: str, *, json: dict[str, Any] | None = None) -> dict:
    return request(tool, "PATCH", path, json=json)
