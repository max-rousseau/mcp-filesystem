"""Security tests for path validation and git recommendation."""

import logging
import pytest
import os
import sys

from mcp_yamlfilesystem.yaml_manager import YAMLConfigManager
from mcp_yamlfilesystem.config import (
    Config,
    _validate_config_directory_permissions,
)
from mcp_yamlfilesystem.exceptions import (
    FilePathError,
    YAMLConfigError,
)


class TestPathTraversalProtection:
    """Test protection against path traversal attacks."""

    def test_reject_parent_directory_traversal(self, git_repo_dir):
        """Reject paths attempting to escape via ../"""
        manager = YAMLConfigManager(git_repo_dir)

        with pytest.raises(FilePathError, match="must be within config directory"):
            manager.validate_path("../../../etc/passwd")

    def test_reject_absolute_paths(self, git_repo_dir):
        """Reject absolute paths."""
        manager = YAMLConfigManager(git_repo_dir)

        with pytest.raises(FilePathError, match="Absolute paths are not allowed"):
            manager.validate_path("/etc/passwd")

        with pytest.raises(FilePathError, match="Absolute paths are not allowed"):
            manager.validate_path("/tmp/test.yaml")  # nosec B108

    def test_reject_null_bytes(self, git_repo_dir):
        """Reject paths containing null bytes."""
        manager = YAMLConfigManager(git_repo_dir)

        with pytest.raises(FilePathError, match="invalid characters"):
            manager.validate_path("test\x00.yaml")

    def test_reject_control_characters(self, git_repo_dir):
        """Reject paths with control characters."""
        manager = YAMLConfigManager(git_repo_dir)

        with pytest.raises(FilePathError, match="invalid characters"):
            manager.validate_path("test\x01.yaml")

    def test_accept_valid_relative_paths(self, git_repo_dir):
        """Accept valid relative paths within directory."""
        manager = YAMLConfigManager(git_repo_dir)

        (git_repo_dir / "test.yaml").touch()
        valid_path = manager.validate_path("test.yaml")
        # validate_path returns a relative string path
        assert valid_path == "test.yaml"
        assert manager._filesystem.exists(valid_path)

        (git_repo_dir / "configs").mkdir()
        (git_repo_dir / "configs" / "sub.yaml").touch()
        valid_path = manager.validate_path("configs/sub.yaml")
        assert manager._filesystem.exists(valid_path)


class TestSymlinkProtection:
    """Test protection against symlink escape attacks."""

    def test_reject_symlink_to_external_file(self, git_repo_dir, temp_dir):
        """Reject symlinks pointing outside config directory."""
        manager = YAMLConfigManager(git_repo_dir)

        external_file = temp_dir / "external.yaml"
        external_file.write_text("external: data\n", encoding="utf-8")

        symlink_path = git_repo_dir / "link.yaml"
        symlink_path.symlink_to(external_file)

        with pytest.raises(FilePathError, match="must be within config directory"):
            manager.validate_path("link.yaml")

    def test_accept_symlink_to_internal_file(self, git_repo_dir):
        """Accept symlinks pointing to files within config directory."""
        manager = YAMLConfigManager(git_repo_dir)

        target_file = git_repo_dir / "target.yaml"
        target_file.write_text("data: value\n", encoding="utf-8")

        symlink_path = git_repo_dir / "link.yaml"
        symlink_path.symlink_to(target_file)

        resolved = manager.validate_path("link.yaml")
        # validate_path returns a relative string path
        assert manager._filesystem.exists(resolved)
        assert manager._filesystem.read_text(resolved) == "data: value\n"


class TestExtensionValidation:
    """Test file extension whitelisting."""

    def test_reject_non_yaml_extensions(self, git_repo_dir):
        """Reject files without .yaml or .yml extension."""
        manager = YAMLConfigManager(git_repo_dir)

        with pytest.raises(FilePathError, match="Only files with extensions"):
            manager.validate_path("script.py")

        with pytest.raises(FilePathError, match="Only files with extensions"):
            manager.validate_path("config.json")

        with pytest.raises(FilePathError, match="Only files with extensions"):
            manager.validate_path("data.txt")

    def test_accept_yaml_extensions(self, git_repo_dir):
        """Accept .yaml and .yml extensions."""
        manager = YAMLConfigManager(git_repo_dir)

        (git_repo_dir / "test.yaml").touch()
        assert manager.validate_path("test.yaml")

        (git_repo_dir / "test.yml").touch()
        assert manager.validate_path("test.yml")

    def test_case_insensitive_extension_check(self, git_repo_dir):
        """Extension check should be case-insensitive."""
        manager = YAMLConfigManager(git_repo_dir)

        (git_repo_dir / "test.YAML").touch()
        assert manager.validate_path("test.YAML")

        (git_repo_dir / "test.YML").touch()
        assert manager.validate_path("test.YML")


