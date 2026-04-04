"""Tests for YAMLConfigManager file operations."""

import pytest
from pathlib import Path

from mcp_yamlfilesystem.yaml_manager import YAMLConfigManager
from mcp_yamlfilesystem.exceptions import (
    YAMLConfigError,
    YAMLSyntaxError,
)


class TestFileReading:
    """Test file reading operations."""

    def test_read_existing_file(
        self, git_repo_dir, _sample_yaml_file, sample_yaml_content
    ):
        """Read existing YAML file successfully."""
        manager = YAMLConfigManager(git_repo_dir)

        content = manager.read_file("test.yaml")
        assert content == sample_yaml_content

    def test_read_nonexistent_file(self, git_repo_dir):
        """Raise FileNotFoundError for nonexistent files."""
        manager = YAMLConfigManager(git_repo_dir)

        with pytest.raises(FileNotFoundError, match="File not found"):
            manager.read_file("nonexistent.yaml")

    def test_read_nested_file(self, nested_yaml_structure):
        """Read file in nested directory."""
        manager = YAMLConfigManager(nested_yaml_structure)

        content = manager.read_file("configs/automation/test.yaml")
        assert "automation:" in content


class TestFileWriting:
    """Test file writing operations."""

    def test_write_valid_yaml(self, git_repo_dir):
        """Write valid YAML content to file."""
        manager = YAMLConfigManager(git_repo_dir)

        yaml_content = "key: value\nlist:\n  - item1\n  - item2\n"
        manager.write_file("test.yaml", yaml_content)

        written_content = (git_repo_dir / "test.yaml").read_text()
        assert written_content == yaml_content

    def test_reject_invalid_yaml_syntax(self, git_repo_dir, invalid_yaml_content):
        """Reject writing content with invalid YAML syntax."""
        manager = YAMLConfigManager(git_repo_dir)

        with pytest.raises(YAMLSyntaxError, match="Invalid YAML syntax"):
            manager.write_file("test.yaml", invalid_yaml_content)

    def test_write_creates_parent_directories(self, git_repo_dir):
        """Automatically create parent directories when writing."""
        manager = YAMLConfigManager(git_repo_dir)

        manager.write_file("configs/automation/new.yaml", "data: test\n")

        assert (git_repo_dir / "configs" / "automation" / "new.yaml").exists()

    def test_overwrite_existing_file(self, git_repo_dir, _sample_yaml_file):
        """Overwrite existing file with new content."""
        manager = YAMLConfigManager(git_repo_dir)

        new_content = "updated: true\n"
        manager.write_file("test.yaml", new_content)

        assert (git_repo_dir / "test.yaml").read_text() == new_content


class TestFileCreation:
    """Test file creation operations."""

    def test_create_new_file(self, git_repo_dir):
        """Create new YAML file successfully."""
        manager = YAMLConfigManager(git_repo_dir)

        content = "name: new_file\nversion: 1\n"
        manager.create_file("new.yaml", content)

        assert (git_repo_dir / "new.yaml").exists()
        assert (git_repo_dir / "new.yaml").read_text() == content

    def test_reject_create_existing_file(self, git_repo_dir, _sample_yaml_file):
        """Reject creation if file already exists."""
        manager = YAMLConfigManager(git_repo_dir)

        with pytest.raises(FileExistsError, match="already exists"):
            manager.create_file("test.yaml", "new: content\n")

    def test_create_with_nested_path(self, git_repo_dir):
        """Create file with nested directory path."""
        manager = YAMLConfigManager(git_repo_dir)

        manager.create_file("configs/sensor/temp.yaml", "sensor:\n  - name: test\n")

        assert (git_repo_dir / "configs" / "sensor" / "temp.yaml").exists()

    def test_reject_invalid_yaml_on_create(self, git_repo_dir, invalid_yaml_content):
        """Reject creation with invalid YAML syntax."""
        manager = YAMLConfigManager(git_repo_dir)

        with pytest.raises(YAMLSyntaxError):
            manager.create_file("invalid.yaml", invalid_yaml_content)


