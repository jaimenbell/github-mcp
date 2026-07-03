"""Read group: repo/issue/PR/file/user/commit lookups. Always enabled (no
env gate) -- these work unauthenticated (GitHub's 60 req/hr tier) and are
considered safe by default.

Every function returns a plain dict ({"ok": True, ...} or a structured
error) built from `client.get`, never raises. Base64 file-content decoding
happens here (get_file_content) since it's read-tool-specific, not a
generic client concern.
"""
from __future__ import annotations

import base64
import binascii

from .. import client

MAX_FILE_BYTES = 100_000


def get_repo(owner: str, repo: str) -> dict:
    """Metadata for a repository: description, language, stars, forks, open
    issues, default branch, archived flag, license, last-push time."""
    result = client.get("get_repo", f"/repos/{owner}/{repo}")
    if not result["ok"]:
        return result
    d = result["data"]
    return {
        "ok": True,
        "full_name": d.get("full_name"),
        "description": d.get("description"),
        "language": d.get("language"),
        "stargazers_count": d.get("stargazers_count"),
        "forks_count": d.get("forks_count"),
        "open_issues_count": d.get("open_issues_count"),
        "default_branch": d.get("default_branch"),
        "archived": d.get("archived"),
        "disabled": d.get("disabled"),
        "license": (d.get("license") or {}).get("spdx_id"),
        "pushed_at": d.get("pushed_at"),
        "html_url": d.get("html_url"),
    }


def list_issues(owner: str, repo: str, state: str = "open", limit: int = 20) -> dict:
    """List issues (pull requests filtered out), most-recently-updated first."""
    capped = max(1, min(limit, 50))
    result = client.get(
        "list_issues",
        f"/repos/{owner}/{repo}/issues",
        params={"state": state, "per_page": capped, "sort": "updated"},
    )
    if not result["ok"]:
        return result
    issues = [item for item in result["data"] if "pull_request" not in item]
    return {
        "ok": True,
        "issues": [
            {
                "number": i.get("number"),
                "title": i.get("title"),
                "state": i.get("state"),
                "user": (i.get("user") or {}).get("login"),
                "labels": [lbl.get("name") for lbl in i.get("labels", [])],
                "comments": i.get("comments"),
                "updated_at": i.get("updated_at"),
            }
            for i in issues
        ],
    }


def get_issue(owner: str, repo: str, issue_number: int) -> dict:
    """Fetch a single issue's full detail (title, body, state, labels, comments)."""
    result = client.get("get_issue", f"/repos/{owner}/{repo}/issues/{issue_number}")
    if not result["ok"]:
        return result
    d = result["data"]
    return {
        "ok": True,
        "number": d.get("number"),
        "title": d.get("title"),
        "body": d.get("body"),
        "state": d.get("state"),
        "user": (d.get("user") or {}).get("login"),
        "labels": [lbl.get("name") for lbl in d.get("labels", [])],
        "comments": d.get("comments"),
        "created_at": d.get("created_at"),
        "updated_at": d.get("updated_at"),
    }


def list_pull_requests(owner: str, repo: str, state: str = "open", limit: int = 20) -> dict:
    """List pull requests, most-recently-updated first."""
    capped = max(1, min(limit, 50))
    result = client.get(
        "list_pull_requests",
        f"/repos/{owner}/{repo}/pulls",
        params={"state": state, "per_page": capped, "sort": "updated"},
    )
    if not result["ok"]:
        return result
    return {
        "ok": True,
        "pull_requests": [
            {
                "number": p.get("number"),
                "title": p.get("title"),
                "state": p.get("state"),
                "user": (p.get("user") or {}).get("login"),
                "draft": p.get("draft"),
                "base": (p.get("base") or {}).get("ref"),
                "head": (p.get("head") or {}).get("ref"),
                "updated_at": p.get("updated_at"),
            }
            for p in result["data"]
        ],
    }


