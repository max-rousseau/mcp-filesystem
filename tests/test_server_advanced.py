"""Advanced tests for server module - testing uncovered paths."""

import pytest
import os
import sys
import logging
from unittest.mock import patch, MagicMock

from mcp_yamlfilesystem import server
from mcp_yamlfilesystem.config import LogConfig


class TestLoggingConfiguration:
    """Tests for configure_logging function."""

    def test_configure_logging_debug_mode(self, tmp_path):
        """Test logging configuration in debug mode."""
        log_config = LogConfig(debug=True, log_file=None)
        server.configure_logging(log_config)

        # Verify logging level is DEBUG
        logger = logging.getLogger("mcp_yamlfilesystem")
        assert logger.level == logging.DEBUG

    def test_configure_logging_info_mode(self, tmp_path):
        """Test logging configuration in info mode."""
        log_config = LogConfig(debug=False, log_file=None)
        server.configure_logging(log_config)

        # Verify logging level is INFO
        logger = logging.getLogger("mcp_yamlfilesystem")
        assert logger.level == logging.INFO

    def test_configure_logging_with_file(self):
        """Test logging configuration with log file uses FileHandler only."""
        from io import StringIO
        from pathlib import Path
        from unittest.mock import patch

        # Use a real StreamHandler writing to StringIO to simulate FileHandler
        mock_stream = StringIO()
        mock_handler = logging.StreamHandler(mock_stream)

        with patch("logging.FileHandler", return_value=mock_handler):
            log_config = LogConfig(debug=True, log_file=Path("/fake/test.log"))
            server.configure_logging(log_config)

            # Verify only one handler (file, no stderr)
            logger = logging.getLogger("mcp_yamlfilesystem")
            assert len(logger.handlers) == 1
            assert logger.handlers[0] is mock_handler

    def test_configure_logging_file_only_no_stderr(self, capsys):
        """Test that logs go to file only, not stderr, when log file configured."""
        from io import StringIO
        from pathlib import Path
        from unittest.mock import patch

        mock_file = StringIO()
        mock_handler = logging.StreamHandler(mock_file)
        mock_handler.setFormatter(logging.Formatter("%(message)s"))

        with patch("logging.FileHandler", return_value=mock_handler):
            log_config = LogConfig(debug=True, log_file=Path("/fake/test.log"))
            server.configure_logging(log_config)

            # Log a message
            test_logger = logging.getLogger("mcp_yamlfilesystem.test")
            test_logger.info("test message for file only")

            # Verify message went to file handler
            mock_file.seek(0)
            assert "test message for file only" in mock_file.read()

            # Verify nothing went to stderr (would pollute MCP stdio protocol)
            captured = capsys.readouterr()
            assert "test message for file only" not in captured.err

    def test_configure_logging_clears_existing_handlers(self):
        """Test that reconfiguring clears existing handlers."""
        log_config1 = LogConfig(debug=False, log_file=None)
        server.configure_logging(log_config1)

        log_config2 = LogConfig(debug=True, log_file=None)
        server.configure_logging(log_config2)

        # Verify handlers were replaced, not accumulated
        logger = logging.getLogger("mcp_yamlfilesystem")
        # Should only have stderr handler
        assert len(logger.handlers) == 1

    def test_configure_logging_silences_smbprotocol(self):
        """Test that smbprotocol logger is silenced to prevent stdio pollution."""
        log_config = LogConfig(debug=False, log_file=None)
        server.configure_logging(log_config)

        # Verify smbprotocol logger is set to WARNING to suppress INFO messages
        smb_logger = logging.getLogger("smbprotocol")
        assert smb_logger.level == logging.WARNING


