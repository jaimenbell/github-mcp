# github-mcp

[![PyPI](https://img.shields.io/pypi/v/jaimenbell-github-mcp)](https://pypi.org/project/jaimenbell-github-mcp/)
[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-io.github.jaimenbell%2Fgithub--mcp-blue)](https://github.com/jaimenbell/github-mcp/blob/master/server.json)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![tests](https://img.shields.io/badge/tests-74%20passing%20%2F%201%20skipped-brightgreen)](#testing)

A public read+write MCP server over the GitHub REST API, built to the
[desktop-mcp](https://github.com/jaimenbell/desktop-mcp)/rag-mcp/[mcp-factory](https://github.com/jaimenbell/mcp-factory) standard (own
pyproject, fastmcp server, honest README, real test suite) with env-gated
tool groups (**write disabled by default**). **Not the official GitHub MCP
server** -- see below.

## Quickstart (60 seconds)

```
pip install jaimenbell-github-mcp
```

```jsonc
// Add to your MCP host config (e.g. Claude Desktop/Code's mcpServers block)
{
  "mcpServers": {
    "github-mcp": {
      "command": "github-mcp"
    }
  }
}
```

The `write` tool group (issue/PR mutations) is off by default -- see
[Env vars](#env-vars) below to enable it.

## What this is / is not

This is a **reference portfolio implementation** demonstrating a hardened
read+write MCP server pattern over a real external SaaS API (GitHub) --
env-gated tool groups, typed error/rate-limit handling, auth that degrades
gracefully, a real test suite. It exists to show, concretely, "I build
read/write MCP servers over external APIs" with a link a client can click.

**It is NOT the official GitHub MCP server.** It does not aim for parity
with GitHub's own MCP offering (GraphQL, Actions, webhooks, GitHub Apps are
all out of scope -- see below). It started life as a factory-scaffolded
read-only demo ([mcp-factory](https://github.com/jaimenbell/mcp-factory)'s
`generated/github_read_server.py`) and was hand-hardened into this
standalone read+write server -- the scaffold-then-harden path is itself part
of the story this repo tells.

## Tool groups

| Group | Tools | Default state |
|---|---|---|
| `read` | `get_repo`, `list_issues`, `get_issue`, `list_pull_requests`, `get_pull_request`, `get_file_content`, `search_repos`, `get_user`, `list_commits` | always on, works unauthenticated (GitHub's 60 req/hr tier) |
| `write` | `create_issue`, `comment_on_issue`, `update_issue_state`, `add_labels`, `create_pr_review_comment` | env-gated, **OFF by default** -- requires `GITHUB_MCP_ENABLE_WRITE=1` **and** `GITHUB_TOKEN` |

A disabled write call returns a structured `policy_refusal` error (never a
silent no-op, never a crash). A write call with the group enabled but no
token returns a structured `auth_required` error -- the group gate and the
token precondition are checked independently, both before any network call.

## Write-safety-off-by-default

This is defense-in-depth, mirroring desktop-mcp's `input` group: harness-level
permission prompts are the first gate, but the server itself refuses every
write tool unless its own environment explicitly opts in with
`GITHUB_MCP_ENABLE_WRITE=1`, and even then refuses without a `GITHUB_TOKEN`.
A misconfigured or overly-permissive MCP host cannot turn on GitHub mutations
this process wasn't deliberately configured to allow. The registration this
repo ships with (see `~/.claude.json`'s `github-mcp` entry) has the write
group **absent from env** -- enabling it is a deliberate per-registration
operator choice, not a code change.

## Honest-capabilities table

Every claim below maps to the file that implements it and the test(s) that
verify it -- no capability is asserted without a corresponding implementation
and test.

| Claim | Implementation | Verified by |
|---|---|---|
| Repo metadata (stars, language, license, default branch, archived flag...) | `github_mcp/groups/read.py::get_repo` | `tests/test_read.py::TestGetRepo`, live: `tests/test_live_smoke.py::test_live_get_repo_real_json` |
| List / fetch issues (PRs filtered from list) | `github_mcp/groups/read.py::list_issues`, `get_issue` | `tests/test_read.py::TestListIssues`, `TestGetIssue` |
| List / fetch pull requests | `github_mcp/groups/read.py::list_pull_requests`, `get_pull_request` | `tests/test_read.py::TestListPullRequests`, `TestGetPullRequest` |
| Read a repo file's content (base64-decoded, binary detected not decoded) | `github_mcp/groups/read.py::get_file_content` | `tests/test_read.py::TestGetFileContent` |
| Search public repositories | `github_mcp/groups/read.py::search_repos` | `tests/test_read.py::TestSearchRepos` |
| Public user/org profile | `github_mcp/groups/read.py::get_user` | `tests/test_read.py::TestGetUser` |
| List commits on a branch/ref | `github_mcp/groups/read.py::list_commits` | `tests/test_read.py::TestListCommits` |
| Open an issue | `github_mcp/groups/write.py::create_issue` | `tests/test_write.py::TestCreateIssue` |
| Comment on an issue/PR | `github_mcp/groups/write.py::comment_on_issue` | `tests/test_write.py::TestCommentOnIssue` |
| Open/close an issue | `github_mcp/groups/write.py::update_issue_state` | `tests/test_write.py::TestUpdateIssueState` |
| Add labels to an issue/PR | `github_mcp/groups/write.py::add_labels` | `tests/test_write.py::TestAddLabels` |
| Create a PR review comment on a diff line | `github_mcp/groups/write.py::create_pr_review_comment` | `tests/test_write.py::TestCreatePrReviewComment` |
| Write group OFF by default, structured refusal when disabled | `github_mcp/config.py::group_enabled`, `gated_write` | `tests/test_config.py::TestGroupEnabled`, `tests/test_write.py::TestGateDisabledByDefault` |
| Write tools require a token even when the group is enabled | `github_mcp/config.py::check_write_preconditions` | `tests/test_config.py::TestCheckWritePreconditions`, `tests/test_write.py::TestAuthRequiredWhenGroupEnabled` |
| Fine-grained PAT auth, degrades to unauthenticated tier when absent | `github_mcp/client.py::_headers` | `tests/test_client.py::TestAuthHeaderInjection`, `tests/test_read.py::TestUnauthDegrade` |
| GitHub primary rate-limit (403 + `X-RateLimit-Reset`) and secondary rate-limit (403 + `Retry-After`, no `X-RateLimit-Remaining`) both surface as a typed error with reset/retry time, never a crash | `github_mcp/client.py::_rate_limit_error`, `_is_rate_limit_response` | `tests/test_client.py::TestRateLimitError`, `tests/test_client.py::TestRateLimitError::test_secondary_rate_limit_no_ratelimit_headers_retry_after_only`, `tests/test_read.py::TestUnauthDegrade::test_get_repo_rate_limited_without_token_is_typed` |
| Malformed owner/repo/path (control chars etc.) that would raise `httpx.InvalidURL` surfaces as a typed error, never an uncaught exception | `github_mcp/client.py::request` | `tests/test_client.py::TestNetworkError::test_malformed_path_raises_invalid_url_caught_as_network_error` |
| Generic 4xx/5xx surfaces as a typed error, never a crash | `github_mcp/client.py::_api_error` | `tests/test_client.py::TestApiError` |
| Non-JSON / malformed responses and network failures surface as typed errors | `github_mcp/client.py::_handle_response`, `request` | `tests/test_client.py::TestDecodeError`, `TestNetworkError` |

## Limitations (read before relying on this)

- **REST v1 only.** No GraphQL API coverage.
- **No webhooks / GitHub App auth.** Fine-grained PAT only.
- **No Actions/workflow-dispatch tools.** Issue/PR CRUD is the v1 write surface.
- **Unauthenticated read is rate-limited to 60 req/hr** by GitHub itself (10
  req/min for search) -- expect `rate_limited` errors under sustained
  unauthenticated use; set `GITHUB_TOKEN` (even a read-only fine-grained PAT)
  to raise this considerably.
- **`get_file_content` truncates past 100KB** and reports (rather than
  decodes) non-UTF-8 files.
- **No pagination beyond a single page** for list endpoints (`limit`, capped
  per-endpoint, is the only page-size control in v1).
- **Not registered with the mcp-factory hub.** Ships as a standalone repo
  (own pyproject, system Python312 install), matching the rag-mcp/desktop-mcp
  model.

## Env vars

| Var | Effect | Default |
|---|---|---|
| `GITHUB_MCP_ENABLE_WRITE` | enable the `write` tool group | unset (off) |
| `GITHUB_TOKEN` | fine-grained PAT; read works without it (degraded unauth rate), write requires it | unset |
| `GITHUB_MCP_LIVE` | `1` to run the real-network smoke test (see Testing) | unset (skip) |

## Usage examples

```jsonc
// A tool call from the MCP host, illustrative -- not a shell command.
{"tool": "get_repo", "arguments": {"owner": "anthropics", "repo": "anthropic-sdk-python"}}
// -> {"ok": true, "full_name": "anthropics/anthropic-sdk-python", "stargazers_count": 1234, ...}

// write group disabled (default):
{"tool": "create_issue", "arguments": {"owner": "o", "repo": "r", "title": "bug"}}
// -> {"ok": false, "error": {"type": "policy_refusal", "group": "write", "required_env": "GITHUB_MCP_ENABLE_WRITE", ...}}

// write group enabled, no token set:
{"tool": "create_issue", "arguments": {"owner": "o", "repo": "r", "title": "bug"}}
// -> {"ok": false, "error": {"type": "auth_required", "tool": "create_issue", ...}}
```

## Testing

```
# unit suite (respx-mocked api.github.com, no real network touched)
python -m pytest -q

# handshake check -- prints every registered tool name
python scripts/list_tools.py

# real-network read smoke (get_repo against a stable public repo;
# no write smoke exists anywhere in this suite -- see safety rails above)
GITHUB_MCP_LIVE=1 python -m pytest -q -k live_get_repo
```

## Install

```
pip install -r requirements.txt   # or: pip install .
# deps: fastmcp==3.4.2, httpx==0.28.1
# test-only: pytest==9.0.3, respx==0.23.1
```

## Setup / connect

1. `pip install -r requirements.txt` on Python 3.12+.
2. (Optional) generate a [fine-grained PAT](https://github.com/settings/tokens?type=beta)
   scoped to the repos you want read+write access to (Issues: read/write,
   Pull requests: read/write, Contents: read is enough for v1). Read tools
   work with **no token at all** -- they just run at GitHub's unauthenticated
   60 req/hr tier.
3. Add to your MCP host config (e.g. `~/.claude.json`):

```jsonc
{
  "mcpServers": {
    "github-mcp": {
      "command": "C:\\Users\\jaime\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
      "args": ["C:\\Users\\jaime\\projects\\github-mcp\\run_server.py"],
      "env": {
        "GITHUB_TOKEN": "your-fine-grained-pat-here"
        // GITHUB_MCP_ENABLE_WRITE intentionally absent -- write stays off
        // until you deliberately opt in per-deployment.
      }
    }
  }
}
```

4. To enable write tools for a given deployment, add
   `"GITHUB_MCP_ENABLE_WRITE": "1"` to that entry's `env` block. This is a
   registration-time operator decision, not a code change.

Registered in `~/.claude.json` as `github-mcp` (stdio, system Python312,
`read` group always on, `write` group absent from env -- off).


## Commercial support

Maintained by [Jaimen Bell](https://jaimenbell.dev). For production MCP integrations, custom servers, or agent-reliability work, see [jaimenbell.dev](https://jaimenbell.dev) or sponsor ongoing maintenance via [GitHub Sponsors](https://github.com/sponsors/jaimenbell).

<!-- MCP registry ownership marker -->
mcp-name: io.github.jaimenbell/github-mcp
