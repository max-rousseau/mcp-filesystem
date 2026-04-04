"""MCP Protocol Integration Tests.

Tests the MCP server at the protocol level using the official MCP SDK client.
Verifies tool discovery, invocation, and response formats.
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

    # Reset server state for testing
    server_module.yaml_manager = None
    server_module.diff_engine = None

    # Create server instance using deferred instantiation (no auth for tests)
    return _create_mcp_server()


class TestMCPServerInitialization:
    """Test MCP server initialization and discovery."""

    async def test_server_initializes(self, mcp_server):
        """Server should initialize successfully."""
        async with create_connected_server_and_client_session(mcp_server) as client:
            assert client is not None

    async def test_list_tools_returns_expected_count(self, mcp_server):
        """Server should expose exactly 5 tools."""
        async with create_connected_server_and_client_session(mcp_server) as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 5

    async def test_all_expected_tools_present(self, mcp_server):
        """All expected tools should be discoverable."""
        async with create_connected_server_and_client_session(mcp_server) as client:
            tools = await client.list_tools()
            tool_names = {tool.name for tool in tools.tools}

            expected_tools = {
                "read_file",
                "update_file",
                "create_file",
                "grep_files",
                "list_directory_structure",
            }

            assert tool_names == expected_tools

    async def test_tools_have_descriptions(self, mcp_server):
        """All tools should have non-empty descriptions."""
        async with create_connected_server_and_client_session(mcp_server) as client:
            tools = await client.list_tools()

            for tool in tools.tools:
                assert tool.description
                assert len(tool.description) > 10

    async def test_tools_have_input_schemas(self, mcp_server):
        """All tools should have properly defined input schemas."""
        async with create_connected_server_and_client_session(mcp_server) as client:
            tools = await client.list_tools()

            for tool in tools.tools:
                assert tool.inputSchema
                assert "type" in tool.inputSchema
                assert tool.inputSchema["type"] == "object"


class TestReadFileTool:
    """Test read_file tool via MCP protocol."""

    async def test_read_existing_file(self, mcp_server, git_repo_dir):
        """read_file should return file contents."""
        (git_repo_dir / "test.yaml").write_text("key: value\n", encoding="utf-8")

        async with create_connected_server_and_client_session(mcp_server) as client:
            result = await client.call_tool(
                "read_file", arguments={"file_path": "test.yaml"}
            )

            assert result.isError is False
            assert "key: value" in get_result_text(result)

    async def test_read_nonexistent_file_raises_error(self, mcp_server):
        """read_file should raise error for nonexistent files."""
        async with create_connected_server_and_client_session(mcp_server) as client:
            result = await client.call_tool(
                "read_file", arguments={"file_path": "nonexistent.yaml"}
            )
            # The SDK returns isError=True instead of raising ToolError
            assert result.isError is True
            assert "File not found" in get_result_text(result)

    async def test_read_file_with_path_traversal_raises_error(self, mcp_server):
        """read_file should reject path traversal attempts."""
        async with create_connected_server_and_client_session(mcp_server) as client:
            result = await client.call_tool(
                "read_file", arguments={"file_path": "../../../etc/passwd"}
            )
            assert result.isError is True
            assert "must be within config directory" in get_result_text(result)


class TestCreateFileTool:
    """Test create_file tool via MCP protocol."""

    async def test_create_new_file(self, mcp_server, git_repo_dir):
        """create_file should create new YAML files."""
        async with create_connected_server_and_client_session(mcp_server) as client:
            result = await client.call_tool(
                "create_file",
                arguments={
                    "file_path": "new.yaml",
                    "content": "name: test\nversion: 1\n",
                },
            )

            assert result.isError is False
            assert (git_repo_dir / "new.yaml").exists()
            assert "Successfully created" in get_result_text(result)

    async def test_create_file_with_invalid_yaml_raises_error(self, mcp_server):
        """create_file should reject invalid YAML."""
        async with create_connected_server_and_client_session(mcp_server) as client:
            result = await client.call_tool(
                "create_file",
                arguments={
                    "file_path": "invalid.yaml",
                    "content": "invalid: [unclosed\n",
                },
            )
            assert result.isError is True
            assert "Invalid YAML" in get_result_text(result)


class TestUpdateFileTool:
    """Test update_file tool via MCP protocol."""

    async def test_update_file_with_diff(self, mcp_server, git_repo_dir):
        """update_file should apply diff changes."""
        (git_repo_dir / "config.yaml").write_text("timeout: 30\n", encoding="utf-8")

        diff = """<<<<<<< SEARCH
