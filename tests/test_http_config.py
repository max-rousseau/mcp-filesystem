"""Tests for HTTP transport configuration."""

import os
import pytest
from unittest.mock import patch

from mcp_yamlfilesystem.config import (
    Config,
    _load_http_config,
    HTTPConfig,
)
from mcp_yamlfilesystem.exceptions import YAMLConfigError


class TestHTTPConfigDataclass:
    """Tests for HTTPConfig dataclass."""

    def test_defaults(self):
        """Test default values."""
        config = HTTPConfig()
        assert config.enabled is False
        assert config.host == "127.0.0.1"
        assert config.port == 8000
        assert config.path == "/mcp"

    def test_custom_values(self):
        """Test custom values."""
        config = HTTPConfig(
            enabled=True, host="0.0.0.0", port=9000, path="/api/mcp"  # nosec B104
        )
        assert config.enabled is True
        assert config.host == "0.0.0.0"  # nosec B104
        assert config.port == 9000
        assert config.path == "/api/mcp"

    def test_partial_custom_values(self):
        """Test partial custom values with defaults."""
        config = HTTPConfig(enabled=True, port=3000)
        assert config.enabled is True
        assert config.host == "127.0.0.1"
        assert config.port == 3000
        assert config.path == "/mcp"


class TestLoadHTTPConfig:
    """Tests for _load_http_config function."""

    def test_all_keys_from_dict(self):
        """Test loading with all required keys present in dict."""
        file_config = {
            "MCP_HTTP_ENABLED": "false",
            "MCP_HTTP_HOST": "127.0.0.1",
            "MCP_HTTP_PORT": "8000",
            "MCP_HTTP_PATH": "/mcp",
        }
        with patch.dict(os.environ, {}, clear=True):
            result = _load_http_config(file_config)
            assert result.enabled is False
            assert result.host == "127.0.0.1"
            assert result.port == 8000
            assert result.path == "/mcp"

    def test_missing_required_key_raises_error(self):
        """Test that missing required key raises error."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(YAMLConfigError, match="Missing required configuration"):
                _load_http_config({})

    def test_config_from_dict(self):
        """Test loading from config dict."""
        file_config = {
            "MCP_HTTP_ENABLED": "true",
            "MCP_HTTP_HOST": "0.0.0.0",  # nosec B104
            "MCP_HTTP_PORT": "9000",
            "MCP_HTTP_PATH": "/api",
        }
        with patch.dict(os.environ, {}, clear=True):
            result = _load_http_config(file_config)
            assert result.enabled is True
            assert result.host == "0.0.0.0"  # nosec B104
            assert result.port == 9000
            assert result.path == "/api"

    def test_env_vars_override_config(self):
        """Test environment variables take precedence."""
        file_config = {
            "MCP_HTTP_ENABLED": "false",
            "MCP_HTTP_HOST": "localhost",
            "MCP_HTTP_PORT": "8000",
            "MCP_HTTP_PATH": "/mcp",
        }
        env_vars = {
            "MCP_HTTP_ENABLED": "true",
            "MCP_HTTP_HOST": "0.0.0.0",  # nosec B104
            "MCP_HTTP_PORT": "9999",
            "MCP_HTTP_PATH": "/custom",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            result = _load_http_config(file_config)
            assert result.enabled is True
            assert result.host == "0.0.0.0"  # nosec B104
            assert result.port == 9999
            assert result.path == "/custom"

    def test_partial_env_override(self):
        """Test partial environment variable override."""
        file_config = {
            "MCP_HTTP_ENABLED": "false",
            "MCP_HTTP_HOST": "127.0.0.1",
            "MCP_HTTP_PORT": "8000",
            "MCP_HTTP_PATH": "/mcp",
        }
        with patch.dict(os.environ, {"MCP_HTTP_ENABLED": "true"}, clear=True):
            result = _load_http_config(file_config)
            assert result.enabled is True
            assert result.port == 8000

    def test_invalid_port_raises_error(self):
        """Test invalid port raises error."""
        file_config = {
            "MCP_HTTP_ENABLED": "false",
            "MCP_HTTP_HOST": "127.0.0.1",
            "MCP_HTTP_PATH": "/mcp",
        }
        with patch.dict(os.environ, {"MCP_HTTP_PORT": "not-a-number"}, clear=True):
            with pytest.raises(YAMLConfigError) as exc:
                _load_http_config(file_config)
            assert "Invalid MCP_HTTP_PORT value" in str(exc.value)
            assert "not-a-number" in str(exc.value)

    def test_invalid_port_in_config_raises_error(self):
        """Test invalid port in config file raises error."""
        file_config = {
            "MCP_HTTP_ENABLED": "false",
            "MCP_HTTP_HOST": "127.0.0.1",
            "MCP_HTTP_PORT": "abc",
            "MCP_HTTP_PATH": "/mcp",
        }
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(YAMLConfigError) as exc:
                _load_http_config(file_config)
            assert "Invalid MCP_HTTP_PORT value" in str(exc.value)

    @pytest.mark.parametrize(
        "value",
        ["true", "True", "TRUE", "1", "yes", "on"],
    )
    def test_enabled_truthy_values(self, value: str):
        """Test various truthy values for enabled."""
        file_config = {
            "MCP_HTTP_HOST": "127.0.0.1",
            "MCP_HTTP_PORT": "8000",
            "MCP_HTTP_PATH": "/mcp",
        }
        with patch.dict(os.environ, {"MCP_HTTP_ENABLED": value}, clear=True):
            result = _load_http_config(file_config)
            assert result.enabled is True

    @pytest.mark.parametrize(
        "value",
        ["false", "False", "FALSE", "0", "no", "off", ""],
    )
    def test_enabled_falsy_values(self, value: str):
        """Test various falsy values for enabled."""
        file_config = {
            "MCP_HTTP_HOST": "127.0.0.1",
            "MCP_HTTP_PORT": "8000",
            "MCP_HTTP_PATH": "/mcp",
        }
        with patch.dict(os.environ, {"MCP_HTTP_ENABLED": value}, clear=True):
            result = _load_http_config(file_config)
            assert result.enabled is False

    def test_empty_host_is_used_as_is(self):
        """Test empty host value is used as-is (no default substitution)."""
        file_config = {
            "MCP_HTTP_ENABLED": "false",
            "MCP_HTTP_PORT": "8000",
            "MCP_HTTP_PATH": "/mcp",
        }
        with patch.dict(os.environ, {"MCP_HTTP_HOST": ""}, clear=True):
            result = _load_http_config(file_config)
            assert result.host == ""

    def test_empty_path_is_used_as_is(self):
        """Test empty path value is used as-is (no default substitution)."""
        file_config = {
            "MCP_HTTP_ENABLED": "false",
            "MCP_HTTP_HOST": "127.0.0.1",
            "MCP_HTTP_PORT": "8000",
        }
        with patch.dict(os.environ, {"MCP_HTTP_PATH": ""}, clear=True):
            result = _load_http_config(file_config)
            assert result.path == ""


class TestLoadConfigWithHTTP:
    """Tests for load_config with HTTP configuration."""

    @pytest.fixture
    def git_repo_dir(self, tmp_path):
        """Create a temporary git-controlled directory."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        return tmp_path

    def test_config_includes_http_config(self, git_repo_dir):
        """Test that load_config includes http_config."""
        env_vars = {
            "MCP_FILESYSTEM_LOCAL_PATH": str(git_repo_dir),
            "MCP_HTTP_ENABLED": "true",
            "MCP_HTTP_PORT": "9000",
            "MCP_OAUTH_ENABLED": "false",  # Disable OAuth for HTTP-only tests
        }
        with patch.dict(os.environ, env_vars, clear=True):
            config = Config.get()
            assert config.http_config is not None
            assert config.http_config.enabled is True
            assert config.http_config.port == 9000

    def test_http_config_defaults_when_not_specified(self, git_repo_dir):
        """Test HTTP config has defaults when not specified."""
        with patch.dict(
            os.environ,
            {"MCP_FILESYSTEM_LOCAL_PATH": str(git_repo_dir)},
            clear=True,
        ):
            config = Config.get()
            assert config.http_config is not None
            assert config.http_config.enabled is False
            assert config.http_config.host == "127.0.0.1"
            assert config.http_config.port == 8000
            assert config.http_config.path == "/mcp"

    def test_http_config_with_smb_mode(self):
        """Test HTTP config works alongside SMB mode."""
        env_vars = {
            "MCP_FILESYSTEM_SMB_PATH": "//server/share",
            "MCP_FILESYSTEM_SMB_USER": "user",
            "MCP_FILESYSTEM_SMB_PASSWORD": "pass",
            "MCP_HTTP_ENABLED": "true",
            "MCP_HTTP_HOST": "0.0.0.0",  # nosec B104
            "MCP_OAUTH_ENABLED": "false",  # Disable OAuth for HTTP-only tests
        }
        with patch.dict(os.environ, env_vars, clear=True):
            config = Config.get()
            assert config.is_smb_mode is True
            assert config.http_config.enabled is True
            assert config.http_config.host == "0.0.0.0"  # nosec B104
