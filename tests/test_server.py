from __future__ import annotations

import asyncio

from github_mcp.server import mcp

EXPECTED_READ_TOOLS = {
    "get_repo",
    "list_issues",
    "get_issue",
    "list_pull_requests",
    "get_pull_request",
    "get_file_content",
    "search_repos",
    "get_user",
    "list_commits",
}

EXPECTED_WRITE_TOOLS = {
    "create_issue",
    "comment_on_issue",
    "update_issue_state",
    "add_labels",
    "create_pr_review_comment",
}


def _list_tool_names() -> set[str]:
    tools = asyncio.run(mcp.list_tools())
    return {t.name for t in tools}


class TestHandshake:
    def test_all_v1_tools_registered(self):
        names = _list_tool_names()
        assert EXPECTED_READ_TOOLS <= names
        assert EXPECTED_WRITE_TOOLS <= names

    def test_tool_count(self):
        names = _list_tool_names()
        assert len(names) == len(EXPECTED_READ_TOOLS) + len(EXPECTED_WRITE_TOOLS)

    def test_every_tool_has_a_description(self):
        tools = asyncio.run(mcp.list_tools())
        for tool in tools:
            assert tool.description, f"{tool.name} has no description"
