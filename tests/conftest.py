"""Pytest configuration and fixtures for MCP YAML Filesystem tests."""

import pytest


@pytest.fixture(autouse=True)
def isolate_config_file(tmp_path, monkeypatch):
    """Prevent real user config file from interfering with tests.

    This autouse fixture ensures tests don't accidentally read from the user's
    actual ~/.config/mcp-yamlfilesystem/config file, which could contain
    credentials and affect test behavior.

    Also resets server module global state and Config singleton to prevent
    cached state from leaking between tests.
    """
    import logging

    from mcp_yamlfilesystem import config
    from mcp_yamlfilesystem.config import Config
    from mcp_yamlfilesystem.server import MCPServer

    # Reset Config singleton before each test
    Config.reset()

    # Reset MCPServer singleton before each test
    MCPServer.reset()

    # Clear handlers from loggers that may have been configured by previous tests
    # This ensures caplog can capture log messages properly
    for logger_name in ("mcp_yamlfilesystem", "mcp_yamlfilesystem.config"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True

    # Create a minimal config file with all required keys (matching config.example defaults)
    test_config = tmp_path / "test_config"
    test_config.write_text(
        "MCP_FILESYSTEM_LOCAL_PATH=\n"
        "ALLOWED_EXTENSIONS=.yaml,.yml\n"
        "DEBUG=false\n"
        "LOG_FILE=\n"
        "MCP_HTTP_ENABLED=false\n"
        "MCP_HTTP_HOST=127.0.0.1\n"
        "MCP_HTTP_PORT=8000\n"
        "MCP_HTTP_PATH=/mcp\n"
        "MCP_OAUTH_ENABLED=false\n"
        "MCP_OAUTH_CLIENT_ID=\n"
        "MCP_OAUTH_CLIENT_SECRET=\n"
        "MCP_OAUTH_BASE_URL=\n"
        "MCP_OAUTH_ALLOWED_EMAILS=\n"
        "MCP_FILESYSTEM_SMB_PATH=\n"
        "MCP_FILESYSTEM_SMB_USER=\n"
        "MCP_FILESYSTEM_SMB_PASSWORD=\n"
        "MCP_FILESYSTEM_SMB_IGNORE_DIRS=\n",
        encoding="utf-8",
    )
    test_config.chmod(0o600)
    monkeypatch.setattr(config, "get_config_file_path", lambda: test_config)


@pytest.fixture
def temp_dir(tmp_path):
    """Create temporary directory for tests."""
    temp_path = tmp_path / "temp_dir"
    temp_path.mkdir()
    return temp_path


@pytest.fixture
def git_repo_dir(tmp_path):
    """Create temporary directory with .git folder (mock git repo)."""
    temp_path = tmp_path / "git_repo"
    temp_path.mkdir()
    git_dir = temp_path / ".git"
    git_dir.mkdir()
    return temp_path


@pytest.fixture
def non_git_dir(tmp_path):
    """Create temporary directory without .git folder."""
    temp_path = tmp_path / "non_git"
    temp_path.mkdir()
    return temp_path


@pytest.fixture
def sample_yaml_content():
    """Sample valid YAML content for tests."""
    return """name: test_config
version: 1.0
settings:
  timeout: 30
  retries: 3
  enabled: true
items:
  - id: 1
    name: first
  - id: 2
    name: second
"""


@pytest.fixture
def invalid_yaml_content():
    """Invalid YAML content for testing error handling."""
    return """name: test
invalid: [unclosed bracket
  bad: indentation
"""


@pytest.fixture
def _sample_yaml_file(git_repo_dir, sample_yaml_content):
    """Create sample YAML file in git repo."""
    file_path = git_repo_dir / "test.yaml"
    file_path.write_text(sample_yaml_content, encoding="utf-8")
    return file_path


@pytest.fixture
def nested_yaml_structure(git_repo_dir):
    """Create nested directory structure with YAML files."""
    (git_repo_dir / "configs").mkdir()
    (git_repo_dir / "configs" / "automation").mkdir()
    (git_repo_dir / "configs" / "sensor").mkdir()

    (git_repo_dir / "main.yaml").write_text("key: value\n", encoding="utf-8")
    (git_repo_dir / "configs" / "automation" / "test.yaml").write_text(
        "automation:\n  - id: 1\n", encoding="utf-8"
    )
    (git_repo_dir / "configs" / "sensor" / "temp.yaml").write_text(
        "sensor:\n  - platform: mqtt\n", encoding="utf-8"
    )

    yield git_repo_dir


@pytest.fixture
def reset_server_state():
    """Reset MCPServer singleton between tests.

    The MCPServer is a singleton that persists between tests. This fixture
    resets it so that MCPServer.get() creates a fresh instance.
    """
    from mcp_yamlfilesystem.server import MCPServer

    # Reset singleton before test
    MCPServer.reset()

    yield

    # Reset again after test for cleanliness
    MCPServer.reset()
