"""Integration tests for MCP server tools."""

import pytest

from mcp_yamlfilesystem.yaml_manager import YAMLConfigManager
from mcp_yamlfilesystem.diff_engine import YAMLDiffEngine


class TestReadFileTool:
    """Test read_file MCP tool integration."""

    def test_read_existing_file(self, git_repo_dir, sample_yaml_content):
        """Read existing file through manager."""
        manager = YAMLConfigManager(git_repo_dir)

        (git_repo_dir / "config.yaml").write_text(sample_yaml_content, encoding="utf-8")

        content = manager.read_file("config.yaml")
        assert content == sample_yaml_content

    def test_read_nested_file(self, nested_yaml_structure):
        """Read file in nested directory."""
        manager = YAMLConfigManager(nested_yaml_structure)

        content = manager.read_file("configs/automation/test.yaml")
        assert "automation" in content


class TestUpdateFileTool:
    """Test update_file MCP tool integration."""

    def test_update_file_with_diff(self, git_repo_dir):
        """Update file using diff engine."""
        manager = YAMLConfigManager(git_repo_dir)
        diff_engine = YAMLDiffEngine()

        original = "timeout: 30\nretries: 3\n"
        (git_repo_dir / "config.yaml").write_text(original, encoding="utf-8")

        diff = """<<<<<<< SEARCH
timeout: 30
=======
timeout: 60
>>>>>>> REPLACE"""

        current = manager.read_file("config.yaml")
        updated = diff_engine.apply_diff(current, diff)
        manager.write_file("config.yaml", updated)

        result = manager.read_file("config.yaml")
        assert "timeout: 60" in result
        assert "retries: 3" in result

    def test_update_multiple_blocks(self, git_repo_dir):
        """Update file with multiple diff blocks."""
        manager = YAMLConfigManager(git_repo_dir)
        diff_engine = YAMLDiffEngine()

        original = "name: old\nversion: 1\nenabled: false\n"
        (git_repo_dir / "config.yaml").write_text(original, encoding="utf-8")

        diff = """<<<<<<< SEARCH
name: old
=======
name: new
>>>>>>> REPLACE

<<<<<<< SEARCH
enabled: false
=======
enabled: true
>>>>>>> REPLACE"""

        current = manager.read_file("config.yaml")
        updated = diff_engine.apply_diff(current, diff)
        manager.write_file("config.yaml", updated)

        result = manager.read_file("config.yaml")
        assert "name: new" in result
        assert "enabled: true" in result


class TestCreateFileTool:
    """Test create_file MCP tool integration."""

    def test_create_new_file(self, git_repo_dir):
        """Create new file with valid content."""
        manager = YAMLConfigManager(git_repo_dir)

        content = "name: new_config\nversion: 1.0\n"
        manager.create_file("new.yaml", content)

        assert (git_repo_dir / "new.yaml").exists()
        assert manager.read_file("new.yaml") == content

    def test_create_file_with_nested_path(self, git_repo_dir):
        """Create file in nested directory structure."""
        manager = YAMLConfigManager(git_repo_dir)

        content = "sensor:\n  - name: test\n"
        manager.create_file("configs/sensor/new.yaml", content)

        assert (git_repo_dir / "configs" / "sensor" / "new.yaml").exists()


class TestGrepFilesTool:
    """Test grep_files MCP tool integration."""

    def test_grep_finds_matches(self, git_repo_dir):
        """Find pattern across files."""
        manager = YAMLConfigManager(git_repo_dir)

        (git_repo_dir / "config1.yaml").write_text("timeout: 30\n", encoding="utf-8")
        (git_repo_dir / "config2.yaml").write_text("timeout: 60\n", encoding="utf-8")

        results = manager.grep_files("timeout")
        assert len(results) == 2

    def test_grep_with_file_filter(self, nested_yaml_structure):
        """Filter grep to specific files."""
        manager = YAMLConfigManager(nested_yaml_structure)

        results = manager.grep_files("automation", "configs/automation/*.yaml")
        assert all("automation" in r["file"] for r in results)


