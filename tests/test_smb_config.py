"""Tests for SMB configuration and filesystem backend."""

import os
import pytest
from unittest.mock import patch

from mcp_yamlfilesystem.config import (
    Config,
    _parse_smb_path,
    _load_smb_config,
)
from mcp_yamlfilesystem.exceptions import YAMLConfigError
from mcp_yamlfilesystem.filesystem import LocalFileSystem, SMBFileSystem
from mcp_yamlfilesystem.yaml_manager import YAMLConfigManager


class TestParseSmbPath:
    """Tests for SMB path parsing."""

    def test_parse_double_slash_format(self):
        """Test parsing //server/share format."""
        server, share, base_path = _parse_smb_path("//fileserver/configs")
        assert server == "fileserver"
        assert share == "configs"
        assert base_path == ""

    def test_parse_with_base_path(self):
        """Test parsing //server/share/path format."""
        server, share, base_path = _parse_smb_path(
            "//nas.local/data/homeassistant/config"
        )
        assert server == "nas.local"
        assert share == "data"
        assert base_path == "homeassistant/config"

    def test_parse_backslash_format(self):
        """Test parsing \\\\server\\share format."""
        server, share, base_path = _parse_smb_path("\\\\fileserver\\configs")
        assert server == "fileserver"
        assert share == "configs"
        assert base_path == ""

    def test_parse_smb_uri_format(self):
        """Test parsing smb://server/share format."""
        server, share, base_path = _parse_smb_path("smb://fileserver/configs")
        assert server == "fileserver"
        assert share == "configs"
        assert base_path == ""

    def test_parse_smb_uri_with_path(self):
        """Test parsing smb://server/share/path format."""
        server, share, base_path = _parse_smb_path("smb://server/share/dir/subdir")
        assert server == "server"
        assert share == "share"
        assert base_path == "dir/subdir"

    def test_invalid_path_no_prefix(self):
        """Test that paths without // prefix raise error."""
        with pytest.raises(YAMLConfigError) as exc:
            _parse_smb_path("server/share")
        assert "Invalid SMB path format" in str(exc.value)

    def test_invalid_path_server_only(self):
        """Test that server-only paths raise error."""
        with pytest.raises(YAMLConfigError) as exc:
            _parse_smb_path("//server")
        assert "Must include at least server and share name" in str(exc.value)


class TestLoadSmbConfig:
    """Tests for SMB configuration loading."""

    def test_no_smb_config_returns_none(self):
        """Test that missing SMB config returns None."""
        result = _load_smb_config({})
        assert result is None

    def test_complete_config_from_dict(self):
        """Test loading complete SMB config from dict."""
        file_config = {
            "MCP_FILESYSTEM_SMB_PATH": "//server/share",
            "MCP_FILESYSTEM_SMB_USER": "testuser",
            "MCP_FILESYSTEM_SMB_PASSWORD": "testpass",
            "MCP_FILESYSTEM_SMB_IGNORE_DIRS": "",
        }
        result = _load_smb_config(file_config)
        assert result is not None
        assert result.server == "server"
        assert result.share == "share"
        assert result.username == "testuser"
        assert result.password == "testpass"
        assert result.base_path == ""

    def test_config_with_base_path(self):
        """Test loading SMB config with base path."""
        file_config = {
            "MCP_FILESYSTEM_SMB_PATH": "//server/share/subdir/path",
            "MCP_FILESYSTEM_SMB_USER": "user",
            "MCP_FILESYSTEM_SMB_PASSWORD": "pass",
            "MCP_FILESYSTEM_SMB_IGNORE_DIRS": "",
        }
        result = _load_smb_config(file_config)
        assert result.base_path == "subdir/path"

    def test_env_vars_override_config_file(self):
        """Test that environment variables take precedence."""
        file_config = {
            "MCP_FILESYSTEM_SMB_PATH": "//file-server/configs",
            "MCP_FILESYSTEM_SMB_USER": "fileuser",
            "MCP_FILESYSTEM_SMB_PASSWORD": "filepass",
            "MCP_FILESYSTEM_SMB_IGNORE_DIRS": "",
        }
        with patch.dict(
            os.environ,
            {
                "MCP_FILESYSTEM_SMB_PATH": "//env-server/env-share",
                "MCP_FILESYSTEM_SMB_USER": "envuser",
                "MCP_FILESYSTEM_SMB_PASSWORD": "envpass",
            },
        ):
            result = _load_smb_config(file_config)
            assert result.server == "env-server"
            assert result.share == "env-share"
            assert result.username == "envuser"
            assert result.password == "envpass"

    def test_partial_config_raises_error(self):
        """Test that partial SMB config raises error."""
        file_config = {
            "MCP_FILESYSTEM_SMB_PATH": "//server/share",
            "MCP_FILESYSTEM_SMB_USER": "user",
            # Missing MCP_FILESYSTEM_SMB_PASSWORD
        }
        with pytest.raises(YAMLConfigError) as exc:
            _load_smb_config(file_config)
        assert "Incomplete SMB configuration" in str(exc.value)
        assert "MCP_FILESYSTEM_SMB_PASSWORD" in str(exc.value)