class TestGitRecommendation:
    """Test git version control recommendation for config directory."""

    def _minimal_required_env(self, monkeypatch):
        """Set all required HTTP/OAuth env vars so config loading succeeds."""
        monkeypatch.setenv("MCP_HTTP_ENABLED", "false")
        monkeypatch.setenv("MCP_HTTP_HOST", "127.0.0.1")
        monkeypatch.setenv("MCP_HTTP_PORT", "8000")
        monkeypatch.setenv("MCP_HTTP_PATH", "/mcp")
        monkeypatch.setenv("MCP_OAUTH_ENABLED", "false")
        monkeypatch.setenv("MCP_OAUTH_CLIENT_ID", "")
        monkeypatch.setenv("MCP_OAUTH_CLIENT_SECRET", "")
        monkeypatch.setenv("MCP_OAUTH_BASE_URL", "")
        monkeypatch.setenv("MCP_OAUTH_ALLOWED_EMAILS", "")
        monkeypatch.setenv("MCP_FILESYSTEM_SMB_IGNORE_DIRS", "")
        monkeypatch.setenv("DEBUG", "false")
        monkeypatch.setenv("LOG_FILE", "")

    def test_warn_non_git_directory(self, non_git_dir, monkeypatch, tmp_path, caplog):
        """Warn when directory lacks .git folder (git is recommended, not required)."""
        monkeypatch.setenv("MCP_FILESYSTEM_LOCAL_PATH", str(non_git_dir))
        self._minimal_required_env(monkeypatch)
        from mcp_yamlfilesystem import config

        monkeypatch.setattr(
            config, "get_config_file_path", lambda: tmp_path / "nonexistent"
        )

        with caplog.at_level(logging.WARNING, logger="mcp_yamlfilesystem.config"):
            loaded_config = Config.get()

        assert loaded_config.yaml_root_path == non_git_dir.resolve()
        assert "not git-controlled" in caplog.text
        assert "recommended" in caplog.text

    def test_accept_git_directory(self, git_repo_dir, monkeypatch, tmp_path):
        """Accept directories with .git folder without warning."""
        monkeypatch.setenv("MCP_FILESYSTEM_LOCAL_PATH", str(git_repo_dir))
        self._minimal_required_env(monkeypatch)
        from mcp_yamlfilesystem import config

        monkeypatch.setattr(
            config, "get_config_file_path", lambda: tmp_path / "nonexistent"
        )

        loaded_config = Config.get()
        assert loaded_config.yaml_root_path == git_repo_dir.resolve()

    def test_git_warning_message_helpful(
        self, non_git_dir, monkeypatch, tmp_path, caplog
    ):
        """Verify warning message includes helpful instructions."""
        monkeypatch.setenv("MCP_FILESYSTEM_LOCAL_PATH", str(non_git_dir))
        self._minimal_required_env(monkeypatch)
        from mcp_yamlfilesystem import config

        monkeypatch.setattr(
            config, "get_config_file_path", lambda: tmp_path / "nonexistent"
        )

        with caplog.at_level(logging.WARNING, logger="mcp_yamlfilesystem.config"):
            Config.get()

        assert "git init" in caplog.text
        assert "traceability" in caplog.text.lower()


