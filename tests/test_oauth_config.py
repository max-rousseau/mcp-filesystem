"""Tests for OAuth configuration."""

import os
import pytest
from unittest.mock import patch

from mcp_yamlfilesystem.config import (
    Config,
    _load_oauth_config,
    OAuthConfig,
)
from mcp_yamlfilesystem.exceptions import YAMLConfigError


class TestOAuthConfigDataclass:
    """Tests for OAuthConfig dataclass."""

    def test_defaults(self):
        """Test default values."""
        config = OAuthConfig()
        assert config.enabled is True
        assert config.client_id == ""
        assert config.client_secret == ""
        assert config.base_url == ""
        assert config.allowed_emails is None

    def test_custom_values(self):
        """Test custom values."""
        config = OAuthConfig(
            enabled=False,
            client_id="test-client-id.apps.googleusercontent.com",
            client_secret="GOCSPX-test-secret",
            base_url="https://example.com",
            allowed_emails=["admin@example.com", "user@example.com"],
        )
        assert config.enabled is False
        assert config.client_id == "test-client-id.apps.googleusercontent.com"
        assert config.client_secret == "GOCSPX-test-secret"
        assert config.base_url == "https://example.com"
        assert config.allowed_emails == ["admin@example.com", "user@example.com"]

    def test_partial_custom_values(self):
        """Test partial custom values with remaining defaults."""
        config = OAuthConfig(client_id="my-client-id")
        assert config.enabled is True
        assert config.client_id == "my-client-id"
        assert config.client_secret == ""
        assert config.base_url == ""
        assert config.allowed_emails is None

    def test_none_allowed_emails_is_none(self):
        """Test that None allowed_emails stays None (no __post_init__ conversion)."""
        config = OAuthConfig(allowed_emails=None)
        assert config.allowed_emails is None


_FULL_OAUTH_CONFIG = {
    "MCP_OAUTH_ENABLED": "false",
    "MCP_OAUTH_CLIENT_ID": "",
    "MCP_OAUTH_CLIENT_SECRET": "",
    "MCP_OAUTH_BASE_URL": "",
    "MCP_OAUTH_ALLOWED_EMAILS": "",
}


