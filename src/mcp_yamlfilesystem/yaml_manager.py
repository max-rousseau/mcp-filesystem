"""
Module: yaml_manager

Purpose:
    Secure YAML configuration file manager with comprehensive path validation
    and security enforcement. Provides core file operations (read, write, create,
    search) while ensuring all operations stay within root directory boundaries.

    Supports both local filesystem and SMB share backends through the
    FileSystemBackend abstraction.

Classes:
    - YAMLConfigManager: Main manager class for secure YAML operations

Functions:
    - validate_path: Security-focused path validation
    - read_file: Read YAML file contents
    - write_file: Write YAML with validation
    - create_file: Create new YAML files
    - list_yaml_files: List files matching patterns
    - grep_files: Search across YAML files
    - validate_yaml: Validate YAML syntax

Security Features:
    - Directory containment enforcement
    - Extension whitelisting (.yaml, .yml only)
    - Symlink resolution and validation
    - Path traversal attack prevention
    - Null byte injection protection
    - Control character filtering

Usage Example:
    from pathlib import Path
    from mcp_yamlfilesystem.yaml_manager import YAMLConfigManager
    from mcp_yamlfilesystem.filesystem import LocalFileSystem, SMBFileSystem

    # Initialize with root directory (local mode)
    manager = YAMLConfigManager(Path("/home/user/configs"))

    # Or with SMB backend (no root required, private to process)
    smb_fs = SMBFileSystem(
        server="fileserver",
        share="configs",
        username="user",
        password="pass"
    )
    manager = YAMLConfigManager(filesystem=smb_fs)

    # Read file
    content = manager.read_file("app/settings.yaml")

    # Write file
    manager.write_file("app/settings.yaml", "key: value\\n")

    # Search files
    results = manager.grep_files("api_key", "**/*.yaml")

Happy Path Flow:

```mermaid
sequenceDiagram
    participant Client
    participant YAMLConfigManager
    participant PathValidator
    participant FileSystem
    participant YAMLParser

    Client->>YAMLConfigManager: read_file("config.yaml")
    YAMLConfigManager->>PathValidator: validate_path()
    PathValidator->>PathValidator: check absolute path
    PathValidator->>PathValidator: check null bytes
    PathValidator->>PathValidator: resolve symlinks
    PathValidator->>PathValidator: check containment
    PathValidator->>PathValidator: check extension
    PathValidator-->>YAMLConfigManager: validated Path
    YAMLConfigManager->>FileSystem: read_text()
    FileSystem-->>YAMLConfigManager: content
    YAMLConfigManager-->>Client: YAML content

    Client->>YAMLConfigManager: write_file("config.yaml", content)
    YAMLConfigManager->>YAMLParser: validate_yaml(content)
    YAMLParser->>YAMLParser: safe_load_yaml() with custom tag support
    YAMLParser-->>YAMLConfigManager: valid
    YAMLConfigManager->>PathValidator: validate_path()
    PathValidator-->>YAMLConfigManager: validated Path
    YAMLConfigManager->>FileSystem: write_text()
    FileSystem-->>YAMLConfigManager: success
    YAMLConfigManager-->>Client: success
```
"""

import re
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

from .exceptions import YAMLConfigError, YAMLSyntaxError, FilePathError
from .filesystem import FileSystemBackend, LocalFileSystem

logger = logging.getLogger(__name__)


class CustomTagLoader(yaml.SafeLoader):
    """YAML SafeLoader that handles unknown custom tags gracefully.

    Applications like Home Assistant use custom YAML tags such as
    !include, !secret, !include_dir_list, etc. This loader allows
    syntax validation of such files without requiring the actual
    tag constructors.

    Unknown tags are preserved as their scalar/sequence/mapping values
    without raising ConstructorError.
    """

    pass


def _construct_undefined(loader: yaml.Loader, node: yaml.Node) -> Any:
    """Handle unknown YAML tags by returning their underlying value."""
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    elif isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


# Register handler for all unknown tags
CustomTagLoader.add_constructor(None, _construct_undefined)


def safe_load_yaml(content: str) -> Any:
    """Load YAML content safely, handling custom tags.

    Uses CustomTagLoader to parse YAML that may contain application-specific
    tags like !include, !secret, etc. These tags are handled gracefully
    without requiring their actual constructors.

    Args:
        content: YAML string to parse.

    Returns:
        Parsed YAML data structure.

    Raises:
        yaml.YAMLError: If YAML syntax is invalid.
    """
    # Safe: CustomTagLoader inherits from yaml.SafeLoader and only overrides the
    # fallback constructor to return primitive types (scalar/sequence/mapping).
    # No arbitrary Python object instantiation is possible.
    return yaml.load(content, Loader=CustomTagLoader)  # nosec B506