class TestYAMLValidation:
    """Test YAML syntax validation."""

    def test_validate_correct_yaml(self, git_repo_dir, sample_yaml_content):
        """Validate correct YAML syntax."""
        manager = YAMLConfigManager(git_repo_dir)

        assert manager.validate_yaml(sample_yaml_content) is True

    def test_reject_invalid_yaml(self, git_repo_dir, invalid_yaml_content):
        """Reject invalid YAML syntax."""
        manager = YAMLConfigManager(git_repo_dir)

        with pytest.raises(YAMLSyntaxError, match="Invalid YAML syntax"):
            manager.validate_yaml(invalid_yaml_content)

    def test_validate_empty_yaml(self, git_repo_dir):
        """Accept empty YAML (valid)."""
        manager = YAMLConfigManager(git_repo_dir)

        assert manager.validate_yaml("") is True

    def test_validate_yaml_with_unicode(self, git_repo_dir):
        """Validate YAML with unicode characters."""
        manager = YAMLConfigManager(git_repo_dir)

        unicode_yaml = "name: café\ngreeting: こんにちは\n"
        assert manager.validate_yaml(unicode_yaml) is True


class TestFileListin:
    """Test file listing operations."""

    def test_list_yaml_files_in_flat_directory(self, git_repo_dir):
        """List YAML files in flat directory structure."""
        manager = YAMLConfigManager(git_repo_dir)

        (git_repo_dir / "file1.yaml").touch()
        (git_repo_dir / "file2.yml").touch()
        (git_repo_dir / "file3.txt").touch()

        files = manager.list_yaml_files("*.yaml")
        assert "file1.yaml" in files
        assert "file3.txt" not in files

    def test_list_yaml_files_recursive(self, nested_yaml_structure):
        """List YAML files recursively."""
        manager = YAMLConfigManager(nested_yaml_structure)

        files = manager.list_yaml_files("**/*.yaml")
        assert "main.yaml" in files
        assert "configs/automation/test.yaml" in files
        assert "configs/sensor/temp.yaml" in files

    def test_list_with_glob_pattern(self, nested_yaml_structure):
        """List files matching specific glob pattern."""
        manager = YAMLConfigManager(nested_yaml_structure)

        files = manager.list_yaml_files("configs/automation/*.yaml")
        assert any("automation" in f for f in files)
        assert not any("sensor" in f for f in files)

    def test_list_includes_yml_extension(self, git_repo_dir):
        """List includes both .yaml and .yml extensions."""
        manager = YAMLConfigManager(git_repo_dir)

        (git_repo_dir / "test.yaml").touch()
        (git_repo_dir / "test.yml").touch()

        files = manager.list_yaml_files("*.yaml")
        assert len(files) == 2


class TestGrepFunctionality:
    """Test search/grep operations."""

    def test_grep_finds_matches(self, nested_yaml_structure):
        """Find pattern matches across files."""
        manager = YAMLConfigManager(nested_yaml_structure)

        results = manager.grep_files("automation")
        assert len(results) > 0
        assert any("automation" in r["content"].lower() for r in results)

    def test_grep_returns_file_line_content(self, git_repo_dir):
        """Return file path, line number, and content."""
        manager = YAMLConfigManager(git_repo_dir)

        (git_repo_dir / "test.yaml").write_text(
            "line1: value1\nline2: value2\nline3: value3\n"
        )

        results = manager.grep_files("value2")
        assert len(results) == 1
        assert results[0]["file"] == "test.yaml"
        assert results[0]["line"] == 2
        assert "value2" in results[0]["content"]

    def test_grep_with_regex_pattern(self, git_repo_dir):
        """Search with regex patterns."""
        manager = YAMLConfigManager(git_repo_dir)

        (git_repo_dir / "test.yaml").write_text(
            "timeout: 30\nretries: 5\nenabled: true\n"
        )

        results = manager.grep_files(r"timeout.*\d+")
        assert len(results) == 1
        assert "timeout" in results[0]["content"]

    def test_grep_case_insensitive(self, git_repo_dir):
        """Search is case-insensitive."""
        manager = YAMLConfigManager(git_repo_dir)

        (git_repo_dir / "test.yaml").write_text("Name: TestValue\n")

        results_lower = manager.grep_files("name")
        results_upper = manager.grep_files("NAME")
        results_mixed = manager.grep_files("NaMe")

        assert len(results_lower) == 1
        assert len(results_upper) == 1
        assert len(results_mixed) == 1

    def test_grep_with_file_pattern_filter(self, nested_yaml_structure):
        """Filter search to specific files with glob pattern."""
        manager = YAMLConfigManager(nested_yaml_structure)

        results = manager.grep_files("sensor", "configs/sensor/*.yaml")
        assert len(results) > 0
        assert all("sensor" in r["file"] for r in results)

    def test_grep_no_matches_returns_empty(self, git_repo_dir):
        """Return empty list when no matches found."""
        manager = YAMLConfigManager(git_repo_dir)

        (git_repo_dir / "test.yaml").write_text("key: value\n")

        results = manager.grep_files("nonexistent_pattern")
        assert results == []

    def test_grep_invalid_regex_raises_error(self, git_repo_dir):
        """Raise error for invalid regex patterns."""
        manager = YAMLConfigManager(git_repo_dir)

        (git_repo_dir / "test.yaml").write_text("data: value\n")

        with pytest.raises(YAMLConfigError, match="Invalid search pattern"):
            manager.grep_files("[invalid(regex")

    def test_grep_respects_max_matches_limit(self, git_repo_dir):
        """Respect maximum match limit."""
        manager = YAMLConfigManager(git_repo_dir)

        lines = "\n".join([f"line{i}: value" for i in range(1000)])
        (git_repo_dir / "large.yaml").write_text(lines)

        results = manager.grep_files("line")
        assert len(results) <= 500