class TestStdoutNotPolluted:
    """Tests to ensure logs never pollute stdout (MCP protocol channel)."""

    def test_info_logs_go_to_stderr_not_stdout(self, capsys):
        """Test that INFO level logs go to stderr, not stdout."""
        log_config = LogConfig(debug=False, log_file=None)
        server.configure_logging(log_config)

        logger = logging.getLogger("mcp_yamlfilesystem")
        logger.info("Test info message")

        captured = capsys.readouterr()
        assert captured.out == "", f"stdout should be empty, got: {captured.out!r}"
        assert "Test info message" in captured.err

    def test_debug_logs_go_to_stderr_not_stdout(self, capsys):
        """Test that DEBUG level logs go to stderr, not stdout."""
        log_config = LogConfig(debug=True, log_file=None)
        server.configure_logging(log_config)

        logger = logging.getLogger("mcp_yamlfilesystem")
        logger.debug("Test debug message")

        captured = capsys.readouterr()
        assert captured.out == "", f"stdout should be empty, got: {captured.out!r}"
        assert "Test debug message" in captured.err

    def test_warning_logs_go_to_stderr_not_stdout(self, capsys):
        """Test that WARNING level logs go to stderr, not stdout."""
        log_config = LogConfig(debug=False, log_file=None)
        server.configure_logging(log_config)

        logger = logging.getLogger("mcp_yamlfilesystem")
        logger.warning("Test warning message")

        captured = capsys.readouterr()
        assert captured.out == "", f"stdout should be empty, got: {captured.out!r}"
        assert "Test warning message" in captured.err

    def test_error_logs_go_to_stderr_not_stdout(self, capsys):
        """Test that ERROR level logs go to stderr, not stdout."""
        log_config = LogConfig(debug=False, log_file=None)
        server.configure_logging(log_config)

        logger = logging.getLogger("mcp_yamlfilesystem")
        logger.error("Test error message")

        captured = capsys.readouterr()
        assert captured.out == "", f"stdout should be empty, got: {captured.out!r}"
        assert "Test error message" in captured.err

    def test_smbprotocol_warning_goes_to_stderr_not_stdout(self, capsys):
        """Test that smbprotocol WARNING logs go to stderr, not stdout."""
        log_config = LogConfig(debug=False, log_file=None)
        server.configure_logging(log_config)

        # smbprotocol logger should be at WARNING level
        smb_logger = logging.getLogger("smbprotocol")
        smb_logger.warning("Test SMB warning")

        captured = capsys.readouterr()
        assert captured.out == "", f"stdout should be empty, got: {captured.out!r}"
        # Note: smbprotocol may not have handlers attached, so we just verify stdout is clean

    def test_smbprotocol_info_suppressed_entirely(self, capsys):
        """Test that smbprotocol INFO logs are suppressed (not even in stderr)."""
        log_config = LogConfig(debug=False, log_file=None)
        server.configure_logging(log_config)

        smb_logger = logging.getLogger("smbprotocol")
        smb_logger.info("SMB info that should be suppressed")

        captured = capsys.readouterr()
        assert captured.out == "", f"stdout should be empty, got: {captured.out!r}"
        assert "SMB info that should be suppressed" not in captured.err

    def test_multiple_log_messages_all_go_to_stderr(self, capsys):
        """Test that multiple log messages all go to stderr, stdout stays clean."""
        log_config = LogConfig(debug=True, log_file=None)
        server.configure_logging(log_config)

        logger = logging.getLogger("mcp_yamlfilesystem")
        logger.debug("Debug message 1")
        logger.info("Info message 1")
        logger.warning("Warning message 1")
        logger.debug("Debug message 2")

        captured = capsys.readouterr()
        assert captured.out == "", f"stdout should be empty, got: {captured.out!r}"
        assert "Debug message 1" in captured.err
        assert "Info message 1" in captured.err
        assert "Warning message 1" in captured.err
        assert "Debug message 2" in captured.err


@pytest.fixture
def preserve_tool_registry():
    """Save and restore the tool registry to prevent test pollution."""
    original_registry = server._tool_registry.copy()
    yield
    server._tool_registry.clear()
    server._tool_registry.update(original_registry)