class YAMLConfigManager:
    """Secure YAML configuration file manager with path validation.

    Enforces strict security boundaries to prevent unauthorized file access:
    - Directory containment (all paths must be within root)
    - Extension whitelisting (configurable, defaults to .yaml, .yml)
    - YAML syntax validation before writes
    - Path traversal protection

    Supports both local filesystem and SMB share backends through the
    FileSystemBackend abstraction. SMB mode works without root privileges
    and keeps the connection private to the process.

    Attributes:
        config_dir: Root directory path (absolute, resolved) - for local mode
        allowed_extensions: Set of permitted file extensions
        _filesystem: FileSystemBackend instance for file operations

    Example:
        >>> from pathlib import Path
        >>> manager = YAMLConfigManager(Path("/home/user/configs"))
        >>> content = manager.read_file("settings.yaml")
        >>> manager.write_file("settings.yaml", "key: new_value\\n")

        >>> # SMB mode
        >>> from mcp_yamlfilesystem.filesystem import SMBFileSystem
        >>> smb_fs = SMBFileSystem("server", "share", "user", "pass")
        >>> manager = YAMLConfigManager(filesystem=smb_fs)
    """

    def __init__(
        self,
        config_dir: Optional[Path] = None,
        allowed_extensions: set[str] | None = None,
        filesystem: Optional[FileSystemBackend] = None,
    ) -> None:
        """Initialize YAML configuration manager.

        Can be initialized in two ways:
        1. With config_dir (Path) for local filesystem mode
        2. With filesystem (FileSystemBackend) for SMB or other backends

        Args:
            config_dir: Root directory for YAML files (local mode).
            allowed_extensions: Set of allowed file extensions (e.g., {'.yaml', '.yml'}).
                               Defaults to {'.yaml', '.yml'} if not provided.
            filesystem: FileSystemBackend instance for file operations.
                       If provided, config_dir is ignored.

        Raises:
            YAMLConfigError: If neither config_dir nor filesystem is provided,
                            or if config_dir doesn't exist or isn't a directory.

        Example:
            >>> from pathlib import Path
            >>> manager = YAMLConfigManager(Path("/valid/path"))
            >>> print(manager.config_dir)
            /valid/path

            >>> manager = YAMLConfigManager(
            ...     Path("/valid/path"),
            ...     allowed_extensions={'.yaml', '.yml', '.json'}
            ... )
            >>> print(manager.allowed_extensions)
            {'.yaml', '.yml', '.json'}

            >>> manager = YAMLConfigManager(Path("/nonexistent"))
            Traceback (most recent call last):
            ...
            YAMLConfigError: Configuration directory does not exist...
        """
        self.allowed_extensions = (
            allowed_extensions if allowed_extensions else {".yaml", ".yml"}
        )

        if filesystem is not None:
            # Use provided filesystem backend
            self._filesystem = filesystem
            self.config_dir = None
            logger.debug(
                f"YAMLConfigManager initialized with backend: {filesystem.root_path} "
                f"(extensions: {self.allowed_extensions})"
            )
        elif config_dir is not None:
            # Local filesystem mode
            self.config_dir = config_dir.resolve()

            if not self.config_dir.exists():
                raise YAMLConfigError(
                    f"Configuration directory does not exist: {self.config_dir}"
                )

            if not self.config_dir.is_dir():
                raise YAMLConfigError(
                    f"Configuration path is not a directory: {self.config_dir}"
                )

            self._filesystem = LocalFileSystem(self.config_dir)
            logger.debug(
                f"YAMLConfigManager initialized: {self.config_dir} "
                f"(extensions: {self.allowed_extensions})"
            )
        else:
            raise YAMLConfigError(
                "YAMLConfigManager requires either config_dir or filesystem parameter"
            )

    def validate_path(self, file_path: str) -> str:
        """Validate and resolve file path within config directory.

        Security checks performed:
        1. Rejects absolute paths (security: prevent arbitrary file access)
        2. Rejects paths with null bytes or control characters (security: injection)
        3. Resolves symlinks and verifies containment (security: path traversal)
        4. Validates file extension (security: file type restriction)

        Args:
            file_path: Relative path to YAML file.

        Returns:
            Validated relative path string (for use with filesystem backend).

        Raises:
            FilePathError: If path is invalid, outside config directory, or wrong extension.

        Example:
            >>> manager = YAMLConfigManager(Path("/home/user/configs"))
            >>> valid = manager.validate_path("app/settings.yaml")
            >>> print(valid)
            app/settings.yaml

            >>> manager.validate_path("/etc/passwd")
            Traceback (most recent call last):
            ...
            FilePathError: Absolute paths are not allowed...

            >>> manager.validate_path("../../etc/passwd")
            Traceback (most recent call last):
            ...
            FilePathError: File path must be within config directory...

            >>> manager.validate_path("config.txt")
            Traceback (most recent call last):
            ...
            FilePathError: Only YAML files (.yaml, .yml) are supported...
        """
        if "\x00" in file_path or any(
            ord(c) < 32 and c not in "\n\r\t" for c in file_path
        ):
            raise FilePathError(
                "File path contains invalid characters (null bytes or control characters)"
            )

        path = Path(file_path)

        if path.is_absolute():
            raise FilePathError(
                "Absolute paths are not allowed. Use relative paths from the root directory."
            )

        # Use filesystem backend for path resolution and containment check
        try:
            resolved = self._filesystem.resolve_path(file_path)
        except ValueError as e:
            raise FilePathError(
                f"File path must be within config directory: {file_path}"
            ) from e

        # Check extension
        suffix = Path(resolved).suffix.lower()
        if suffix not in self.allowed_extensions:
            extensions_str = ", ".join(sorted(self.allowed_extensions))
            raise FilePathError(
                f"Only files with extensions ({extensions_str}) are supported. "
                f"Got: {suffix}"
            )

        return resolved

    def read_file(self, file_path: str) -> str:
        """Read YAML configuration file contents.

        Args:
            file_path: Relative path to YAML file.

        Returns:
            Raw file contents as UTF-8 string.

        Raises:
            FilePathError: If path is invalid.
            FileNotFoundError: If file doesn't exist.
            YAMLConfigError: On read errors (permissions, encoding, etc).

        Example:
            >>> manager = YAMLConfigManager(Path("/home/user/configs"))
            >>> content = manager.read_file("settings.yaml")
            >>> print(content[:20])
            database:
              host:...
        """
        resolved_path = self.validate_path(file_path)

        if not self._filesystem.exists(resolved_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        try:
            content = self._filesystem.read_text(resolved_path)
            logger.debug(f"Read {len(content)} bytes from {file_path}")
            return content
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {file_path}")
        except Exception as e:
            raise YAMLConfigError(f"Error reading file {file_path}: {e}")

    def validate_yaml(self, content: str) -> bool:
        """Validate YAML syntax using safe parsing.

        Uses safe_load_yaml to ensure content is valid YAML. Supports
        custom tags like !include, !secret that are common in Home Assistant
        and similar applications.

        Args:
            content: YAML content to validate.

        Returns:
            True if valid YAML.

        Raises:
            YAMLSyntaxError: If YAML syntax is invalid.

        Example:
            >>> manager = YAMLConfigManager(Path("/home/user/configs"))
            >>> manager.validate_yaml("key: value\\n")
            True

            >>> manager.validate_yaml("key: [unclosed")
            Traceback (most recent call last):
            ...
            YAMLSyntaxError: Invalid YAML syntax: ...
        """
        try:
            safe_load_yaml(content)
            return True
        except yaml.YAMLError as e:
            raise YAMLSyntaxError(f"Invalid YAML syntax: {e}")

    def write_file(self, file_path: str, content: str) -> None:
        """Write content to YAML file with validation.

        Validates YAML syntax before writing to prevent invalid files.
        Creates parent directories if they don't exist.

        Args:
            file_path: Relative path to YAML file.
            content: YAML content to write (must be valid YAML).

        Raises:
            FilePathError: If path is invalid.
            YAMLSyntaxError: If content is not valid YAML.
            YAMLConfigError: On write errors (permissions, disk full, etc).

        Example:
            >>> manager = YAMLConfigManager(Path("/home/user/configs"))
            >>> manager.write_file("app/settings.yaml", "key: value\\n")

            >>> manager.write_file("bad.yaml", "key: [unclosed")
            Traceback (most recent call last):
            ...
            YAMLSyntaxError: Invalid YAML syntax: ...
        """
        self.validate_yaml(content)

        resolved_path = self.validate_path(file_path)

        try:
            self._filesystem.write_text(resolved_path, content)
            logger.info(f"Wrote {len(content)} bytes to {file_path}")
        except Exception as e:
            raise YAMLConfigError(f"Error writing file {file_path}: {e}")

    def create_file(self, file_path: str, content: str) -> None:
        """Create new YAML file.

        Args:
            file_path: Relative path for new file.
            content: YAML content for new file.

        Raises:
            FilePathError: If path is invalid.
            FileExistsError: If file already exists.
            YAMLSyntaxError: If content is not valid YAML.
            YAMLConfigError: On creation errors.

        Example:
            >>> manager = YAMLConfigManager(Path("/home/user/configs"))
            >>> manager.create_file("new.yaml", "key: value\\n")

            >>> manager.create_file("new.yaml", "more: data\\n")
            Traceback (most recent call last):
            ...
            FileExistsError: File already exists: new.yaml
        """
        resolved_path = self.validate_path(file_path)

        if self._filesystem.exists(resolved_path):
            raise FileExistsError(f"File already exists: {file_path}")

        self.write_file(file_path, content)
        logger.info(f"Created new file: {file_path}")

    def list_yaml_files(self, pattern: str = "**/*.yaml") -> List[str]:
        """List files matching glob pattern for all allowed extensions.

        Searches using all configured allowed extensions by replacing the
        .yaml extension in the pattern with each allowed extension.

        Args:
            pattern: Glob pattern for matching files (default: "**/*.yaml").
                     The .yaml suffix is substituted for each allowed extension.

        Returns:
            List of relative file paths (sorted, deduplicated).

        Example:
            >>> manager = YAMLConfigManager(Path("/home/user/configs"))
            >>> files = manager.list_yaml_files("app/**/*.yaml")
            >>> print(files)
            ['app/database.yaml', 'app/settings.yaml']

            >>> all_files = manager.list_yaml_files()
            >>> len(all_files)
            42
        """
        files = []

        for ext in self.allowed_extensions:
            glob_pattern = pattern.replace(".yaml", ext)
            matching = self._filesystem.glob(glob_pattern)
            files.extend(matching)

        return sorted(set(files))

    def grep_files(
        self, search_pattern: str, file_pattern: str = "**/*.yaml"
    ) -> List[Dict[str, Any]]:
        """Search for text patterns across YAML files.

        Performs case-insensitive regex search across files. Limits results
        to 500 matches to prevent excessive memory usage.

        Args:
            search_pattern: Text or regex pattern to search for.
            file_pattern: Glob pattern to filter files (default: "**/*.yaml").

        Returns:
            List of dicts with keys: file (str), line (int), content (str).
            If any files could not be read, a warning entry is appended with
            file="_warning", line=0, and a description of skipped files.

        Raises:
            YAMLConfigError: If search pattern is invalid regex or exceeds
                the maximum length (1000 characters).

        Example:
            >>> manager = YAMLConfigManager(Path("/home/user/configs"))
            >>> results = manager.grep_files("database")
            >>> for r in results:
            ...     print(f"{r['file']}:{r['line']}: {r['content']}")
            app/settings.yaml:5:   database: postgres
            db/config.yaml:1: database:

            >>> results = manager.grep_files("timeout.*[0-9]+", "**/*.yaml")
            >>> len(results)
            3
        """
        results = []
        skipped_files = []
        files = self.list_yaml_files(file_pattern)

        max_pattern_length = 1000
        if len(search_pattern) > max_pattern_length:
            raise YAMLConfigError(
                f"Search pattern too long ({len(search_pattern)} chars, max {max_pattern_length})"
            )

        try:
            regex = re.compile(search_pattern, re.IGNORECASE)
        except re.error as e:
            raise YAMLConfigError(f"Invalid search pattern: {e}")

        match_count = 0
        max_matches = 500

        for file_path in files:
            if match_count >= max_matches:
                logger.warning(f"Hit max match limit ({max_matches}), stopping search")
                break

            try:
                content = self.read_file(file_path)
                lines = content.split("\n")

                for line_num, line in enumerate(lines, 1):
                    if match_count >= max_matches:
                        break

                    if regex.search(line):
                        results.append(
                            {
                                "file": file_path,
                                "line": line_num,
                                "content": line.strip(),
                            }
                        )
                        match_count += 1
            except Exception as e:
                from .exceptions import SMBConnectionError

                if isinstance(e, SMBConnectionError):
                    raise
                logger.warning(f"Error searching file {file_path}: {e}")
                skipped_files.append(file_path)
                continue

        if skipped_files:
            results.append(
                {
                    "file": "_warning",
                    "line": 0,
                    "content": f"Search incomplete: {len(skipped_files)} file(s) could not be read",
                }
            )

        return results