class TestLoadOAuthConfig:
    """Tests for _load_oauth_config function."""

    def test_all_keys_http_disabled(self):
        """Test loading with all keys when HTTP is disabled."""
        with patch.dict(os.environ, {}, clear=True):
            result = _load_oauth_config(_FULL_OAUTH_CONFIG, http_enabled=False)
            assert result.enabled is False
            assert result.client_id == ""
            assert result.client_secret == ""
            assert result.base_url == ""
            assert result.allowed_emails == []

    def test_missing_required_key_raises_error(self):
        """Test that missing required key raises error."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(YAMLConfigError, match="Missing required configuration"):
                _load_oauth_config({}, http_enabled=False)

    def test_no_config_http_disabled(self):
        """Test defaults when HTTP is disabled and enabled key is false."""
        with patch.dict(os.environ, {}, clear=True):
            result = _load_oauth_config(_FULL_OAUTH_CONFIG, http_enabled=False)
            assert result.enabled is False
            assert result.client_id == ""
            assert result.client_secret == ""
            assert result.base_url == ""
            assert result.allowed_emails == []

    def test_no_config_http_enabled_no_credentials_raises(self):
        """Test that missing credentials raises error when HTTP enabled."""
        file_config = {
            "MCP_OAUTH_ENABLED": "true",
            "MCP_OAUTH_CLIENT_ID": "",
            "MCP_OAUTH_CLIENT_SECRET": "",
            "MCP_OAUTH_BASE_URL": "",
            "MCP_OAUTH_ALLOWED_EMAILS": "",
        }
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(YAMLConfigError) as exc:
                _load_oauth_config(file_config, http_enabled=True)
            assert "MCP_OAUTH_CLIENT_ID" in str(exc.value)
            assert "MCP_OAUTH_CLIENT_SECRET" in str(exc.value)
            assert "MCP_OAUTH_BASE_URL" in str(exc.value)

    def test_http_enabled_with_credentials(self):
        """Test OAuth enabled by default when HTTP enabled with credentials."""
        file_config = {
            "MCP_OAUTH_ENABLED": "true",
            "MCP_OAUTH_CLIENT_ID": "test-id.apps.googleusercontent.com",
            "MCP_OAUTH_CLIENT_SECRET": "GOCSPX-test",
            "MCP_OAUTH_BASE_URL": "https://example.com",
            "MCP_OAUTH_ALLOWED_EMAILS": "",
        }
        with patch.dict(os.environ, {}, clear=True):
            result = _load_oauth_config(file_config, http_enabled=True)
            assert result.enabled is True
            assert result.client_id == "test-id.apps.googleusercontent.com"
            assert result.client_secret == "GOCSPX-test"
            assert result.base_url == "https://example.com"

    def test_config_from_dict_with_emails(self):
        """Test loading from config dict with allowed emails."""
        file_config = {
            "MCP_OAUTH_ENABLED": "true",
            "MCP_OAUTH_CLIENT_ID": "test-id.apps.googleusercontent.com",
            "MCP_OAUTH_CLIENT_SECRET": "GOCSPX-test",
            "MCP_OAUTH_BASE_URL": "https://example.com",
            "MCP_OAUTH_ALLOWED_EMAILS": "admin@example.com,user@example.com",
        }
        with patch.dict(os.environ, {}, clear=True):
            result = _load_oauth_config(file_config, http_enabled=True)
            assert result.enabled is True
            assert result.allowed_emails == ["admin@example.com", "user@example.com"]

    def test_env_vars_override_config(self):
        """Test environment variables take precedence."""
        file_config = {
            "MCP_OAUTH_ENABLED": "true",
            "MCP_OAUTH_CLIENT_ID": "file-id",
            "MCP_OAUTH_CLIENT_SECRET": "file-secret",
            "MCP_OAUTH_BASE_URL": "https://file.com",
            "MCP_OAUTH_ALLOWED_EMAILS": "file@example.com",
        }
        env_vars = {
            "MCP_OAUTH_CLIENT_ID": "env-id.apps.googleusercontent.com",
            "MCP_OAUTH_CLIENT_SECRET": "GOCSPX-env",
            "MCP_OAUTH_BASE_URL": "https://env.com",
            "MCP_OAUTH_ALLOWED_EMAILS": "env@example.com",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            result = _load_oauth_config(file_config, http_enabled=True)
            assert result.client_id == "env-id.apps.googleusercontent.com"
            assert result.client_secret == "GOCSPX-env"
            assert result.base_url == "https://env.com"
            assert result.allowed_emails == ["env@example.com"]

    def test_partial_env_override(self):
        """Test partial environment variable override."""
        file_config = {
            "MCP_OAUTH_ENABLED": "true",
            "MCP_OAUTH_CLIENT_ID": "file-id.apps.googleusercontent.com",
            "MCP_OAUTH_CLIENT_SECRET": "GOCSPX-file",
            "MCP_OAUTH_BASE_URL": "https://file.com",
            "MCP_OAUTH_ALLOWED_EMAILS": "",
        }
        with patch.dict(
            os.environ,
            {"MCP_OAUTH_CLIENT_ID": "env-id.apps.googleusercontent.com"},
            clear=True,
        ):
            result = _load_oauth_config(file_config, http_enabled=True)
            assert result.client_id == "env-id.apps.googleusercontent.com"
            assert result.client_secret == "GOCSPX-file"
            assert result.base_url == "https://file.com"

    def test_explicit_disabled_no_credentials_required(self):
        """Test that explicit disable doesn't require credentials."""
        file_config = {
            "MCP_OAUTH_CLIENT_ID": "",
            "MCP_OAUTH_CLIENT_SECRET": "",
            "MCP_OAUTH_BASE_URL": "",
            "MCP_OAUTH_ALLOWED_EMAILS": "",
        }
        with patch.dict(os.environ, {"MCP_OAUTH_ENABLED": "false"}, clear=True):
            result = _load_oauth_config(file_config, http_enabled=True)
            assert result.enabled is False
            assert result.client_id == ""

    @pytest.mark.parametrize(
        "value",
        ["true", "True", "TRUE", "1", "yes", "on"],
    )
    def test_enabled_truthy_values(self, value: str):
        """Test various truthy values for enabled."""
        file_config = {
            "MCP_OAUTH_CLIENT_ID": "test-id.apps.googleusercontent.com",
            "MCP_OAUTH_CLIENT_SECRET": "GOCSPX-test",
            "MCP_OAUTH_BASE_URL": "https://example.com",
            "MCP_OAUTH_ALLOWED_EMAILS": "",
        }
        with patch.dict(os.environ, {"MCP_OAUTH_ENABLED": value}, clear=True):
            result = _load_oauth_config(file_config, http_enabled=True)
            assert result.enabled is True

    @pytest.mark.parametrize(
        "value",
        ["false", "False", "FALSE", "0", "no", "off"],
    )
    def test_enabled_falsy_values(self, value: str):
        """Test various falsy values for enabled."""
        file_config = {
            "MCP_OAUTH_CLIENT_ID": "",
            "MCP_OAUTH_CLIENT_SECRET": "",
            "MCP_OAUTH_BASE_URL": "",
            "MCP_OAUTH_ALLOWED_EMAILS": "",
        }
        with patch.dict(os.environ, {"MCP_OAUTH_ENABLED": value}, clear=True):
            result = _load_oauth_config(file_config, http_enabled=True)
            assert result.enabled is False

    def test_allowed_emails_parsing_with_spaces(self):
        """Test allowed emails parsing handles whitespace."""
        file_config = {
            "MCP_OAUTH_ENABLED": "true",
            "MCP_OAUTH_CLIENT_ID": "test-id.apps.googleusercontent.com",
            "MCP_OAUTH_CLIENT_SECRET": "GOCSPX-test",
            "MCP_OAUTH_BASE_URL": "https://example.com",
            "MCP_OAUTH_ALLOWED_EMAILS": " admin@example.com , user@example.com , ",
        }
        with patch.dict(os.environ, {}, clear=True):
            result = _load_oauth_config(file_config, http_enabled=True)
            assert result.allowed_emails == ["admin@example.com", "user@example.com"]

    def test_empty_allowed_emails(self):
        """Test empty allowed emails list."""
        file_config = {
            "MCP_OAUTH_ENABLED": "true",
            "MCP_OAUTH_CLIENT_ID": "test-id.apps.googleusercontent.com",
            "MCP_OAUTH_CLIENT_SECRET": "GOCSPX-test",
            "MCP_OAUTH_BASE_URL": "https://example.com",
            "MCP_OAUTH_ALLOWED_EMAILS": "",
        }
        with patch.dict(os.environ, {}, clear=True):
            result = _load_oauth_config(file_config, http_enabled=True)
            assert result.allowed_emails == []

    def test_missing_client_id_raises(self):
        """Test missing client ID raises error when OAuth enabled + HTTP enabled."""
        file_config = {
            "MCP_OAUTH_ENABLED": "true",
            "MCP_OAUTH_CLIENT_ID": "",
            "MCP_OAUTH_CLIENT_SECRET": "GOCSPX-test",
            "MCP_OAUTH_BASE_URL": "https://example.com",
            "MCP_OAUTH_ALLOWED_EMAILS": "",
        }
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(YAMLConfigError) as exc:
                _load_oauth_config(file_config, http_enabled=True)
            assert "MCP_OAUTH_CLIENT_ID" in str(exc.value)
            assert "MCP_OAUTH_CLIENT_SECRET" not in str(exc.value)

    def test_missing_client_secret_raises(self):
        """Test missing client secret raises error when OAuth enabled + HTTP enabled."""
        file_config = {
            "MCP_OAUTH_ENABLED": "true",
            "MCP_OAUTH_CLIENT_ID": "test-id.apps.googleusercontent.com",
            "MCP_OAUTH_CLIENT_SECRET": "",
            "MCP_OAUTH_BASE_URL": "https://example.com",
            "MCP_OAUTH_ALLOWED_EMAILS": "",
        }
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(YAMLConfigError) as exc:
                _load_oauth_config(file_config, http_enabled=True)
            assert "MCP_OAUTH_CLIENT_SECRET" in str(exc.value)
            assert "MCP_OAUTH_CLIENT_ID" not in str(exc.value)

    def test_missing_base_url_raises(self):
        """Test missing base URL raises error when OAuth enabled + HTTP enabled."""
        file_config = {
            "MCP_OAUTH_ENABLED": "true",
            "MCP_OAUTH_CLIENT_ID": "test-id.apps.googleusercontent.com",
            "MCP_OAUTH_CLIENT_SECRET": "GOCSPX-test",
            "MCP_OAUTH_BASE_URL": "",
            "MCP_OAUTH_ALLOWED_EMAILS": "",
        }
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(YAMLConfigError) as exc:
                _load_oauth_config(file_config, http_enabled=True)
            assert "MCP_OAUTH_BASE_URL" in str(exc.value)