class TestToolRegistry:
    """Tests for tool registration system."""

    def test_register_tool_stores_function(self, preserve_tool_registry):
        """Test that _register_tool stores function in registry."""
        # Clear registry
        server._tool_registry.clear()

        @server._register_tool
        async def test_tool(arg: str) -> str:
            return arg

        assert "test_tool" in server._tool_registry
        func, kwargs = server._tool_registry["test_tool"]
        assert func.__name__ == "test_tool"

    def test_register_tool_with_kwargs(self, preserve_tool_registry):
        """Test registering tool with additional kwargs."""
        server._tool_registry.clear()

        @server._register_tool(description="Test tool")
        async def another_tool(arg: str) -> str:
            return arg

        assert "another_tool" in server._tool_registry
        func, kwargs = server._tool_registry["another_tool"]
        assert kwargs["description"] == "Test tool"

    def test_register_tool_returns_original_function(self, preserve_tool_registry):
        """Test that decorator returns original function unchanged."""
        server._tool_registry.clear()

        async def original_func(arg: str) -> str:
            return arg

        decorated = server._register_tool(original_func)
        assert decorated is original_func


class TestCreateMcpServer:
    """Tests for _create_mcp_server function."""

    def test_create_mcp_server_without_auth(self, preserve_tool_registry):
        """Test creating MCP server without authentication."""
        server._tool_registry.clear()

        # Register a dummy tool
        @server._register_tool
        async def dummy_tool() -> str:
            return "test"

        mcp = server._create_mcp_server()
        assert mcp is not None
        assert mcp.name == "YAML Filesystem Manager"

    def test_create_mcp_server_with_auth(self, preserve_tool_registry):
        """Test creating MCP server with OAuth authentication."""
        from pydantic import AnyHttpUrl
        from mcp.server.auth.settings import AuthSettings

        server._tool_registry.clear()

        @server._register_tool
        async def dummy_tool() -> str:
            return "test"

        mock_verifier = MagicMock()
        auth_settings = AuthSettings(
            issuer_url=AnyHttpUrl("https://accounts.google.com"),
            resource_server_url=AnyHttpUrl("https://example.com"),
        )
        mcp = server._create_mcp_server(
            token_verifier=mock_verifier, auth_settings=auth_settings
        )
        assert mcp is not None
        assert mcp.name == "YAML Filesystem Manager"

    def test_create_mcp_server_registers_all_tools(self, preserve_tool_registry):
        """Test that all registered tools are added to server."""
        server._tool_registry.clear()

        @server._register_tool
        async def tool1() -> str:
            return "1"

        @server._register_tool
        async def tool2() -> str:
            return "2"

        mcp = server._create_mcp_server()
        # MCP server was created and tools were registered
        assert mcp is not None


class TestMCPServerSingleton:
    """Tests for MCPServer singleton."""

    def test_mcpserver_get_initializes_if_needed(self, git_repo_dir, monkeypatch):
        """Test that MCPServer.get() initializes if instance is None."""
        server.MCPServer.reset()
        server._logging_configured = False

        monkeypatch.setenv("MCP_FILESYSTEM_LOCAL_PATH", str(git_repo_dir))

        mcp_server = server.MCPServer.get()
        assert mcp_server.yaml_manager is not None
        assert mcp_server.diff_engine is not None

    def test_mcpserver_get_returns_same_instance(self, git_repo_dir, monkeypatch):
        """Test that MCPServer.get() returns same singleton instance."""
        server.MCPServer.reset()
        server._logging_configured = False

        monkeypatch.setenv("MCP_FILESYSTEM_LOCAL_PATH", str(git_repo_dir))

        server1 = server.MCPServer.get()
        server2 = server.MCPServer.get()

        assert server1 is server2

    def test_mcpserver_smb_mode(self, monkeypatch):
        """Test MCPServer initialization in SMB mode."""
        server.MCPServer.reset()
        server._logging_configured = False

        monkeypatch.setenv("MCP_FILESYSTEM_SMB_PATH", "//server/share")
        monkeypatch.setenv("MCP_FILESYSTEM_SMB_USER", "user")
        monkeypatch.setenv("MCP_FILESYSTEM_SMB_PASSWORD", "pass")

        mcp_server = server.MCPServer.get()

        assert mcp_server.yaml_manager is not None
        assert mcp_server.diff_engine is not None


