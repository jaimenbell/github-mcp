#!/usr/bin/env python3
"""github-mcp -- public read+write reference MCP server over the GitHub
REST API (FastMCP).

Reference portfolio implementation, NOT the official GitHub MCP server --
see README's "what this is / is not" section.

Tool groups (see github_mcp.config): read (always on, works unauthenticated
at GitHub's 60 req/hr tier), write (env-gated GITHUB_MCP_ENABLE_WRITE, OFF
by default, also requires GITHUB_TOKEN). Every write-group tool enforces its
own gate + token precondition at the function level
(github_mcp.config.gated_write), so this file is thin wiring -- the safety
logic lives in config.py and is unit-tested independently of the MCP
transport.

Run: python run_server.py
"""
from __future__ import annotations

from fastmcp import FastMCP

from .groups import read, write

SERVER_NAME = "github-mcp"

mcp = FastMCP(SERVER_NAME)


# ---- read (always on) --------------------------------------------------

@mcp.tool(name="get_repo", description="Get metadata for a repository: description, language, stars, forks, open issues, default branch, archived flag, license, last-push time.")
async def get_repo_tool(owner: str, repo: str) -> dict:
    return read.get_repo(owner, repo)


@mcp.tool(name="list_issues", description="List issues for a repository (pull requests filtered out), most-recently-updated first.")
async def list_issues_tool(owner: str, repo: str, state: str = "open", limit: int = 20) -> dict:
    return read.list_issues(owner, repo, state=state, limit=limit)


@mcp.tool(name="get_issue", description="Fetch a single issue's full detail: title, body, state, labels, comment count.")
async def get_issue_tool(owner: str, repo: str, issue_number: int) -> dict:
    return read.get_issue(owner, repo, issue_number)


@mcp.tool(name="list_pull_requests", description="List pull requests for a repository, most-recently-updated first.")
async def list_pull_requests_tool(owner: str, repo: str, state: str = "open", limit: int = 20) -> dict:
    return read.list_pull_requests(owner, repo, state=state, limit=limit)


@mcp.tool(name="get_pull_request", description="Fetch a single pull request's full detail, including merge state.")
async def get_pull_request_tool(owner: str, repo: str, pr_number: int) -> dict:
    return read.get_pull_request(owner, repo, pr_number)


@mcp.tool(name="get_file_content", description="Read a UTF-8 text file from a repo at a given path (base64-decoded). Reports binary files rather than decoding them.")
async def get_file_content_tool(owner: str, repo: str, path: str, ref: str | None = None) -> dict:
    return read.get_file_content(owner, repo, path, ref=ref)


@mcp.tool(name="search_repos", description="Search public repositories by keyword/qualifiers, sorted by best match.")
async def search_repos_tool(query: str, limit: int = 10) -> dict:
    return read.search_repos(query, limit=limit)


@mcp.tool(name="get_user", description="Get a public profile for a GitHub user or organization.")
async def get_user_tool(username: str) -> dict:
    return read.get_user(username)


@mcp.tool(name="list_commits", description="List commits on a repo's default branch (or a given ref), newest first.")
async def list_commits_tool(owner: str, repo: str, limit: int = 20, sha: str | None = None) -> dict:
    return read.list_commits(owner, repo, limit=limit, sha=sha)


# ---- write (env-gated: GITHUB_MCP_ENABLE_WRITE, OFF by default; requires GITHUB_TOKEN) --

@mcp.tool(name="create_issue", description="Open a new issue on a repository. Requires GITHUB_MCP_ENABLE_WRITE=1 and GITHUB_TOKEN.")
async def create_issue_tool(owner: str, repo: str, title: str, body: str | None = None, labels: list[str] | None = None) -> dict:
    return write.create_issue(owner, repo, title, body=body, labels=labels)


@mcp.tool(name="comment_on_issue", description="Post a comment on an issue or pull request. Requires GITHUB_MCP_ENABLE_WRITE=1 and GITHUB_TOKEN.")
async def comment_on_issue_tool(owner: str, repo: str, issue_number: int, body: str) -> dict:
    return write.comment_on_issue(owner, repo, issue_number, body)


@mcp.tool(name="update_issue_state", description="Set an issue's state to 'open' or 'closed'. Requires GITHUB_MCP_ENABLE_WRITE=1 and GITHUB_TOKEN.")
async def update_issue_state_tool(owner: str, repo: str, issue_number: int, state: str) -> dict:
    return write.update_issue_state(owner, repo, issue_number, state)


@mcp.tool(name="add_labels", description="Add one or more labels to an issue or pull request. Requires GITHUB_MCP_ENABLE_WRITE=1 and GITHUB_TOKEN.")
async def add_labels_tool(owner: str, repo: str, issue_number: int, labels: list[str]) -> dict:
    return write.add_labels(owner, repo, issue_number, labels)


@mcp.tool(name="create_pr_review_comment", description="Create a review comment on a specific line of a pull request's diff. Requires GITHUB_MCP_ENABLE_WRITE=1 and GITHUB_TOKEN.")
async def create_pr_review_comment_tool(owner: str, repo: str, pr_number: int, body: str, commit_id: str, path: str, line: int) -> dict:
    return write.create_pr_review_comment(owner, repo, pr_number, body, commit_id, path, line)


if __name__ == "__main__":
    mcp.run()