class TestLoadConfigWithOAuth:
    """Tests for load_config with OAuth configuration."""

    @pytest.fixture
    def git_repo_dir(self, tmp_path):
        """Create a temporary git-controlled directory."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        return tmp_path

    def test_config_includes_oauth_config(self, git_repo_dir):
        """Test that load_config includes oauth_config."""
        env_vars = {
            "MCP_FILESYSTEM_LOCAL_PATH": str(git_repo_dir),
            "MCP_HTTP_ENABLED": "true",
            "MCP_OAUTH_ENABLED": "true",
            "MCP_OAUTH_CLIENT_ID": "test-id.apps.googleusercontent.com",
            "MCP_OAUTH_CLIENT_SECRET": "GOCSPX-test",
            "MCP_OAUTH_BASE_URL": "https://example.com",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            config = Config.get()
            assert config.oauth_config is not None
            assert config.oauth_config.enabled is True
            assert config.oauth_config.client_id == "test-id.apps.googleusercontent.com"

    def test_oauth_config_defaults_when_http_disabled(self, git_repo_dir):
        """Test OAuth config has defaults (disabled) when HTTP disabled."""
        with patch.dict(
            os.environ,
            {"MCP_FILESYSTEM_LOCAL_PATH": str(git_repo_dir)},
            clear=True,
        ):
            config = Config.get()
            assert config.oauth_config is not None
            assert config.oauth_config.enabled is False

    def test_oauth_enabled_requires_credentials(self, git_repo_dir):
        """Test OAuth enabled with HTTP requires credentials."""
        env_vars = {
            "MCP_FILESYSTEM_LOCAL_PATH": str(git_repo_dir),
            "MCP_HTTP_ENABLED": "true",
            "MCP_OAUTH_ENABLED": "true",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(YAMLConfigError) as exc:
                Config.get()
            assert "MCP_OAUTH_CLIENT_ID" in str(exc.value)

    def test_oauth_disabled_with_http(self, git_repo_dir):
        """Test OAuth can be disabled even with HTTP enabled."""
        env_vars = {
            "MCP_FILESYSTEM_LOCAL_PATH": str(git_repo_dir),
            "MCP_HTTP_ENABLED": "true",
            "MCP_OAUTH_ENABLED": "false",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            config = Config.get()
            assert config.http_config.enabled is True
            assert config.oauth_config.enabled is False

    def test_oauth_with_allowed_emails(self, git_repo_dir):
        """Test OAuth config with allowed emails list."""
        env_vars = {
            "MCP_FILESYSTEM_LOCAL_PATH": str(git_repo_dir),
            "MCP_HTTP_ENABLED": "true",
            "MCP_OAUTH_CLIENT_ID": "test-id.apps.googleusercontent.com",
            "MCP_OAUTH_CLIENT_SECRET": "GOCSPX-test",
            "MCP_OAUTH_BASE_URL": "https://example.com",
            "MCP_OAUTH_ALLOWED_EMAILS": "admin@example.com,user@example.com",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            config = Config.get()
            assert config.oauth_config.allowed_emails == [
                "admin@example.com",
                "user@example.com",
            ]

    def test_oauth_config_with_smb_mode(self):
        """Test OAuth config works alongside SMB mode."""
        env_vars = {
            "MCP_FILESYSTEM_SMB_PATH": "//server/share",
            "MCP_FILESYSTEM_SMB_USER": "user",
            "MCP_FILESYSTEM_SMB_PASSWORD": "pass",
            "MCP_HTTP_ENABLED": "true",
            "MCP_OAUTH_ENABLED": "true",
            "MCP_OAUTH_CLIENT_ID": "test-id.apps.googleusercontent.com",
            "MCP_OAUTH_CLIENT_SECRET": "GOCSPX-test",
            "MCP_OAUTH_BASE_URL": "https://example.com",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            config = Config.get()
            assert config.is_smb_mode is True
            assert config.http_config.enabled is True
            assert config.oauth_config.enabled is True