class TestLoadConfigSmbMode:
    """Tests for load_config in SMB mode."""

    def test_smb_mode_skips_git_requirement(self):
        """Test that SMB mode skips git requirement."""
        with patch.dict(
            os.environ,
            {
                "MCP_FILESYSTEM_SMB_PATH": "//server/share",
                "MCP_FILESYSTEM_SMB_USER": "user",
                "MCP_FILESYSTEM_SMB_PASSWORD": "pass",
            },
            clear=True,
        ):
            # Remove any existing MCP_FILESYSTEM_LOCAL_PATH
            os.environ.pop("MCP_FILESYSTEM_LOCAL_PATH", None)
            os.environ.pop("ALLOWED_EXTENSIONS", None)

            config = Config.get()
            assert config.is_smb_mode
            assert config.smb_config is not None
            assert config.yaml_root_path is None

    def test_smb_mode_with_allowed_extensions(self, monkeypatch, tmp_path):
        """Test that SMB mode respects allowed_extensions from config file."""
        # Use a config file without ALLOWED_EXTENSIONS so env var is the source
        config_file = tmp_path / "smb_ext_config"
        config_file.write_text(
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
            "MCP_FILESYSTEM_SMB_IGNORE_DIRS=\n"
            "DEBUG=false\n"
            "LOG_FILE=\n",
            encoding="utf-8",
        )
        config_file.chmod(0o600)
        from mcp_yamlfilesystem import config as config_module

        monkeypatch.setattr(config_module, "get_config_file_path", lambda: config_file)
        with patch.dict(
            os.environ,
            {
                "MCP_FILESYSTEM_SMB_PATH": "//server/share",
                "MCP_FILESYSTEM_SMB_USER": "user",
                "MCP_FILESYSTEM_SMB_PASSWORD": "pass",
                "ALLOWED_EXTENSIONS": ".yaml,.yml,.json",
            },
            clear=True,
        ):
            config = Config.get()
            assert ".json" in config.allowed_extensions


class TestLocalFileSystem:
    """Tests for LocalFileSystem backend."""

    def test_init_with_valid_path(self, tmp_path):
        """Test initialization with valid path."""
        fs = LocalFileSystem(tmp_path)
        assert fs.root_path == str(tmp_path)

    def test_init_with_nonexistent_path(self, tmp_path):
        """Test initialization with nonexistent path raises error."""
        nonexistent = tmp_path / "nonexistent"
        with pytest.raises(ValueError) as exc:
            LocalFileSystem(nonexistent)
        assert "does not exist" in str(exc.value)

    def test_read_write_text(self, tmp_path):
        """Test reading and writing text files."""
        fs = LocalFileSystem(tmp_path)
        content = "key: value\n"
        fs.write_text("test.yaml", content)
        assert fs.read_text("test.yaml") == content

    def test_exists(self, tmp_path):
        """Test exists method."""
        fs = LocalFileSystem(tmp_path)
        assert not fs.exists("missing.yaml")
        (tmp_path / "exists.yaml").write_text("key: value")
        assert fs.exists("exists.yaml")

    def test_is_file(self, tmp_path):
        """Test is_file method."""
        fs = LocalFileSystem(tmp_path)
        (tmp_path / "file.yaml").write_text("key: value")
        (tmp_path / "dir").mkdir()
        assert fs.is_file("file.yaml")
        assert not fs.is_file("dir")

    def test_glob(self, tmp_path):
        """Test glob pattern matching."""
        fs = LocalFileSystem(tmp_path)
        (tmp_path / "a.yaml").write_text("a: 1")
        (tmp_path / "b.yaml").write_text("b: 2")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "c.yaml").write_text("c: 3")

        files = fs.glob("**/*.yaml")
        assert len(files) == 3
        assert "a.yaml" in files
        assert "b.yaml" in files

    def test_resolve_path_prevents_traversal(self, tmp_path):
        """Test that path traversal is prevented."""
        fs = LocalFileSystem(tmp_path)
        with pytest.raises(ValueError) as exc:
            fs.resolve_path("../../../etc/passwd")
        assert "escapes root" in str(exc.value)


