"""Real-network smoke test. Skipped unless GITHUB_MCP_LIVE=1.

Read-only, targets a stable public repo. No write smoke exists anywhere in
this suite by design -- write tools are exercised only via respx mocks (see
test_write.py); this project never creates real issues/comments as part of
its own test run.
"""
from __future__ import annotations

import os

import pytest

from github_mcp.groups import read

LIVE = os.environ.get("GITHUB_MCP_LIVE") == "1"
pytestmark = pytest.mark.skipif(not LIVE, reason="set GITHUB_MCP_LIVE=1 to run real-network smoke tests")


@pytest.mark.live
def test_live_get_repo_real_json():
    result = read.get_repo("octocat", "Hello-World")
    assert result["ok"] is True, result
    assert result["full_name"] == "octocat/Hello-World"
    assert isinstance(result["stargazers_count"], int)
    assert result["stargazers_count"] >= 0
