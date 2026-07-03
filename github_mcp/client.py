"""Thin sync httpx wrapper around api.github.com.

One function per HTTP verb used by the tool groups (get/post/patch). Auth
header injection when a token is present; degrades to GitHub's unauthenticated
60 req/hr tier otherwise. GitHub's 403 primary-rate-limit response and any
4xx/5xx surface as clean typed error dicts (never a raw exception/crash),
carrying the rate-limit reset time when GitHub provides one. A dedicated
httpx.Client is created per call so tests can respx-mock deterministically
without managing a shared client lifecycle across the process.
"""
from __future__ import annotations

import json as json_module
from typing import Any

import httpx

from . import config

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
    return {
        "ok": False,
        "error": {
            "type": "rate_limited",
            "message": (
                "GitHub API rate limit exceeded. "
                + (f"Resets at unix time {reset_header}." if reset_header else "")
            ),
            "tool": tool,
            "status_code": response.status_code,
            "reset_time": int(reset_header) if reset_header and reset_header.isdigit() else None,
            "remaining": int(remaining) if remaining and remaining.isdigit() else None,
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
    if response.status_code != 403:
        return False
    remaining = response.headers.get("X-RateLimit-Remaining")
    return remaining == "0"


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
    exceptions (timeout, connection refused, DNS failure) are also caught and
    surfaced as a typed error rather than propagating -- the tool caller
    always gets a dict back, never an exception."""
    url = f"{config.GITHUB_API_BASE}{path}"
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT_S) as client:
            response = client.request(method, url, headers=_headers(), params=params, json=json)
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "error": {
                "type": "network_error",
                "message": str(exc),
                "tool": tool,
            },
        }
    return _handle_response(tool, response)


def get(tool: str, path: str, *, params: dict[str, Any] | None = None) -> dict:
    return request(tool, "GET", path, params=params)


def post(tool: str, path: str, *, json: dict[str, Any] | None = None) -> dict:
    return request(tool, "POST", path, json=json)


def patch(tool: str, path: str, *, json: dict[str, Any] | None = None) -> dict:
    return request(tool, "PATCH", path, json=json)
