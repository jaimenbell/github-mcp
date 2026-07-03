"""Write group: issue/PR mutations. Env-gated behind GITHUB_MCP_ENABLE_WRITE
(OFF by default) AND requires GITHUB_TOKEN -- both preconditions enforced by
`config.gated_write` at the source, so a disabled group or missing token
returns a structured refusal before any network call is attempted.
"""
from __future__ import annotations

from .. import client, config


@config.gated_write
def create_issue(owner: str, repo: str, title: str, body: str | None = None, labels: list[str] | None = None) -> dict:
    """Open a new issue on a repository."""
    payload: dict = {"title": title}
    if body is not None:
        payload["body"] = body
    if labels:
        payload["labels"] = labels
    result = client.post("create_issue", f"/repos/{owner}/{repo}/issues", json=payload)
    if not result["ok"]:
        return result
    d = result["data"]
    return {"ok": True, "number": d.get("number"), "html_url": d.get("html_url"), "state": d.get("state")}


@config.gated_write
def comment_on_issue(owner: str, repo: str, issue_number: int, body: str) -> dict:
    """Post a comment on an issue or pull request (PRs are issues in GitHub's
    comments API)."""
    result = client.post(
        "comment_on_issue",
        f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
        json={"body": body},
    )
    if not result["ok"]:
        return result
    d = result["data"]
    return {"ok": True, "id": d.get("id"), "html_url": d.get("html_url")}


@config.gated_write
def update_issue_state(owner: str, repo: str, issue_number: int, state: str) -> dict:
    """Set an issue's state to 'open' or 'closed'."""
    if state not in ("open", "closed"):
        return {
            "ok": False,
            "error": {
                "type": "invalid_input",
                "message": f"state must be 'open' or 'closed', got '{state}'",
                "tool": "update_issue_state",
            },
        }
    result = client.patch(
        "update_issue_state",
        f"/repos/{owner}/{repo}/issues/{issue_number}",
        json={"state": state},
    )
    if not result["ok"]:
        return result
    d = result["data"]
    return {"ok": True, "number": d.get("number"), "state": d.get("state")}


@config.gated_write
def add_labels(owner: str, repo: str, issue_number: int, labels: list[str]) -> dict:
    """Add one or more labels to an issue or pull request."""
    result = client.post(
        "add_labels",
        f"/repos/{owner}/{repo}/issues/{issue_number}/labels",
        json={"labels": labels},
    )
    if not result["ok"]:
        return result
    return {"ok": True, "labels": [lbl.get("name") for lbl in result["data"]]}


@config.gated_write
def create_pr_review_comment(owner: str, repo: str, pr_number: int, body: str, commit_id: str, path: str, line: int) -> dict:
    """Create a review comment on a specific line of a pull request's diff."""
    payload = {"body": body, "commit_id": commit_id, "path": path, "line": line}
    result = client.post(
        "create_pr_review_comment",
        f"/repos/{owner}/{repo}/pulls/{pr_number}/comments",
        json=payload,
    )
    if not result["ok"]:
        return result
    d = result["data"]
    return {"ok": True, "id": d.get("id"), "html_url": d.get("html_url")}