class TestListDirectoryStructureTool:
    """Test list_directory_structure MCP tool integration."""

    def test_list_flat_structure(self, git_repo_dir):
        """List flat directory structure."""
        manager = YAMLConfigManager(git_repo_dir)

        (git_repo_dir / "file1.yaml").touch()
        (git_repo_dir / "file2.yaml").touch()

        files = manager.list_yaml_files()
        assert "file1.yaml" in files
        assert "file2.yaml" in files

    def test_list_nested_structure(self, nested_yaml_structure):
        """List nested directory structure."""
        manager = YAMLConfigManager(nested_yaml_structure)

        files = manager.list_yaml_files()
        assert len(files) >= 3


class TestEndToEndWorkflows:
    """Test complete end-to-end workflows."""

    def test_create_read_update_validate_workflow(self, git_repo_dir):
        """Complete workflow: create -> read -> update -> validate."""
        manager = YAMLConfigManager(git_repo_dir)
        diff_engine = YAMLDiffEngine()

        content = "name: initial\nversion: 1\n"
        manager.create_file("workflow.yaml", content)

        read_content = manager.read_file("workflow.yaml")
        assert "name: initial" in read_content

        diff = """<<<<<<< SEARCH
version: 1
=======
version: 2
>>>>>>> REPLACE"""
        updated = diff_engine.apply_diff(read_content, diff)
        manager.write_file("workflow.yaml", updated)

        final_content = manager.read_file("workflow.yaml")
        assert "version: 2" in final_content
        assert manager.validate_yaml(final_content) is True

    def test_search_and_modify_workflow(self, git_repo_dir):
        """Workflow: create files -> search -> modify based on results."""
        manager = YAMLConfigManager(git_repo_dir)
        diff_engine = YAMLDiffEngine()

        (git_repo_dir / "config1.yaml").write_text("timeout: 30\n", encoding="utf-8")
        (git_repo_dir / "config2.yaml").write_text("timeout: 30\n", encoding="utf-8")

        results = manager.grep_files("timeout: 30")
        assert len(results) == 2

        for result in results:
            content = manager.read_file(result["file"])
            diff = """<<<<<<< SEARCH
timeout: 30
=======
timeout: 60
>>>>>>> REPLACE"""
            updated = diff_engine.apply_diff(content, diff)
            manager.write_file(result["file"], updated)

        verify_results = manager.grep_files("timeout: 60")
        assert len(verify_results) == 2

    def test_complex_nested_structure_workflow(self, git_repo_dir):
        """Workflow with complex nested structure."""
        manager = YAMLConfigManager(git_repo_dir)

        manager.create_file("base.yaml", "base: config\n")
        manager.create_file("level1/sub.yaml", "level: 1\n")
        manager.create_file("level1/level2/deep.yaml", "level: 2\n")

        all_files = manager.list_yaml_files("**/*.yaml")
        assert len(all_files) == 3

        results = manager.grep_files("level")
        assert len(results) == 2