class TestConfigValidation:
    """Test configuration loading validation."""

    def _set_required_http_oauth_env(self, monkeypatch):
        """Set all required HTTP/OAuth env vars so config loading can proceed."""
        monkeypatch.setenv("MCP_HTTP_ENABLED", "false")
        monkeypatch.setenv("MCP_HTTP_HOST", "127.0.0.1")
        monkeypatch.setenv("MCP_HTTP_PORT", "8000")
        monkeypatch.setenv("MCP_HTTP_PATH", "/mcp")
        monkeypatch.setenv("MCP_OAUTH_ENABLED", "false")
        monkeypatch.setenv("MCP_OAUTH_CLIENT_ID", "")
        monkeypatch.setenv("MCP_OAUTH_CLIENT_SECRET", "")
        monkeypatch.setenv("MCP_OAUTH_BASE_URL", "")
        monkeypatch.setenv("MCP_OAUTH_ALLOWED_EMAILS", "")
        monkeypatch.setenv("MCP_FILESYSTEM_SMB_IGNORE_DIRS", "")
        monkeypatch.setenv("DEBUG", "false")
        monkeypatch.setenv("LOG_FILE", "")

    def test_require_local_path(self, monkeypatch, tmp_path):
        """Require local path to be set via env var or config file."""
        monkeypatch.delenv("MCP_FILESYSTEM_LOCAL_PATH", raising=False)
        # Also ensure no SMB config
        monkeypatch.delenv("MCP_FILESYSTEM_SMB_PATH", raising=False)
        monkeypatch.delenv("MCP_FILESYSTEM_SMB_USER", raising=False)
        monkeypatch.delenv("MCP_FILESYSTEM_SMB_PASSWORD", raising=False)
        self._set_required_http_oauth_env(monkeypatch)

        # Mock the config file path to an empty location
        from mcp_yamlfilesystem import config

        monkeypatch.setattr(
            config, "get_config_file_path", lambda: tmp_path / "nonexistent"
        )

        with pytest.raises(YAMLConfigError, match="Configuration required"):
            Config.get()

    def test_reject_nonexistent_directory(self, monkeypatch, tmp_path):
        """Reject path that doesn't exist."""
        monkeypatch.setenv("MCP_FILESYSTEM_LOCAL_PATH", "/nonexistent/path")
        self._set_required_http_oauth_env(monkeypatch)
        # Prevent real config file from interfering
        from mcp_yamlfilesystem import config

        monkeypatch.setattr(
            config, "get_config_file_path", lambda: tmp_path / "nonexistent"
        )

        with pytest.raises(YAMLConfigError, match="does not exist"):
            Config.get()

    def test_reject_file_instead_of_directory(self, temp_dir, monkeypatch, tmp_path):
        """Reject path pointing to file instead of directory."""
        file_path = temp_dir / "file.txt"
        file_path.touch()

        monkeypatch.setenv("MCP_FILESYSTEM_LOCAL_PATH", str(file_path))
        self._set_required_http_oauth_env(monkeypatch)
        # Prevent real config file from interfering
        from mcp_yamlfilesystem import config

        monkeypatch.setattr(
            config, "get_config_file_path", lambda: tmp_path / "nonexistent"
        )

        with pytest.raises(YAMLConfigError, match="not a directory"):
            Config.get()


class TestReadOperationSecurity:
    """Test security of read operations."""

    def test_cannot_read_outside_directory(self, git_repo_dir, temp_dir):
        """Cannot read files outside config directory."""
        manager = YAMLConfigManager(git_repo_dir)

        external_file = temp_dir / "external.yaml"
        external_file.write_text("secret: data\n", encoding="utf-8")

        with pytest.raises(FilePathError):
            relative_path = os.path.relpath(external_file, git_repo_dir)
            manager.read_file(relative_path)


class TestWriteOperationSecurity:
    """Test security of write operations."""

    def test_cannot_write_outside_directory(self, git_repo_dir):
        """Cannot write files outside config directory."""
        manager = YAMLConfigManager(git_repo_dir)

        with pytest.raises(FilePathError):
            manager.write_file("../../../tmp/malicious.yaml", "data: evil\n")

    def test_cannot_create_outside_directory(self, git_repo_dir):
        """Cannot create files outside config directory."""
        manager = YAMLConfigManager(git_repo_dir)

        with pytest.raises(FilePathError):
            manager.create_file("../../../tmp/malicious.yaml", "data: evil\n")