class TestYAMLConfigManagerWithFilesystem:
    """Tests for YAMLConfigManager with filesystem backend."""

    def test_init_with_path(self, tmp_path):
        """Test initialization with Path (backward compatibility)."""
        manager = YAMLConfigManager(config_dir=tmp_path)
        assert manager.config_dir == tmp_path

    def test_init_with_filesystem(self, tmp_path):
        """Test initialization with filesystem backend."""
        fs = LocalFileSystem(tmp_path)
        manager = YAMLConfigManager(filesystem=fs)
        assert manager._filesystem is fs
        assert manager.config_dir is None

    def test_init_without_params_raises_error(self):
        """Test initialization without params raises error."""
        with pytest.raises(YAMLConfigError) as exc:
            YAMLConfigManager()
        assert "requires either config_dir or filesystem" in str(exc.value)

    def test_operations_work_with_filesystem_backend(self, tmp_path):
        """Test that all operations work with filesystem backend."""
        fs = LocalFileSystem(tmp_path)
        manager = YAMLConfigManager(filesystem=fs)

        # Create file
        manager.create_file("test.yaml", "key: value\n")

        # Read file
        content = manager.read_file("test.yaml")
        assert "key: value" in content

        # Write file
        manager.write_file("test.yaml", "key: updated\n")
        content = manager.read_file("test.yaml")
        assert "key: updated" in content

        # List files
        files = manager.list_yaml_files()
        assert "test.yaml" in files


class TestSMBFileSystemMocked:
    """Tests for SMBFileSystem with mocked smbprotocol."""

    def test_smb_path_construction(self):
        """Test SMB path construction."""
        fs = SMBFileSystem(
            server="server",
            share="share",
            username="user",
            password="pass",
            base_path="base/path",
        )
        assert fs.root_path == "//server/share/base/path"

    def test_smb_path_without_base(self):
        """Test SMB path construction without base path."""
        fs = SMBFileSystem(
            server="server",
            share="share",
            username="user",
            password="pass",
        )
        assert fs.root_path == "//server/share"

    def test_resolve_path_prevents_traversal(self):
        """Test that path traversal is prevented."""
        fs = SMBFileSystem(
            server="server",
            share="share",
            username="user",
            password="pass",
        )
        with pytest.raises(ValueError) as exc:
            fs.resolve_path("../../../etc/passwd")
        assert "escapes root" in str(exc.value)

    def test_resolve_path_normalizes(self):
        """Test that paths are normalized."""
        fs = SMBFileSystem(
            server="server",
            share="share",
            username="user",
            password="pass",
        )
        resolved = fs.resolve_path("subdir/./file.yaml")
        assert resolved == "subdir/file.yaml"

    def test_connect_establishes_tree_connection(self):
        """Test that SMBConnection._connect() establishes low-level SMB tree connection.

        Uses smbprotocol for compound request support, plus registers
        with smbclient for high-level file operations.
        """
        fs = SMBFileSystem(
            server="testserver.local",
            share="share",
            username="user",
            password="pass",
        )

        with (
            patch("smbclient.register_session") as mock_register,
            patch("smbprotocol.connection.Connection") as mock_connection,
            patch("smbprotocol.session.Session") as mock_session,
            patch("smbprotocol.tree.TreeConnect") as mock_tree,
        ):
            # Setup mocks
            mock_conn_instance = mock_connection.return_value
            mock_sess_instance = mock_session.return_value
            mock_tree_instance = mock_tree.return_value

            # Trigger connection via SMBConnection
            fs._conn._connect()

            # Verify low-level connection established
            mock_connection.assert_called_once()
            mock_conn_instance.connect.assert_called_once()

            # Verify session created with credentials
            mock_session.assert_called_once_with(
                connection=mock_conn_instance,
                username="user",
                password="pass",
            )
            mock_sess_instance.connect.assert_called_once()

            # Verify TreeConnect was created with session and share
            mock_tree.assert_called_once_with(
                mock_sess_instance, "\\\\testserver.local\\share"
            )
            mock_tree_instance.connect.assert_called_once()

            # Verify smbclient also registered for high-level ops
            mock_register.assert_called_once_with(
                "testserver.local",
                username="user",
                password="pass",
            )

    def test_connect_only_connects_once(self):
        """Test that SMBConnection._connect() only establishes connection once."""
        fs = SMBFileSystem(
            server="testserver.local",
            share="share",
            username="user",
            password="pass",
        )

        with (
            patch("smbclient.register_session") as mock_register,
            patch("smbprotocol.connection.Connection") as mock_connection,
            patch("smbprotocol.session.Session"),
            patch("smbprotocol.tree.TreeConnect"),
        ):
            # First connection
            fs._conn._connect()
            assert mock_connection.call_count == 1
            assert mock_register.call_count == 1

            # Second call should not connect again
            fs._conn._connect()
            assert mock_connection.call_count == 1
            assert mock_register.call_count == 1

    def test_connect_raises_ioerror_on_failure(self):
        """Test that SMBConnection._connect() wraps exceptions in IOError."""
        fs = SMBFileSystem(
            server="testserver.local",
            share="share",
            username="user",
            password="pass",
        )

        with patch("smbprotocol.connection.Connection") as mock_connection:
            mock_connection.return_value.connect.side_effect = Exception(
                "Network unreachable"
            )

            with pytest.raises(IOError) as exc:
                fs._conn._connect()
            assert "SMB connection failed" in str(exc.value)
            assert "Network unreachable" in str(exc.value)
