from __future__ import annotations

from github_mcp import config


class TestGroupEnabled:
    def test_read_always_on(self):
        assert config.group_enabled(config.GROUP_READ) is True

    def test_write_off_by_default(self):
        assert config.group_enabled(config.GROUP_WRITE) is False

    def test_write_on_when_env_set(self, enable_write):
        assert config.group_enabled(config.GROUP_WRITE) is True

    def test_write_off_for_falsy_env(self, monkeypatch):
        monkeypatch.setenv("GITHUB_MCP_ENABLE_WRITE", "0")
        assert config.group_enabled(config.GROUP_WRITE) is False

    def test_unknown_group_defaults_off(self):
        assert config.group_enabled("bogus") is False


class TestGetToken:
    def test_none_when_unset(self):
        assert config.get_token() is None

    def test_returns_value_when_set(self, with_token):
        assert config.get_token() == "github_pat_fake_test_token_1234"

    def test_empty_string_treated_as_absent(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "")
        assert config.get_token() is None


class TestMaskToken:
    def test_masks_all_but_last_four(self):
        assert config.mask_token("github_pat_abcdef1234") == "...1234"

    def test_none_token(self):
        assert config.mask_token(None) == "(none)"

    def test_short_token_fully_masked(self):
        assert config.mask_token("ab") == "**"


class TestPolicyRefusal:
    def test_shape(self):
        result = config.policy_refusal(config.GROUP_WRITE, "create_issue")
        assert result["ok"] is False
        assert result["error"]["type"] == "policy_refusal"
        assert result["error"]["group"] == "write"
        assert result["error"]["tool"] == "create_issue"
        assert result["error"]["required_env"] == "GITHUB_MCP_ENABLE_WRITE"


class TestAuthRequired:
    def test_shape(self):
        result = config.auth_required("create_issue")
        assert result["ok"] is False
        assert result["error"]["type"] == "auth_required"
        assert result["error"]["tool"] == "create_issue"


class TestCheckWritePreconditions:
    def test_refuses_when_group_disabled(self):
        result = config.check_write_preconditions("create_issue")
        assert result is not None
        assert result["error"]["type"] == "policy_refusal"

    def test_refuses_when_no_token(self, enable_write):
        result = config.check_write_preconditions("create_issue")
        assert result is not None
        assert result["error"]["type"] == "auth_required"

    def test_passes_when_group_enabled_and_token_present(self, write_ready):
        result = config.check_write_preconditions("create_issue")
        assert result is None


class TestGatedWriteDecorator:
    def test_refused_when_disabled(self):
        @config.gated_write
        def fake_tool():
            return {"ok": True, "called": True}

        result = fake_tool()
        assert result["ok"] is False
        assert result["error"]["type"] == "policy_refusal"

    def test_refused_when_no_token(self, enable_write):
        @config.gated_write
        def fake_tool():
            return {"ok": True, "called": True}

        result = fake_tool()
        assert result["ok"] is False
        assert result["error"]["type"] == "auth_required"

    def test_calls_through_when_ready(self, write_ready):
        @config.gated_write
        def fake_tool():
            return {"ok": True, "called": True}

        result = fake_tool()
        assert result == {"ok": True, "called": True}
