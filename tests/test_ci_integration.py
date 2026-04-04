"""CI Integration Tests using Official MCP SDK.

Tests the MCP server via actual stdio subprocess connection using the
official modelcontextprotocol/python-sdk. Uses real configuration from
.env or ~/.config/mcp-yamlfilesystem/config - no environment overrides.

These tests validate the actual deployment configuration works correctly.
Skipped in CI environments where SMB shares are not available.
"""

import os
from pathlib import Path

import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Skip all tests in this module if running in CI or no usable config exists
_in_ci = os.environ.get("CI", "").lower() in ("true", "1", "yes")
_config_path = Path.home() / ".config" / "mcp-yamlfilesystem" / "config"
_REQUIRED_KEYS = {
    "MCP_HTTP_ENABLED",
    "MCP_HTTP_HOST",
    "MCP_HTTP_PORT",
    "MCP_HTTP_PATH",
    "MCP_OAUTH_ENABLED",
    "MCP_FILESYSTEM_SMB_IGNORE_DIRS",
    "DEBUG",
    "LOG_FILE",
}


def _config_has_required_keys(path: Path) -> bool:
    """Return True only if the config file contains all required keys."""
    if not path.exists():
        return False
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.add(line.split("=", 1)[0].strip())
    return _REQUIRED_KEYS.issubset(keys)


_has_valid_config = _config_has_required_keys(_config_path)

pytestmark = pytest.mark.skipif(
    _in_ci or not _has_valid_config,
    reason="Requires real configuration with all required keys (skipped in CI)",
)


@pytest.fixture
def server_params():
    """Create StdioServerParameters using real system configuration."""
    return StdioServerParameters(
        command=".venv/bin/mcp-yamlfilesystem",
        args=[],
    )


class TestMCPSDKIntegration:
    """Integration tests using real system configuration."""

    @pytest.mark.asyncio
    async def test_server_initializes(self, server_params):
        """Server should initialize with real config."""
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                result = await session.initialize()

                assert result is not None
                assert result.serverInfo.name == "YAML Filesystem Manager"

    @pytest.mark.asyncio
    async def test_list_tools(self, server_params):
        """Server should list all expected tools."""
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_result = await session.list_tools()

                tool_names = {tool.name for tool in tools_result.tools}
                expected = {
                    "read_file",
                    "update_file",
                    "create_file",
                    "grep_files",
                    "list_directory_structure",
                }
                assert tool_names == expected

    @pytest.mark.asyncio
    async def test_list_directory_structure(self, server_params):
        """Server should list directory structure from real filesystem."""
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "list_directory_structure", arguments={}
                )

                assert result is not None
                assert len(result.content) > 0
                # Should return some structure (exact content depends on config)
                assert result.content[0].text is not None

    @pytest.mark.asyncio
    async def test_grep_files(self, server_params):
        """Server should grep files from real filesystem."""
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "grep_files", arguments={"search_pattern": "aquarium"}
                )

                assert result is not None
                assert len(result.content) > 0
                # Result depends on actual config content

    @pytest.mark.asyncio
    async def test_read_file(self, server_params):
        """Server should read files from real filesystem."""
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # First list structure to find a file
                structure = await session.call_tool(
                    "list_directory_structure", arguments={}
                )

                # Extract first yaml file from structure if available
                structure_text = structure.content[0].text
                lines = structure_text.split("\n")
                yaml_files = [
                    line.strip()
                    for line in lines
                    if line.strip().endswith((".yaml", ".yml"))
                ]

                if yaml_files:
                    # Read the first yaml file found
                    file_path = yaml_files[0]
                    result = await session.call_tool(
                        "read_file", arguments={"file_path": file_path}
                    )
                    assert result is not None
                    assert len(result.content) > 0

    @pytest.mark.asyncio
    async def test_sequential_operations(self, server_params):
        """Server should handle multiple sequential operations."""
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Multiple operations in sequence
                await session.list_tools()
                await session.call_tool("list_directory_structure", arguments={})
                await session.call_tool(
                    "grep_files", arguments={"search_pattern": ".*"}
                )

                # If we get here without error, sequential ops work
                assert True
