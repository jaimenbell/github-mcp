from __future__ import annotations

import base64

import httpx
import respx

from github_mcp.groups import read


class TestGetRepo:
    @respx.mock
    def test_success(self):
        respx.get("https://api.github.com/repos/anthropics/anthropic-sdk-python").mock(
            return_value=httpx.Response(
                200,
                json={
                    "full_name": "anthropics/anthropic-sdk-python",
                    "description": "SDK",
                    "language": "Python",
                    "stargazers_count": 100,
                    "forks_count": 10,
                    "open_issues_count": 5,
                    "default_branch": "main",
                    "archived": False,
                    "disabled": False,
                    "license": {"spdx_id": "MIT"},
                    "pushed_at": "2026-01-01T00:00:00Z",
                    "html_url": "https://github.com/anthropics/anthropic-sdk-python",
                },
            )
        )
        result = read.get_repo("anthropics", "anthropic-sdk-python")
        assert result["ok"] is True
        assert result["full_name"] == "anthropics/anthropic-sdk-python"
        assert result["stargazers_count"] == 100
        assert result["license"] == "MIT"

    @respx.mock
    def test_error_propagates(self):
        respx.get("https://api.github.com/repos/o/missing").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )
        result = read.get_repo("o", "missing")
        assert result["ok"] is False
        assert result["error"]["type"] == "github_api_error"


class TestListIssues:
    @respx.mock
    def test_filters_out_pull_requests(self):
        respx.get("https://api.github.com/repos/o/r/issues").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"number": 1, "title": "real issue", "state": "open", "user": {"login": "a"}, "labels": [], "comments": 0, "updated_at": "t"},
                    {"number": 2, "title": "a pr", "state": "open", "user": {"login": "b"}, "labels": [], "comments": 0, "updated_at": "t", "pull_request": {}},
                ],
            )
        )
        result = read.list_issues("o", "r")
        assert result["ok"] is True
        assert len(result["issues"]) == 1
        assert result["issues"][0]["number"] == 1

    @respx.mock
    def test_limit_capped_at_50(self):
        route = respx.get("https://api.github.com/repos/o/r/issues").mock(return_value=httpx.Response(200, json=[]))
        read.list_issues("o", "r", limit=999)
        assert route.calls.last.request.url.params["per_page"] == "50"


class TestGetIssue:
    @respx.mock
    def test_success(self):
        respx.get("https://api.github.com/repos/o/r/issues/7").mock(
            return_value=httpx.Response(
                200,
                json={"number": 7, "title": "t", "body": "b", "state": "open", "user": {"login": "u"}, "labels": [{"name": "bug"}], "comments": 2, "created_at": "c", "updated_at": "u"},
            )
        )
        result = read.get_issue("o", "r", 7)
        assert result["ok"] is True
        assert result["number"] == 7
        assert result["labels"] == ["bug"]


class TestListPullRequests:
    @respx.mock
    def test_success(self):
        respx.get("https://api.github.com/repos/o/r/pulls").mock(
            return_value=httpx.Response(
                200,
                json=[{"number": 3, "title": "t", "state": "open", "user": {"login": "u"}, "draft": False, "base": {"ref": "main"}, "head": {"ref": "feat"}, "updated_at": "t"}],
            )
        )
        result = read.list_pull_requests("o", "r")
        assert result["ok"] is True
        assert result["pull_requests"][0]["base"] == "main"


class TestGetPullRequest:
    @respx.mock
    def test_success(self):
        respx.get("https://api.github.com/repos/o/r/pulls/9").mock(
            return_value=httpx.Response(
                200,
                json={"number": 9, "title": "t", "body": "b", "state": "open", "user": {"login": "u"}, "draft": False, "mergeable": True, "merged": False, "base": {"ref": "main"}, "head": {"ref": "feat"}, "updated_at": "t"},
            )
        )
        result = read.get_pull_request("o", "r", 9)
        assert result["ok"] is True
        assert result["mergeable"] is True


