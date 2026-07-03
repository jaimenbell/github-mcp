from __future__ import annotations

import httpx
import pytest
import respx

from github_mcp.groups import write

WRITE_FN_ARGS = [
    (write.create_issue, ("o", "r", "title")),
    (write.comment_on_issue, ("o", "r", 1, "body")),
    (write.update_issue_state, ("o", "r", 1, "closed")),
    (write.add_labels, ("o", "r", 1, ["bug"])),
    (write.create_pr_review_comment, ("o", "r", 1, "body", "sha123", "file.py", 3)),
]


class TestGateDisabledByDefault:
    @respx.mock
    @pytest.mark.parametrize("fn,args", WRITE_FN_ARGS)
    def test_refused_when_write_disabled(self, fn, args):
        """No route is registered on the respx mock -- if the gate ever lets
        a call fall through to the network, respx raises instead of letting
        the test pass on a coincidentally-shaped refusal dict."""
        result = fn(*args)
        assert result["ok"] is False
        assert result["error"]["type"] == "policy_refusal"
        assert result["error"]["group"] == "write"


class TestAuthRequiredWhenGroupEnabled:
    @respx.mock
    @pytest.mark.parametrize("fn,args", WRITE_FN_ARGS)
    def test_refused_when_no_token(self, fn, args, enable_write):
        """Same no-route guard as above: group enabled but no token must
        still refuse locally, never reach the network."""
        result = fn(*args)
        assert result["ok"] is False
        assert result["error"]["type"] == "auth_required"


class TestCreateIssue:
    @respx.mock
    def test_success(self, write_ready):
        route = respx.post("https://api.github.com/repos/o/r/issues").mock(
            return_value=httpx.Response(201, json={"number": 42, "html_url": "https://github.com/o/r/issues/42", "state": "open"})
        )
        result = write.create_issue("o", "r", "a bug", body="details", labels=["bug"])
        assert result["ok"] is True
        assert result["number"] == 42
        auth = route.calls.last.request.headers["Authorization"]
        assert auth == "Bearer github_pat_fake_test_token_1234"

    @respx.mock
    def test_api_error_propagates(self, write_ready):
        respx.post("https://api.github.com/repos/o/r/issues").mock(
            return_value=httpx.Response(422, json={"message": "Validation Failed"})
        )
        result = write.create_issue("o", "r", "a bug")
        assert result["ok"] is False
        assert result["error"]["type"] == "github_api_error"


class TestCommentOnIssue:
    @respx.mock
    def test_success(self, write_ready):
        respx.post("https://api.github.com/repos/o/r/issues/5/comments").mock(
            return_value=httpx.Response(201, json={"id": 999, "html_url": "u"})
        )
        result = write.comment_on_issue("o", "r", 5, "nice catch")
        assert result["ok"] is True
        assert result["id"] == 999

    @respx.mock
    def test_api_error_propagates(self, write_ready):
        respx.post("https://api.github.com/repos/o/r/issues/5/comments").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )
        result = write.comment_on_issue("o", "r", 5, "nice catch")
        assert result["ok"] is False
        assert result["error"]["type"] == "github_api_error"


class TestUpdateIssueState:
    @respx.mock
    def test_success_closed(self, write_ready):
        respx.patch("https://api.github.com/repos/o/r/issues/5").mock(
            return_value=httpx.Response(200, json={"number": 5, "state": "closed"})
        )
        result = write.update_issue_state("o", "r", 5, "closed")
        assert result["ok"] is True
        assert result["state"] == "closed"

    def test_invalid_state_rejected_before_network(self, write_ready):
        result = write.update_issue_state("o", "r", 5, "bogus")
        assert result["ok"] is False
        assert result["error"]["type"] == "invalid_input"

    @respx.mock
    def test_api_error_propagates(self, write_ready):
        respx.patch("https://api.github.com/repos/o/r/issues/5").mock(
            return_value=httpx.Response(410, json={"message": "Gone"})
        )
        result = write.update_issue_state("o", "r", 5, "closed")
        assert result["ok"] is False
        assert result["error"]["type"] == "github_api_error"


class TestAddLabels:
    @respx.mock
    def test_success(self, write_ready):
        respx.post("https://api.github.com/repos/o/r/issues/5/labels").mock(
            return_value=httpx.Response(200, json=[{"name": "bug"}, {"name": "priority"}])
        )
        result = write.add_labels("o", "r", 5, ["bug", "priority"])
        assert result["ok"] is True
        assert result["labels"] == ["bug", "priority"]

    @respx.mock
    def test_api_error_propagates(self, write_ready):
        respx.post("https://api.github.com/repos/o/r/issues/5/labels").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )
        result = write.add_labels("o", "r", 5, ["bug"])
        assert result["ok"] is False
        assert result["error"]["type"] == "github_api_error"


class TestCreatePrReviewComment:
    @respx.mock
    def test_success(self, write_ready):
        respx.post("https://api.github.com/repos/o/r/pulls/8/comments").mock(
            return_value=httpx.Response(201, json={"id": 1234, "html_url": "u"})
        )
        result = write.create_pr_review_comment("o", "r", 8, "consider renaming", "sha123", "file.py", 10)
        assert result["ok"] is True
        assert result["id"] == 1234

    @respx.mock
    def test_api_error_propagates(self, write_ready):
        respx.post("https://api.github.com/repos/o/r/pulls/8/comments").mock(
            return_value=httpx.Response(422, json={"message": "Validation Failed"})
        )
        result = write.create_pr_review_comment("o", "r", 8, "consider renaming", "sha123", "file.py", 10)
        assert result["ok"] is False
        assert result["error"]["type"] == "github_api_error"