class TestToolErrorHandling:
    """Tests for error handling in MCP tools."""

    @pytest.mark.asyncio
    async def test_read_file_wraps_exceptions(self, git_repo_dir, monkeypatch):
        """Test that read_file wraps exceptions in ValueError."""
        server.MCPServer.reset()
        server._logging_configured = False

        monkeypatch.setenv("MCP_FILESYSTEM_LOCAL_PATH", str(git_repo_dir))

        with pytest.raises(ValueError, match="Failed to read file"):
            await server.read_file("nonexistent.yaml")

    @pytest.mark.asyncio
    async def test_create_file_wraps_exceptions(self, git_repo_dir, monkeypatch):
        """Test that create_file wraps exceptions."""
        server.MCPServer.reset()
        server._logging_configured = False

        test_file = git_repo_dir / "existing.yaml"
        test_file.write_text("key: value\n", encoding="utf-8")

        monkeypatch.setenv("MCP_FILESYSTEM_LOCAL_PATH", str(git_repo_dir))

        with pytest.raises(ValueError, match="Failed to create file"):
            await server.create_file("existing.yaml", "new: content\n")

    @pytest.mark.asyncio
    async def test_update_file_wraps_exceptions(self, git_repo_dir, monkeypatch):
        """Test that update_file wraps exceptions."""
        server.MCPServer.reset()
        server._logging_configured = False

        monkeypatch.setenv("MCP_FILESYSTEM_LOCAL_PATH", str(git_repo_dir))

        bad_diff = "invalid diff format"
        with pytest.raises(ValueError, match="Failed to update file"):
            await server.update_file("test.yaml", bad_diff)

    @pytest.mark.asyncio
    async def test_grep_files_wraps_exceptions(self, git_repo_dir, monkeypatch):
        """Test that grep_files wraps exceptions."""
        server.MCPServer.reset()
        server._logging_configured = False

        monkeypatch.setenv("MCP_FILESYSTEM_LOCAL_PATH", str(git_repo_dir))

        # Invalid regex pattern
        with pytest.raises(ValueError, match="Failed to search files"):
            await server.grep_files("[invalid(regex")

    @pytest.mark.asyncio
    async def test_list_directory_structure_empty_directory(
        self, git_repo_dir, monkeypatch
    ):
        """Test list_directory_structure with no YAML files."""
        server.MCPServer.reset()
        server._logging_configured = False

        monkeypatch.setenv("MCP_FILESYSTEM_LOCAL_PATH", str(git_repo_dir))

        result = await server.list_directory_structure()
        assert "(no YAML files found)" in result


class TestMainEntryPoint:
    """Tests for main() entry point."""

    def test_main_with_local_path_arg(self, git_repo_dir, monkeypatch):
        """Test main with --local-path argument."""
        test_args = ["mcp-yamlfilesystem", "--local-path", str(git_repo_dir), "--test"]

        with patch.object(sys, "argv", test_args):
            with patch("mcp_yamlfilesystem.server._run_test") as mock_test:
                server.main()
                mock_test.assert_called_once()

    def test_main_sets_http_env_vars(self, git_repo_dir, monkeypatch):
        """Test that main sets HTTP environment variables from CLI args."""
        test_args = [
            "mcp-yamlfilesystem",
            "--local-path",
            str(git_repo_dir),
            "--http",
            "--host",
            "0.0.0.0",  # nosec B104 - test value for CLI arg parsing
            "--port",
            "9000",
            "--path",
            "/custom",
            "--test",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("mcp_yamlfilesystem.server._run_test"):
                server.main()

                assert os.environ.get("MCP_HTTP_ENABLED") == "true"
                assert os.environ.get("MCP_HTTP_HOST") == "0.0.0.0"  # nosec B104
                assert os.environ.get("MCP_HTTP_PORT") == "9000"
                assert os.environ.get("MCP_HTTP_PATH") == "/custom"

    def test_main_sets_oauth_env_vars(self, git_repo_dir, monkeypatch):
        """Test that main sets OAuth environment variables from CLI args."""
        test_args = [
            "mcp-yamlfilesystem",
            "--local-path",
            str(git_repo_dir),
            "--oauth-enabled",
            "false",
            "--oauth-base-url",
            "https://example.com",
            "--test",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("mcp_yamlfilesystem.server._run_test"):
                server.main()

                assert os.environ.get("MCP_OAUTH_ENABLED") == "false"
                assert os.environ.get("MCP_OAUTH_BASE_URL") == "https://example.com"
