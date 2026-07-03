from __future__ import annotations

import httpx
import respx

from github_mcp import client


class TestAuthHeaderInjection:
    @respx.mock
    def test_no_token_no_auth_header(self):
        route = respx.get("https://api.github.com/repos/octocat/hello").mock(
            return_value=httpx.Response(200, json={"full_name": "octocat/hello"})
        )
        result = client.get("get_repo", "/repos/octocat/hello")
        assert result["ok"] is True
        assert "Authorization" not in route.calls.last.request.headers

    @respx.mock
    def test_token_present_sends_bearer_header(self, with_token):
        route = respx.get("https://api.github.com/repos/octocat/hello").mock(
            return_value=httpx.Response(200, json={"full_name": "octocat/hello"})
        )
        result = client.get("get_repo", "/repos/octocat/hello")
        assert result["ok"] is True
        auth = route.calls.last.request.headers["Authorization"]
        assert auth == "Bearer github_pat_fake_test_token_1234"


class TestSuccessResponse:
    @respx.mock
    def test_returns_ok_and_data(self):
        respx.get("https://api.github.com/users/torvalds").mock(
            return_value=httpx.Response(200, json={"login": "torvalds"})
        )
        result = client.get("get_user", "/users/torvalds")
        assert result["ok"] is True
        assert result["data"]["login"] == "torvalds"
        assert result["status_code"] == 200

    @respx.mock
    def test_empty_body_returns_empty_dict(self):
        respx.post("https://api.github.com/repos/o/r/issues/1/labels").mock(
            return_value=httpx.Response(204, content=b"")
        )
        result = client.post("add_labels", "/repos/o/r/issues/1/labels")
        assert result["ok"] is True
        assert result["data"] == {}


class TestRateLimitError:
    @respx.mock
    def test_403_with_zero_remaining_is_rate_limited(self):
        respx.get("https://api.github.com/repos/o/r").mock(
            return_value=httpx.Response(
                403,
                json={"message": "API rate limit exceeded"},
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1720000000"},
            )
        )
        result = client.get("get_repo", "/repos/o/r")
        assert result["ok"] is False
        assert result["error"]["type"] == "rate_limited"
        assert result["error"]["reset_time"] == 1720000000
        assert result["error"]["remaining"] == 0

    @respx.mock
    def test_403_without_zero_remaining_is_plain_api_error(self):
        """A 403 that isn't the rate-limit shape (e.g. permission denied) must
        not be misclassified as rate_limited."""
        respx.get("https://api.github.com/repos/o/r").mock(
            return_value=httpx.Response(403, json={"message": "Forbidden"})
        )
        result = client.get("get_repo", "/repos/o/r")
        assert result["ok"] is False
        assert result["error"]["type"] == "github_api_error"
        assert result["error"]["status_code"] == 403

    @respx.mock
    def test_secondary_rate_limit_no_ratelimit_headers_retry_after_only(self):
        """GitHub's secondary (abuse-detection) rate limit: 403, no
        X-RateLimit-* headers at all, just Retry-After. Must still classify
        as rate_limited, not github_api_error."""
        respx.post("https://api.github.com/repos/o/r/issues").mock(
            return_value=httpx.Response(
                403,
                json={"message": "You have exceeded a secondary rate limit"},
                headers={"Retry-After": "30"},
            )
        )
        result = client.post("create_issue", "/repos/o/r/issues")
        assert result["ok"] is False
        assert result["error"]["type"] == "rate_limited"
        assert result["error"]["retry_after_s"] == 30
        assert result["error"]["reset_time"] is None


class TestApiError:
    @respx.mock
    def test_404_typed_error(self):
        respx.get("https://api.github.com/repos/o/nonexistent").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )
        result = client.get("get_repo", "/repos/o/nonexistent")
        assert result["ok"] is False
        assert result["error"]["type"] == "github_api_error"
        assert result["error"]["status_code"] == 404
        assert result["error"]["message"] == "Not Found"

    @respx.mock
    def test_500_typed_error(self):
        respx.get("https://api.github.com/repos/o/r").mock(return_value=httpx.Response(500, text="boom"))
        result = client.get("get_repo", "/repos/o/r")
        assert result["ok"] is False
        assert result["error"]["type"] == "github_api_error"
        assert result["error"]["status_code"] == 500

    @respx.mock
    def test_error_body_not_json_falls_back_to_text(self):
        respx.get("https://api.github.com/repos/o/r").mock(
            return_value=httpx.Response(502, text="Bad Gateway", headers={"Content-Type": "text/plain"})
        )
        result = client.get("get_repo", "/repos/o/r")
        assert result["ok"] is False
        assert "Bad Gateway" in result["error"]["message"]


class TestDecodeError:
    @respx.mock
    def test_non_json_success_body_is_decode_error(self):
        respx.get("https://api.github.com/repos/o/r").mock(
            return_value=httpx.Response(200, text="<html>not json</html>")
        )
        result = client.get("get_repo", "/repos/o/r")
        assert result["ok"] is False
        assert result["error"]["type"] == "decode_error"


class TestNetworkError:
    @respx.mock
    def test_connection_error_is_typed_network_error(self):
        respx.get("https://api.github.com/repos/o/r").mock(side_effect=httpx.ConnectError("refused"))
        result = client.get("get_repo", "/repos/o/r")
        assert result["ok"] is False
        assert result["error"]["type"] == "network_error"

    @respx.mock
    def test_timeout_is_typed_network_error(self):
        respx.get("https://api.github.com/repos/o/r").mock(side_effect=httpx.TimeoutException("timed out"))
        result = client.get("get_repo", "/repos/o/r")
        assert result["ok"] is False
        assert result["error"]["type"] == "network_error"

    def test_malformed_path_raises_invalid_url_caught_as_network_error(self):
        """httpx.InvalidURL is raised during URL construction (before any
        network I/O) and does NOT subclass httpx.HTTPError -- a caller-
        supplied owner/repo/path with control characters must still come
        back as a typed error, never an uncaught exception. No respx.mock:
        this must fail before any request is dispatched."""
        result = client.get("get_repo", "/repos/o/r\r\nX-Injected: 1")
        assert result["ok"] is False
        assert result["error"]["type"] == "network_error"


class TestHttpVerbs:
    @respx.mock
    def test_post_sends_json_body(self):
        route = respx.post("https://api.github.com/repos/o/r/issues").mock(
            return_value=httpx.Response(201, json={"number": 5})
        )
        result = client.post("create_issue", "/repos/o/r/issues", json={"title": "bug"})
        assert result["ok"] is True
        assert route.calls.last.request.content == b'{"title":"bug"}'

    @respx.mock
    def test_patch_sends_json_body(self):
        respx.patch("https://api.github.com/repos/o/r/issues/1").mock(
            return_value=httpx.Response(200, json={"number": 1, "state": "closed"})
        )
        result = client.patch("update_issue_state", "/repos/o/r/issues/1", json={"state": "closed"})
        assert result["ok"] is True
        assert result["data"]["state"] == "closed"