class TestManagerInitialization:
    """Test YAMLConfigManager initialization."""

    def test_initialize_with_valid_directory(self, git_repo_dir):
        """Initialize successfully with valid directory."""
        manager = YAMLConfigManager(git_repo_dir)
        assert manager.config_dir == git_repo_dir.resolve()

    def test_reject_nonexistent_directory(self):
        """Reject initialization with nonexistent directory."""
        with pytest.raises(YAMLConfigError, match="does not exist"):
            YAMLConfigManager(Path("/nonexistent/path"))

    def test_reject_file_as_directory(self, git_repo_dir):
        """Reject initialization with file instead of directory."""
        file_path = git_repo_dir / "file.txt"
        file_path.touch()

        with pytest.raises(YAMLConfigError, match="not a directory"):
            YAMLConfigManager(file_path)


class TestCustomYAMLTags:
    """Test handling of custom YAML tags like Home Assistant's !include."""

    def test_validate_yaml_with_include_tag(self, git_repo_dir):
        """Validate YAML containing !include tag."""
        manager = YAMLConfigManager(git_repo_dir)

        yaml_with_include = "utility_meter: !include configs/utility_meter.yaml\n"
        assert manager.validate_yaml(yaml_with_include) is True

    def test_validate_yaml_with_secret_tag(self, git_repo_dir):
        """Validate YAML containing !secret tag."""
        manager = YAMLConfigManager(git_repo_dir)

        yaml_with_secret = "api_key: !secret my_api_key\n"
        assert manager.validate_yaml(yaml_with_secret) is True

    def test_validate_yaml_with_include_dir_tags(self, git_repo_dir):
        """Validate YAML containing !include_dir_* tags."""
        manager = YAMLConfigManager(git_repo_dir)

        yaml_content = """
automation: !include_dir_list automation/
sensor: !include_dir_merge_named sensors/
script: !include_dir_merge_list scripts/
"""
        assert manager.validate_yaml(yaml_content) is True

    def test_validate_yaml_with_env_var_tag(self, git_repo_dir):
        """Validate YAML containing !env_var tag."""
        manager = YAMLConfigManager(git_repo_dir)

        yaml_with_env = "database_url: !env_var DATABASE_URL\n"
        assert manager.validate_yaml(yaml_with_env) is True

    def test_write_file_with_custom_tags(self, git_repo_dir):
        """Write YAML file containing custom tags."""
        manager = YAMLConfigManager(git_repo_dir)

        yaml_content = """homeassistant:
  name: Home
  packages: !include_dir_named packages/
  secrets: !secret home_secret
"""
        manager.write_file("config.yaml", yaml_content)

        written = (git_repo_dir / "config.yaml").read_text()
        assert "!include_dir_named" in written
        assert "!secret" in written

    def test_create_file_with_custom_tags(self, git_repo_dir):
        """Create YAML file containing custom tags."""
        manager = YAMLConfigManager(git_repo_dir)

        yaml_content = "automation: !include automations.yaml\n"
        manager.create_file("home.yaml", yaml_content)

        assert (git_repo_dir / "home.yaml").exists()
        content = (git_repo_dir / "home.yaml").read_text()
        assert "!include" in content

    def test_validate_complex_nested_custom_tags(self, git_repo_dir):
        """Validate complex YAML with nested custom tags."""
        manager = YAMLConfigManager(git_repo_dir)

        complex_yaml = """
homeassistant:
  packages: !include_dir_named packages/
  customize: !include customize.yaml

automation: !include_dir_list automations/

sensor:
  - platform: template
    sensors: !include sensors/templates.yaml

script: !include scripts.yaml

input_boolean: !include_dir_merge_named inputs/

lovelace:
  mode: yaml
  resources: !include resources.yaml
  dashboards: !include_dir_named dashboards/
"""
        assert manager.validate_yaml(complex_yaml) is True
