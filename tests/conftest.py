"""Shared fixtures: every test gets a clean env-gate slate so gate/token
tests never leak state across tests."""
from __future__ import annotations

import pytest

from github_mcp import ratelimit

_GATE_ENV_VARS = [
    "GITHUB_MCP_ENABLE_WRITE",
    "GITHUB_TOKEN",
    "GITHUB_MCP_MAX_REQUESTS_PER_SEC",
]


@pytest.fixture(autouse=True)
def _clean_gate_state(monkeypatch):
    for var in _GATE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """The module-level RATE_LIMITER singleton is shared process-wide; reset
    its bucket/quota state before each test so accumulated calls from other
    tests never cause a real (even if tiny) sleep here."""
    ratelimit.RATE_LIMITER.reset()
    yield


@pytest.fixture
def enable_write(monkeypatch):
    monkeypatch.setenv("GITHUB_MCP_ENABLE_WRITE", "1")


@pytest.fixture
def with_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "github_pat_fake_test_token_1234")


@pytest.fixture
def write_ready(monkeypatch):
    """write group enabled AND a token present -- the only state where write
    tools actually reach the network."""
    monkeypatch.setenv("GITHUB_MCP_ENABLE_WRITE", "1")
    monkeypatch.setenv("GITHUB_TOKEN", "github_pat_fake_test_token_1234")