def get_pull_request(owner: str, repo: str, pr_number: int) -> dict:
    """Fetch a single pull request's full detail, including merge state."""
    result = client.get("get_pull_request", f"/repos/{owner}/{repo}/pulls/{pr_number}")
    if not result["ok"]:
        return result
    d = result["data"]
    return {
        "ok": True,
        "number": d.get("number"),
        "title": d.get("title"),
        "body": d.get("body"),
        "state": d.get("state"),
        "user": (d.get("user") or {}).get("login"),
        "draft": d.get("draft"),
        "mergeable": d.get("mergeable"),
        "merged": d.get("merged"),
        "base": (d.get("base") or {}).get("ref"),
        "head": (d.get("head") or {}).get("ref"),
        "updated_at": d.get("updated_at"),
    }


def get_file_content(owner: str, repo: str, path: str, ref: str | None = None) -> dict:
    """Read a UTF-8 text file from a repo at a given path (base64-decoded
    server-side). Returns a structured 'binary' marker instead of decoding
    non-UTF-8 content. Truncates past MAX_FILE_BYTES."""
    params = {"ref": ref} if ref else None
    result = client.get("get_file_content", f"/repos/{owner}/{repo}/contents/{path}", params=params)
    if not result["ok"]:
        return result
    d = result["data"]
    if isinstance(d, list):
        return {
            "ok": False,
            "error": {
                "type": "not_a_file",
                "message": f"'{path}' is a directory, not a file.",
                "tool": "get_file_content",
            },
        }
    if d.get("encoding") != "base64":
        return {
            "ok": False,
            "error": {
                "type": "unsupported_encoding",
                "message": f"Unsupported content encoding: {d.get('encoding')}",
                "tool": "get_file_content",
            },
        }
    raw = base64.b64decode(d.get("content", ""))
    try:
        text = raw.decode("utf-8")
        truncated = False
        if len(raw) > MAX_FILE_BYTES:
            text = raw[:MAX_FILE_BYTES].decode("utf-8", errors="ignore")
            truncated = True
        return {
            "ok": True,
            "path": d.get("path"),
            "size": d.get("size"),
            "content": text,
            "truncated": truncated,
            "binary": False,
        }
    except (UnicodeDecodeError, binascii.Error):
        return {
            "ok": True,
            "path": d.get("path"),
            "size": d.get("size"),
            "content": None,
            "truncated": False,
            "binary": True,
        }


def search_repos(query: str, limit: int = 10) -> dict:
    """Search public repositories by keyword/qualifiers, sorted by best match.
    Subject to GitHub's stricter search rate limit (10 req/min unauthenticated)."""
    capped = max(1, min(limit, 25))
    result = client.get("search_repos", "/search/repositories", params={"q": query, "per_page": capped})
    if not result["ok"]:
        return result
    d = result["data"]
    return {
        "ok": True,
        "total_count": d.get("total_count"),
        "items": [
            {
                "full_name": item.get("full_name"),
                "description": item.get("description"),
                "language": item.get("language"),
                "stargazers_count": item.get("stargazers_count"),
                "html_url": item.get("html_url"),
            }
            for item in d.get("items", [])
        ],
    }


def get_user(username: str) -> dict:
    """Public profile for a GitHub user or organization."""
    result = client.get("get_user", f"/users/{username}")
    if not result["ok"]:
        return result
    d = result["data"]
    return {
        "ok": True,
        "login": d.get("login"),
        "name": d.get("name"),
        "bio": d.get("bio"),
        "company": d.get("company"),
        "location": d.get("location"),
        "public_repos": d.get("public_repos"),
        "followers": d.get("followers"),
        "type": d.get("type"),
    }


def list_commits(owner: str, repo: str, limit: int = 20, sha: str | None = None) -> dict:
    """List commits on a repo's default branch (or `sha` ref), newest first."""
    capped = max(1, min(limit, 50))
    params = {"per_page": capped}
    if sha:
        params["sha"] = sha
    result = client.get("list_commits", f"/repos/{owner}/{repo}/commits", params=params)
    if not result["ok"]:
        return result
    return {
        "ok": True,
        "commits": [
            {
                "sha": c.get("sha"),
                "message": (c.get("commit") or {}).get("message"),
                "author": ((c.get("commit") or {}).get("author") or {}).get("name"),
                "date": ((c.get("commit") or {}).get("author") or {}).get("date"),
                "html_url": c.get("html_url"),
            }
            for c in result["data"]
        ],
    }