class TestRunTestFunction:
    """Tests for _run_test() CLI function."""

    def test_run_test_local_success(self, git_repo_dir, capsys, reset_server_state):
        """Test --test with local filesystem succeeds."""
        import os
        from unittest.mock import patch

        # Create a YAML file
        (git_repo_dir / "test.yaml").write_text("key: value\n", encoding="utf-8")

        with patch.dict(
            os.environ,
            {"MCP_FILESYSTEM_LOCAL_PATH": str(git_repo_dir)},
            clear=True,
        ):
            from mcp_yamlfilesystem.server import _run_test

            _run_test()

        captured = capsys.readouterr()
        assert "Testing local filesystem at" in captured.out
        assert "Running list_directory_structure" in captured.out
        assert "Found 1 YAML file(s)" in captured.out
        assert "test.yaml" in captured.out

    def test_run_test_local_with_multiple_files(
        self, git_repo_dir, capsys, reset_server_state
    ):
        """Test --test shows directory tree when multiple files exist."""
        import os
        from unittest.mock import patch

        # Create multiple YAML files
        for i in range(7):
            (git_repo_dir / f"config{i}.yaml").write_text(
                f"key: {i}\n", encoding="utf-8"
            )

        with patch.dict(
            os.environ,
            {"MCP_FILESYSTEM_LOCAL_PATH": str(git_repo_dir)},
            clear=True,
        ):
            from mcp_yamlfilesystem.server import _run_test

            _run_test()

        captured = capsys.readouterr()
        assert "Found 7 YAML file(s)" in captured.out
        # All files should be shown in tree format
        assert "config0.yaml" in captured.out
        assert "config6.yaml" in captured.out

    def test_run_test_local_failure(self, tmp_path, capsys, reset_server_state):
        """Test --test with invalid path fails."""
        import os
        from unittest.mock import patch

        nonexistent = tmp_path / "nonexistent"

        with patch.dict(
            os.environ,
            {"MCP_FILESYSTEM_LOCAL_PATH": str(nonexistent)},
            clear=True,
        ):
            from mcp_yamlfilesystem.server import _run_test

            with pytest.raises(SystemExit) as exc:
                _run_test()
            assert exc.value.code == 1

        captured = capsys.readouterr()
        assert "ERROR - Test failed" in captured.err

    def test_run_test_smb_success(self, capsys, reset_server_state):
        """Test --test with mocked SMB succeeds."""
        import os
        from unittest.mock import patch, MagicMock

        with patch.dict(
            os.environ,
            {
                "MCP_FILESYSTEM_SMB_PATH": "//server/share",
                "MCP_FILESYSTEM_SMB_USER": "user",
                "MCP_FILESYSTEM_SMB_PASSWORD": "pass",
            },
            clear=True,
        ):
            # Mock the YAMLConfigManager that MCPServer.get() creates
            with patch(
                "mcp_yamlfilesystem.server.YAMLConfigManager"
            ) as mock_manager_cls:
                mock_manager = MagicMock()
                mock_manager.list_yaml_files.return_value = [
                    "config.yaml",
                    "settings.yaml",
                ]
                mock_manager._filesystem.root_path = "//server/share"
                mock_manager_cls.return_value = mock_manager

                from mcp_yamlfilesystem.server import _run_test

                _run_test()

        captured = capsys.readouterr()
        assert "Testing SMB connection to //server/share" in captured.out
        assert "Running list_directory_structure" in captured.out
        assert "Found 2 YAML file(s)" in captured.out

    def test_run_test_smb_connection_failure(self, capsys, reset_server_state):
        """Test --test with SMB connection failure."""
        import os
        from unittest.mock import patch, MagicMock

        with patch.dict(
            os.environ,
            {
                "MCP_FILESYSTEM_SMB_PATH": "//server/share",
                "MCP_FILESYSTEM_SMB_USER": "user",
                "MCP_FILESYSTEM_SMB_PASSWORD": "pass",
            },
            clear=True,
        ):
            # Mock the YAMLConfigManager to raise IOError
            with patch(
                "mcp_yamlfilesystem.server.YAMLConfigManager"
            ) as mock_manager_cls:
                mock_manager = MagicMock()
                mock_manager.list_yaml_files.side_effect = IOError(
                    "SMB connection failed: Network unreachable"
                )
                mock_manager_cls.return_value = mock_manager

                from mcp_yamlfilesystem.server import _run_test

                with pytest.raises(SystemExit) as exc:
                    _run_test()
                assert exc.value.code == 1

        captured = capsys.readouterr()
        assert "ERROR - Test failed" in captured.err
        assert "SMB connection failed" in captured.err