class TestGetFileContent:
    @respx.mock
    def test_success_decodes_utf8(self):
        encoded = base64.b64encode(b"hello world").decode()
        respx.get("https://api.github.com/repos/o/r/contents/README.md").mock(
            return_value=httpx.Response(200, json={"path": "README.md", "size": 11, "encoding": "base64", "content": encoded})
        )
        result = read.get_file_content("o", "r", "README.md")
        assert result["ok"] is True
        assert result["content"] == "hello world"
        assert result["binary"] is False

    @respx.mock
    def test_directory_returns_not_a_file(self):
        respx.get("https://api.github.com/repos/o/r/contents/src").mock(
            return_value=httpx.Response(200, json=[{"name": "a.py"}])
        )
        result = read.get_file_content("o", "r", "src")
        assert result["ok"] is False
        assert result["error"]["type"] == "not_a_file"

    @respx.mock
    def test_binary_content_reported_not_decoded(self):
        encoded = base64.b64encode(b"\x89PNG\r\n\x1a\n\x00\x01\x02").decode()
        respx.get("https://api.github.com/repos/o/r/contents/img.png").mock(
            return_value=httpx.Response(200, json={"path": "img.png", "size": 9, "encoding": "base64", "content": encoded})
        )
        result = read.get_file_content("o", "r", "img.png")
        assert result["ok"] is True
        assert result["binary"] is True
        assert result["content"] is None

    @respx.mock
    def test_unsupported_encoding_rejected(self):
        """GitHub returns encoding='none' for blobs over ~1MB (content omitted
        entirely) instead of base64 -- must refuse cleanly, not KeyError/crash."""
        respx.get("https://api.github.com/repos/o/r/contents/huge.bin").mock(
            return_value=httpx.Response(200, json={"path": "huge.bin", "size": 5_000_000, "encoding": "none"})
        )
        result = read.get_file_content("o", "r", "huge.bin")
        assert result["ok"] is False
        assert result["error"]["type"] == "unsupported_encoding"

    @respx.mock
    def test_content_over_max_bytes_is_truncated(self):
        raw = b"x" * (read.MAX_FILE_BYTES + 500)
        encoded = base64.b64encode(raw).decode()
        respx.get("https://api.github.com/repos/o/r/contents/big.txt").mock(
            return_value=httpx.Response(200, json={"path": "big.txt", "size": len(raw), "encoding": "base64", "content": encoded})
        )
        result = read.get_file_content("o", "r", "big.txt")
        assert result["ok"] is True
        assert result["truncated"] is True
        assert len(result["content"]) == read.MAX_FILE_BYTES


class TestSearchRepos:
    @respx.mock
    def test_success(self):
        respx.get("https://api.github.com/search/repositories").mock(
            return_value=httpx.Response(
                200,
                json={"total_count": 1, "items": [{"full_name": "o/r", "description": "d", "language": "Python", "stargazers_count": 5, "html_url": "u"}]},
            )
        )
        result = read.search_repos("mcp server language:python")
        assert result["ok"] is True
        assert result["total_count"] == 1
        assert result["items"][0]["full_name"] == "o/r"


class TestGetUser:
    @respx.mock
    def test_success(self):
        respx.get("https://api.github.com/users/torvalds").mock(
            return_value=httpx.Response(
                200,
                json={"login": "torvalds", "name": "Linus Torvalds", "bio": None, "company": None, "location": "Portland", "public_repos": 10, "followers": 200000, "type": "User"},
            )
        )
        result = read.get_user("torvalds")
        assert result["ok"] is True
        assert result["login"] == "torvalds"
        assert result["followers"] == 200000


class TestListCommits:
    @respx.mock
    def test_success(self):
        respx.get("https://api.github.com/repos/o/r/commits").mock(
            return_value=httpx.Response(
                200,
                json=[{"sha": "abc123", "commit": {"message": "fix bug", "author": {"name": "a", "date": "d"}}, "html_url": "u"}],
            )
        )
        result = read.list_commits("o", "r")
        assert result["ok"] is True
        assert result["commits"][0]["sha"] == "abc123"
        assert result["commits"][0]["message"] == "fix bug"

    @respx.mock
    def test_sha_param_passed_through(self):
        route = respx.get("https://api.github.com/repos/o/r/commits").mock(return_value=httpx.Response(200, json=[]))
        read.list_commits("o", "r", sha="develop")
        assert route.calls.last.request.url.params["sha"] == "develop"


class TestUnauthDegrade:
    """Read tools work with no GITHUB_TOKEN set at all -- the unauthenticated
    60 req/hr tier. Verifies no Authorization header leaks through when the
    env has no token, across a representative read tool."""

    @respx.mock
    def test_get_repo_works_without_token(self):
        route = respx.get("https://api.github.com/repos/o/r").mock(
            return_value=httpx.Response(200, json={"full_name": "o/r"})
        )
        result = read.get_repo("o", "r")
        assert result["ok"] is True
        assert "Authorization" not in route.calls.last.request.headers

    @respx.mock
    def test_get_repo_rate_limited_without_token_is_typed(self):
        respx.get("https://api.github.com/repos/o/r").mock(
            return_value=httpx.Response(
                403,
                json={"message": "API rate limit exceeded"},
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1720000000"},
            )
        )
        result = read.get_repo("o", "r")
        assert result["ok"] is False
        assert result["error"]["type"] == "rate_limited"
        assert result["error"]["reset_time"] == 1720000000