@pytest.mark.skipif(sys.platform == "win32", reason="Unix permission tests")
class TestConfigFilePermissions:
    """Test config file permission validation."""

    def test_reject_world_readable_config(self, tmp_path, monkeypatch):
        """Reject config files readable by others (mode 644)."""
        config_dir = tmp_path / ".config" / "mcp-yamlfilesystem"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config"
        config_file.write_text("allowed_extensions=.yaml,.yml\n")
        config_file.chmod(0o644)  # rw-r--r--

        # Mock the config dir path to use our temp directory
        monkeypatch.setattr(
            "mcp_yamlfilesystem.config._get_config_dir_path",
            lambda: config_dir,
        )

        with pytest.raises(YAMLConfigError) as exc_info:
            _validate_config_directory_permissions()

        assert "Insecure permissions" in str(exc_info.value)
        assert "chmod 600" in str(exc_info.value)

    def test_reject_group_readable_config(self, tmp_path, monkeypatch):
        """Reject config files readable by group (mode 640)."""
        config_dir = tmp_path / ".config" / "mcp-yamlfilesystem"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config"
        config_file.write_text("smb_password=secret\n")
        config_file.chmod(0o640)  # rw-r-----

        monkeypatch.setattr(
            "mcp_yamlfilesystem.config._get_config_dir_path",
            lambda: config_dir,
        )

        with pytest.raises(YAMLConfigError, match="Insecure permissions"):
            _validate_config_directory_permissions()

    def test_accept_secure_permissions(self, tmp_path, monkeypatch):
        """Accept config files with mode 600."""
        config_dir = tmp_path / ".config" / "mcp-yamlfilesystem"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config"
        config_file.write_text("allowed_extensions=.yaml,.yml\n")
        config_file.chmod(0o600)  # rw-------

        monkeypatch.setattr(
            "mcp_yamlfilesystem.config._get_config_dir_path",
            lambda: config_dir,
        )

        # Should not raise
        _validate_config_directory_permissions()

    def test_accept_owner_read_only(self, tmp_path, monkeypatch):
        """Accept config files with mode 400 (read-only by owner)."""
        config_dir = tmp_path / ".config" / "mcp-yamlfilesystem"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config"
        config_file.write_text("allowed_extensions=.yaml,.yml\n")
        config_file.chmod(0o400)  # r--------

        monkeypatch.setattr(
            "mcp_yamlfilesystem.config._get_config_dir_path",
            lambda: config_dir,
        )

        # Should not raise (400 is even more restrictive than 600)
        _validate_config_directory_permissions()

    def test_check_all_files_in_directory(self, tmp_path, monkeypatch):
        """Check permissions on all files in config directory."""
        config_dir = tmp_path / ".config" / "mcp-yamlfilesystem"
        config_dir.mkdir(parents=True)

        # Create multiple files, one insecure
        secure_file = config_dir / "config"
        secure_file.write_text("allowed_extensions=.yaml,.yml\n")
        secure_file.chmod(0o600)

        insecure_file = config_dir / "credentials"
        insecure_file.write_text("smb_password=secret\n")
        insecure_file.chmod(0o644)

        monkeypatch.setattr(
            "mcp_yamlfilesystem.config._get_config_dir_path",
            lambda: config_dir,
        )

        with pytest.raises(YAMLConfigError) as exc_info:
            _validate_config_directory_permissions()

        assert "credentials" in str(exc_info.value)

    def test_no_error_when_config_dir_missing(self, tmp_path, monkeypatch):
        """No error when config directory doesn't exist."""
        nonexistent_dir = tmp_path / "nonexistent"

        monkeypatch.setattr(
            "mcp_yamlfilesystem.config._get_config_dir_path",
            lambda: nonexistent_dir,
        )

        # Should not raise - no config dir is fine
        _validate_config_directory_permissions()

    def test_load_config_checks_permissions(self, tmp_path, monkeypatch, git_repo_dir):
        """Verify load_config validates permissions before loading."""
        config_dir = tmp_path / ".config" / "mcp-yamlfilesystem"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config"
        config_file.write_text("allowed_extensions=.yaml,.yml\n")
        config_file.chmod(0o644)  # Insecure

        monkeypatch.setattr(
            "mcp_yamlfilesystem.config._get_config_dir_path",
            lambda: config_dir,
        )
        monkeypatch.setattr(
            "mcp_yamlfilesystem.config.get_config_file_path",
            lambda: config_file,
        )
        monkeypatch.setenv("MCP_FILESYSTEM_LOCAL_PATH", str(git_repo_dir))

        with pytest.raises(YAMLConfigError, match="Insecure permissions"):
            Config.get()