timeout: 30
=======
timeout: 60
>>>>>>> REPLACE"""

        async with create_connected_server_and_client_session(mcp_server) as client:
            result = await client.call_tool(
                "update_file",
                arguments={"file_path": "config.yaml", "diff_content": diff},
            )

            assert result.isError is False
            assert "Successfully updated" in get_result_text(result)

            updated_content = (git_repo_dir / "config.yaml").read_text()
            assert "timeout: 60" in updated_content


class TestGrepFilesTool:
    """Test grep_files tool via MCP protocol."""

    async def test_grep_finds_matches(self, mcp_server, git_repo_dir):
        """grep_files should find pattern matches."""
        (git_repo_dir / "config1.yaml").write_text("timeout: 30\n", encoding="utf-8")
        (git_repo_dir / "config2.yaml").write_text("timeout: 60\n", encoding="utf-8")

        async with create_connected_server_and_client_session(mcp_server) as client:
            result = await client.call_tool(
                "grep_files", arguments={"search_pattern": "timeout"}
            )

            assert result.isError is False
            result_text = get_result_text(result)
            assert "config1.yaml" in result_text
            assert "config2.yaml" in result_text

    async def test_grep_no_matches_returns_message(self, mcp_server, git_repo_dir):
        """grep_files should return message when no matches found."""
        (git_repo_dir / "config.yaml").write_text("key: value\n", encoding="utf-8")

        async with create_connected_server_and_client_session(mcp_server) as client:
            result = await client.call_tool(
                "grep_files", arguments={"search_pattern": "nonexistent"}
            )

            assert result.isError is False
            assert "No matches found" in get_result_text(result)


class TestListDirectoryStructureTool:
    """Test list_directory_structure tool via MCP protocol."""

    async def test_list_structure_shows_yaml_files(self, mcp_server, git_repo_dir):
        """list_directory_structure should show YAML files in tree format."""
        (git_repo_dir / "test.yaml").touch()
        (git_repo_dir / "configs").mkdir()
        (git_repo_dir / "configs" / "sub.yaml").touch()

        async with create_connected_server_and_client_session(mcp_server) as client:
            result = await client.call_tool("list_directory_structure", arguments={})

            assert result.isError is False
            result_text = get_result_text(result)
            assert "test.yaml" in result_text
            assert "configs/" in result_text

    async def test_list_structure_prunes_empty_directories(
        self, mcp_server, git_repo_dir
    ):
        """list_directory_structure should prune directories with no YAML files."""
        (git_repo_dir / "has_yaml").mkdir()
        (git_repo_dir / "has_yaml" / "config.yaml").touch()

        (git_repo_dir / "empty_dir").mkdir()

        (git_repo_dir / "only_txt").mkdir()
        (git_repo_dir / "only_txt" / "readme.txt").touch()

        (git_repo_dir / "nested_empty").mkdir()
        (git_repo_dir / "nested_empty" / "subdir").mkdir()
        (git_repo_dir / "nested_empty" / "subdir" / "deep").mkdir()

        async with create_connected_server_and_client_session(mcp_server) as client:
            result = await client.call_tool("list_directory_structure", arguments={})

            assert result.isError is False
            result_text = get_result_text(result)
            assert "has_yaml/" in result_text
            assert "config.yaml" in result_text
            assert "empty_dir" not in result_text
            assert "only_txt" not in result_text
            assert "nested_empty" not in result_text

    async def test_list_structure_shows_nested_yaml_directories(
        self, mcp_server, git_repo_dir
    ):
        """list_directory_structure should show dirs with deeply nested YAML files."""
        (git_repo_dir / "deep").mkdir()
        (git_repo_dir / "deep" / "nested").mkdir()
        (git_repo_dir / "deep" / "nested" / "config.yml").touch()

        async with create_connected_server_and_client_session(mcp_server) as client:
            result = await client.call_tool("list_directory_structure", arguments={})

            assert result.isError is False
            result_text = get_result_text(result)
            assert "deep/" in result_text
            assert "nested/" in result_text
            assert "config.yml" in result_text


class TestMCPProtocolCompliance:
    """Test MCP protocol compliance."""

    async def test_tools_return_text_content(self, mcp_server, git_repo_dir):
        """All tools should return TextContent in responses."""
        (git_repo_dir / "test.yaml").write_text("key: value\n", encoding="utf-8")

        async with create_connected_server_and_client_session(mcp_server) as client:
            result = await client.call_tool(
                "read_file", arguments={"file_path": "test.yaml"}
            )

            assert len(result.content) > 0
            assert all(isinstance(c, TextContent) for c in result.content)

    async def test_error_responses_have_is_error_flag(self, mcp_server):
        """Error responses should have isError=True."""
        async with create_connected_server_and_client_session(mcp_server) as client:
            result = await client.call_tool(
                "read_file", arguments={"file_path": "nonexistent.yaml"}
            )
            assert result.isError is True

    async def test_tool_schema_validation(self, mcp_server):
        """Tool schemas should include required parameters."""
        async with create_connected_server_and_client_session(mcp_server) as client:
            tools = await client.list_tools()

            read_file_tool = next(t for t in tools.tools if t.name == "read_file")

            assert "properties" in read_file_tool.inputSchema
            assert "file_path" in read_file_tool.inputSchema["properties"]
            assert "required" in read_file_tool.inputSchema
            assert "file_path" in read_file_tool.inputSchema["required"]
