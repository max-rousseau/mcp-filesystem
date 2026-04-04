"""Stdio Transport Tests.

Tests MCP server communication patterns using the official MCP SDK's in-memory transport.
This approach avoids flaky subprocess spawning while still validating the
full MCP protocol flow including initialization, tool discovery, and invocation.

Note: The actual stdio transport layer is tested by the MCP SDK itself.
These tests verify our server correctly implements the MCP protocol.
"""

import pytest
from mcp.types import TextContent
from mcp.shared.memory import create_connected_server_and_client_session

from mcp_yamlfilesystem.server import _create_mcp_server


def get_result_text(result) -> str:
    """Extract text content from CallToolResult."""
    if result.content and isinstance(result.content[0], TextContent):
        return result.content[0].text
    return ""


@pytest.fixture
async def mcp_server(git_repo_dir, monkeypatch):
    """Create MCP server instance for testing."""
    import mcp_yamlfilesystem.server as server_module

    monkeypatch.setenv("MCP_FILESYSTEM_LOCAL_PATH", str(git_repo_dir))

    # Reset server state
    server_module.yaml_manager = None
    server_module.diff_engine = None

    return _create_mcp_server()


class TestMCPInitialization:
    """Test MCP server initialization via protocol."""

    async def test_server_accepts_connection(self, mcp_server):
        """Server should accept client connection and initialize."""
        async with create_connected_server_and_client_session(mcp_server) as client:
            assert client is not None

    async def test_server_responds_to_ping(self, mcp_server):
        """Server should respond to basic protocol operations after init."""
        async with create_connected_server_and_client_session(mcp_server) as client:
            # send_ping() verifies the connection is alive
            result = await client.send_ping()
            assert result is not None


class TestToolDiscovery:
    """Test MCP tool discovery via protocol."""

    async def test_list_tools_returns_expected_count(self, mcp_server):
        """Server should expose exactly 5 tools."""
        async with create_connected_server_and_client_session(mcp_server) as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 5

    async def test_list_tools_contains_all_expected_tools(self, mcp_server):
        """All expected tools should be discoverable via protocol."""
        async with create_connected_server_and_client_session(mcp_server) as client:
            tools = await client.list_tools()
            tool_names = {tool.name for tool in tools.tools}

            expected = {
                "read_file",
                "update_file",
                "create_file",
                "grep_files",
                "list_directory_structure",
            }
            assert tool_names == expected

    async def test_tool_schemas_are_valid(self, mcp_server):
        """Tool schemas should be properly structured."""
        async with create_connected_server_and_client_session(mcp_server) as client:
            tools = await client.list_tools()

            for tool in tools.tools:
                assert tool.inputSchema is not None
                assert tool.inputSchema.get("type") == "object"
                assert "properties" in tool.inputSchema


class TestToolInvocation:
    """Test MCP tool invocation via protocol."""

    async def test_read_file_returns_content(self, mcp_server, git_repo_dir):
        """read_file tool should return file contents via protocol."""
        (git_repo_dir / "test.yaml").write_text("key: value\n", encoding="utf-8")

        async with create_connected_server_and_client_session(mcp_server) as client:
            result = await client.call_tool(
                "read_file", arguments={"file_path": "test.yaml"}
            )

            assert result.isError is False
            assert len(result.content) > 0
            assert isinstance(result.content[0], TextContent)
            assert "key: value" in result.content[0].text

    async def test_list_directory_structure_returns_tree(
        self, mcp_server, git_repo_dir
    ):
        """list_directory_structure should return directory tree via protocol."""
        (git_repo_dir / "config.yaml").write_text("test: true\n", encoding="utf-8")
        (git_repo_dir / "subdir").mkdir()
        (git_repo_dir / "subdir" / "nested.yaml").write_text(
            "nested: true\n", encoding="utf-8"
        )

        async with create_connected_server_and_client_session(mcp_server) as client:
            result = await client.call_tool("list_directory_structure", arguments={})

            assert result.isError is False
            result_text = get_result_text(result)
            assert "config.yaml" in result_text
            assert "subdir/" in result_text

    async def test_create_file_creates_new_file(self, mcp_server, git_repo_dir):
        """create_file tool should create files via protocol."""
        async with create_connected_server_and_client_session(mcp_server) as client:
            result = await client.call_tool(
                "create_file",
                arguments={
                    "file_path": "new.yaml",
                    "content": "created: true\n",
                },
            )

            assert result.isError is False
            assert (git_repo_dir / "new.yaml").exists()
            assert (git_repo_dir / "new.yaml").read_text() == "created: true\n"


class TestProtocolCompliance:
    """Test MCP protocol compliance."""

    async def test_responses_contain_text_content(self, mcp_server, git_repo_dir):
        """Tool responses should contain properly typed content."""
        (git_repo_dir / "test.yaml").write_text("key: value\n", encoding="utf-8")

        async with create_connected_server_and_client_session(mcp_server) as client:
            result = await client.call_tool(
                "read_file", arguments={"file_path": "test.yaml"}
            )

            assert all(isinstance(c, TextContent) for c in result.content)

    async def test_multiple_sequential_calls_work(self, mcp_server, git_repo_dir):
        """Multiple tool calls in sequence should work correctly."""
        async with create_connected_server_and_client_session(mcp_server) as client:
            # First call - create a file
            await client.call_tool(
                "create_file",
                arguments={"file_path": "seq_test.yaml", "content": "step: 1\n"},
            )

            # Second call - read it back
            result = await client.call_tool(
                "read_file", arguments={"file_path": "seq_test.yaml"}
            )

            assert "step: 1" in get_result_text(result)

            # Third call - list structure
            result = await client.call_tool("list_directory_structure", arguments={})
            assert "seq_test.yaml" in get_result_text(result)
