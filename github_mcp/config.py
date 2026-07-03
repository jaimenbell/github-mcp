"""Config/safety layer for github-mcp.

Tool-group gating + token loading + structured refusal/error payloads. This
is the server's own defense-in-depth layer: even if a caller gets past
harness permission prompts, the server itself refuses write actions unless
GITHUB_MCP_ENABLE_WRITE=1 is set, and never proceeds with a write call that
lacks a token -- mirroring desktop-mcp's config.gated pattern.

Groups:
  read  -- repo/issue/PR/file/user/commit lookups (always on, works
           unauthenticated at GitHub's 60 req/hr tier)
  write -- issue/PR-comment mutations (env-gated, OFF by default, requires
           GITHUB_TOKEN)

Env vars:
  GITHUB_MCP_ENABLE_WRITE=1 -- enable the write group
  GITHUB_TOKEN              -- fine-grained PAT; read works without it
                               (degraded unauth rate), write requires it
"""
from __future__ import annotations

import os

GROUP_READ = "read"
GROUP_WRITE = "write"

_ENV_GATES = {
    GROUP_WRITE: "GITHUB_MCP_ENABLE_WRITE",
}

GITHUB_API_BASE = "https://api.github.com"


def _env_truthy(name: str) -> bool:
    val = os.environ.get(name, "")
    return val.strip().lower() in ("1", "true", "yes", "on")


def group_enabled(group: str) -> bool:
    """read is always on; write requires its env gate."""
    if group == GROUP_READ:
        return True
    env_name = _ENV_GATES.get(group)
    if env_name is None:
        return False
    return _env_truthy(env_name)


def get_token() -> str | None:
    """Fine-grained PAT from GITHUB_TOKEN, or None. Never logged; callers
    must not include this value in any error payload or diagnostic."""
    token = os.environ.get("GITHUB_TOKEN")
    return token if token else None


def mask_token(token: str | None) -> str:
    """Masked representation safe to include in diagnostics -- last 4 chars
    only, never the full token."""
    if not token:
        return "(none)"
    if len(token) <= 4:
        return "*" * len(token)
    return f"...{token[-4:]}"


def policy_refusal(group: str, tool: str) -> dict:
    """Structured refusal payload for a disabled tool group."""
    env_name = _ENV_GATES.get(group, f"GITHUB_MCP_ENABLE_{group.upper()}")
    return {
        "ok": False,
        "error": {
            "type": "policy_refusal",
            "message": (
                f"Tool group '{group}' is disabled. Set {env_name}=1 in the "
                f"server's environment to enable it."
            ),
            "group": group,
            "tool": tool,
            "required_env": env_name,
        },
    }


def auth_required(tool: str) -> dict:
    """Structured refusal payload for a write call with no GITHUB_TOKEN.
    Write actions always require a token even when the group is enabled --
    GitHub's write endpoints reject unauthenticated requests, so this is a
    fast, clean local refusal instead of a round-trip 401/403."""
    return {
        "ok": False,
        "error": {
            "type": "auth_required",
            "message": (
                f"Tool '{tool}' requires a GitHub token. Set GITHUB_TOKEN in "
                f"the server's environment (fine-grained PAT with the needed "
                f"repo write scopes)."
            ),
            "tool": tool,
        },
    }


def check_group(group: str, tool: str) -> dict | None:
    """Gate check for a tool call. Returns a structured refusal dict if the
    group is disabled, else None (caller proceeds)."""
    if not group_enabled(group):
        return policy_refusal(group, tool)
    return None


def check_write_preconditions(tool: str) -> dict | None:
    """Combined gate for write tools: group must be enabled AND a token must
    be present. Returns a structured refusal dict, else None."""
    refusal = check_group(GROUP_WRITE, tool)
    if refusal is not None:
        return refusal
    if get_token() is None:
        return auth_required(tool)
    return None


def gated_write(fn):
    """Decorator applied directly to write-group module functions so the
    policy gate + token precondition is enforced at the source -- not just in
    the MCP tool wrapper -- and is unit-testable without spinning up the
    fastmcp server or hitting the network."""

    def wrapper(*args, **kwargs):
        refusal = check_write_preconditions(fn.__name__)
        if refusal is not None:
            return refusal
        return fn(*args, **kwargs)

    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    wrapper.__wrapped__ = fn
    return wrapper
