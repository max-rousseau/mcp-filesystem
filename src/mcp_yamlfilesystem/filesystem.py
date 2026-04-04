"""
Module: filesystem

Purpose:
    Filesystem abstraction layer providing unified interface for local and SMB
    file operations. Enables the YAML manager to work with files on local disk
    or remote SMB shares transparently.

Classes:
    - FileSystemBackend: Abstract base class defining filesystem interface
    - LocalFileSystem: Implementation for local filesystem operations
    - SMBFileSystem: Implementation for SMB/CIFS share operations

Usage Example:
    from pathlib import Path
    from mcp_yamlfilesystem.filesystem import LocalFileSystem, SMBFileSystem

    # Local filesystem
    local_fs = LocalFileSystem(Path("/home/user/configs"))
    content = local_fs.read_text("settings.yaml")

    # SMB filesystem (no root required, private to process)
    smb_fs = SMBFileSystem(
        server="fileserver",
        share="configs",
        username="user",
        password="pass"
    )
    content = smb_fs.read_text("settings.yaml")

Design Notes:
    - SMBFileSystem delegates all connection management to SMBConnection class
    - SMBConnection provides self-healing with automatic reconnection
    - No system mount required - works without root privileges
    - Connection is private to the process (not visible system-wide)
    - Lazy connection: SMB connects on first execute() call
    - Uses compound requests for 3x performance on directory scans
"""

import fnmatch
import logging
import time as time_module
from abc import ABC, abstractmethod
from pathlib import Path, PurePosixPath
from typing import List

from mcp_yamlfilesystem.smb_connection import SMBConnection

logger = logging.getLogger(__name__)


class FileSystemBackend(ABC):
    """Abstract base class for filesystem operations.

    Provides a unified interface for file operations that can be implemented
    by different backends (local filesystem, SMB shares, etc.).

    All paths passed to methods should be relative paths within the
    configured root directory/share.
    """

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check if a file or directory exists.

        Args:
            path: Relative path to check.

        Returns:
            True if path exists, False otherwise.
        """
        pass

    @abstractmethod
    def is_file(self, path: str) -> bool:
        """Check if path is a file.

        Args:
            path: Relative path to check.

        Returns:
            True if path is a file, False otherwise.
        """
        pass

    @abstractmethod
    def is_dir(self, path: str) -> bool:
        """Check if path is a directory.

        Args:
            path: Relative path to check.

        Returns:
            True if path is a directory, False otherwise.
        """
        pass

    @abstractmethod
    def read_text(self, path: str) -> str:
        """Read file contents as text.

        Args:
            path: Relative path to file.

        Returns:
            File contents as UTF-8 string.

        Raises:
            FileNotFoundError: If file doesn't exist.
            IOError: On read errors.
        """
        pass

    @abstractmethod
    def write_text(self, path: str, content: str) -> None:
        """Write text content to file.

        Creates parent directories if they don't exist.

        Args:
            path: Relative path to file.
            content: Text content to write.

        Raises:
            IOError: On write errors.
        """
        pass

    @abstractmethod
    def mkdir(self, path: str, parents: bool = True) -> None:
        """Create directory.

        Args:
            path: Relative path for directory.
            parents: If True, create parent directories as needed.

        Raises:
            IOError: On creation errors.
        """
        pass

    @abstractmethod
    def glob(self, pattern: str) -> List[str]:
        """Find files matching glob pattern.

        Args:
            pattern: Glob pattern (e.g., "**/*.yaml").

        Returns:
            List of relative paths matching pattern.
        """
        pass

    @abstractmethod
    def resolve_path(self, path: str) -> str:
        """Resolve path to canonical form within root.

        Used for path validation to prevent directory traversal.

        Args:
            path: Relative path to resolve.

        Returns:
            Canonical path string.

        Raises:
            ValueError: If path escapes root directory.
        """
        pass

    @property
    @abstractmethod
    def root_path(self) -> str:
        """Get the root path/identifier for this filesystem."""
        pass


class LocalFileSystem(FileSystemBackend):
    """Local filesystem backend using pathlib.

    Provides file operations on the local filesystem with all paths
    relative to a configured root directory.

    Attributes:
        _root: Root directory Path object.
    """

    def __init__(self, root: Path) -> None:
        """Initialize local filesystem backend.

        Args:
            root: Root directory for all operations.

        Raises:
            ValueError: If root doesn't exist or isn't a directory.
        """
        self._root = root.resolve()
        if not self._root.exists():
            raise ValueError(f"Root directory does not exist: {self._root}")
        if not self._root.is_dir():
            raise ValueError(f"Root path is not a directory: {self._root}")
        logger.debug(f"LocalFileSystem initialized at {self._root}")

    @property
    def root_path(self) -> str:
        """Get the root directory path."""
        return str(self._root)

    def _full_path(self, path: str) -> Path:
        """Get full path from relative path."""
        return self._root / path

    def exists(self, path: str) -> bool:
        """Check if path exists."""
        return self._full_path(path).exists()

    def is_file(self, path: str) -> bool:
        """Check if path is a file."""
        return self._full_path(path).is_file()

    def is_dir(self, path: str) -> bool:
        """Check if path is a directory."""
        return self._full_path(path).is_dir()

    def read_text(self, path: str) -> str:
        """Read file contents as UTF-8 text."""
        full_path = self._full_path(path)
        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return full_path.read_text(encoding="utf-8")

    def write_text(self, path: str, content: str) -> None:
        """Write text content to file."""
        full_path = self._full_path(path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    def mkdir(self, path: str, parents: bool = True) -> None:
        """Create directory."""
        self._full_path(path).mkdir(parents=parents, exist_ok=True)

    def glob(self, pattern: str) -> List[str]:
        """Find files matching glob pattern."""
        results = []
        for match in self._root.glob(pattern):
            if match.is_file():
                results.append(str(match.relative_to(self._root)))
        return sorted(results)

    def resolve_path(self, path: str) -> str:
        """Resolve and validate path stays within root."""
        full_path = (self._root / path).resolve()
        try:
            full_path.relative_to(self._root)
        except ValueError:
            raise ValueError(f"Path escapes root directory: {path}")
        return str(full_path.relative_to(self._root))


class SMBFileSystem(FileSystemBackend):
    """SMB/CIFS filesystem backend using smbprotocol.

    Provides file operations on remote SMB shares without requiring
    system mount or root privileges. The connection is private to
    this process.

    Uses SMB compound requests for efficient directory scanning,
    reducing network roundtrips from 3 per directory to 1.

    Connection management is fully delegated to SMBConnection class.
    This class focuses purely on filesystem operations.

    Attributes:
        _conn: SMBConnection instance (owns connection lifecycle).
        _base_path: Optional subdirectory within share.
        _ignore_dirs: Directory names to skip during recursive glob.
    """

    def __init__(
        self,
        server: str,
        share: str,
        username: str,
        password: str,
        base_path: str = "",
        ignore_dirs: frozenset[str] | None = None,
    ) -> None:
        """Initialize SMB filesystem backend.

        Connection is established lazily on first operation and automatically
        reconnected if it becomes stale (e.g., after idle timeout).

        Args:
            server: SMB server hostname or IP address.
            share: Name of the share on the server.
            username: Username for SMB authentication.
            password: Password for SMB authentication.
            base_path: Optional subdirectory within share to use as root.
            ignore_dirs: Directory names to skip during recursive glob.
        """
        self._conn = SMBConnection(server, share, username, password)
        self._base_path = base_path.strip("/")
        self._ignore_dirs = ignore_dirs or frozenset()
        logger.debug(f"SMBFileSystem configured for //{server}/{share}")

    def _smb_path(self, path: str) -> str:
        """Build full SMB path from relative path."""
        server = self._conn.server
        share = self._conn.share
        if self._base_path:
            return f"\\\\{server}\\{share}\\{self._base_path}\\{path}".replace(
                "/", "\\"
            )
        return f"\\\\{server}\\{share}\\{path}".replace("/", "\\")

    @property
    def root_path(self) -> str:
        """Get the SMB share path identifier."""
        server = self._conn.server
        share = self._conn.share
        if self._base_path:
            return f"//{server}/{share}/{self._base_path}"
        return f"//{server}/{share}"

    def exists(self, path: str) -> bool:
        """Check if path exists on SMB share.

        Raises:
            SMBConnectionError: If unable to communicate with SMB server.
        """
        smb_path = self._smb_path(path)

        def operation():
            from smbclient import stat as smb_stat

            try:
                smb_stat(smb_path)
                return True
            except OSError as e:
                if e.errno == 2:
                    return False
                raise

        return self._conn.execute(operation, f"check existence of {path}")

    def is_file(self, path: str) -> bool:
        """Check if path is a file on SMB share.

        Raises:
            SMBConnectionError: If unable to communicate with SMB server.
        """
        smb_path = self._smb_path(path)

        def operation():
            import stat

            from smbclient import stat as smb_stat

            try:
                st = smb_stat(smb_path)
                return stat.S_ISREG(st.st_mode)
            except OSError as e:
                if e.errno == 2:
                    return False
                raise

        return self._conn.execute(operation, f"check if {path} is file")

    def is_dir(self, path: str) -> bool:
        """Check if path is a directory on SMB share.

        Raises:
            SMBConnectionError: If unable to communicate with SMB server.
        """
        smb_path = self._smb_path(path)

        def operation():
            import stat

            from smbclient import stat as smb_stat

            try:
                st = smb_stat(smb_path)
                return stat.S_ISDIR(st.st_mode)
            except OSError as e:
                if e.errno == 2:
                    return False
                raise

        return self._conn.execute(operation, f"check if {path} is directory")

    def read_text(self, path: str) -> str:
        """Read file contents from SMB share as UTF-8 text.

        Raises:
            FileNotFoundError: If file does not exist.
            SMBConnectionError: If unable to communicate with SMB server.
        """
        smb_path = self._smb_path(path)

        def operation():
            from smbclient import open_file

            with open_file(smb_path, mode="r", encoding="utf-8") as f:
                content = f.read()
            logger.debug(f"Read {len(content)} bytes from SMB: {path}")
            return content

        try:
            return self._conn.execute(operation, f"read file {path}")
        except OSError as e:
            if e.errno == 2:
                raise FileNotFoundError(f"File not found on SMB share: {path}")
            raise

    def write_text(self, path: str, content: str) -> None:
        """Write text content to file on SMB share.

        Raises:
            SMBConnectionError: If unable to communicate with SMB server.
        """
        # Ensure parent directory exists first
        parent = str(PurePosixPath(path).parent)
        if parent and parent != ".":
            self.mkdir(parent, parents=True)

        smb_path = self._smb_path(path)

        def operation():
            from smbclient import open_file

            with open_file(smb_path, mode="w", encoding="utf-8") as f:
                f.write(content)
            logger.debug(f"Wrote {len(content)} bytes to SMB: {path}")

        self._conn.execute(operation, f"write file {path}")

    def mkdir(self, path: str, parents: bool = True) -> None:
        """Create directory on SMB share.

        Raises:
            SMBConnectionError: If unable to communicate with SMB server.
        """
        smb_path = self._smb_path(path)

        def operation():
            from smbclient import makedirs

            makedirs(smb_path, exist_ok=True)

        self._conn.execute(operation, f"create directory {path}")

    def _compound_scandir(self, dir_path: str) -> List[tuple]:
        """Scan directory using compound request (Open+Query+Close in 1 roundtrip).

        Uses SMB compound requests with related=True to batch three operations
        into a single network roundtrip, providing 3x improvement over standard
        scandir which requires 3 separate roundtrips.

        Args:
            dir_path: Path to directory within share (use empty string for root).

        Returns:
            List of (name, is_directory) tuples for entries in directory.

        Raises:
            SMBConnectionError: If connection objects are invalid or operation fails.
        """
        # Build SMB path for directory
        if self._base_path:
            full_dir = (
                f"{self._base_path}\\{dir_path}".strip("\\")
                if dir_path
                else self._base_path
            )
        else:
            full_dir = dir_path.strip("\\") if dir_path else ""

        # Use empty string for root directory query in smbprotocol 1.15+
        query_path = full_dir

        def operation():
            from smbprotocol.open import (
                CreateDisposition,
                CreateOptions,
                DirectoryAccessMask,
                FileAttributes,
                FileInformationClass,
                ImpersonationLevel,
                Open,
                ShareAccess,
            )

            dir_open = Open(self._conn.tree, query_path)

            # Build compound message: create + query + close
            compound_messages = [
                dir_open.create(
                    ImpersonationLevel.Impersonation,
                    DirectoryAccessMask.FILE_LIST_DIRECTORY,
                    FileAttributes.FILE_ATTRIBUTE_DIRECTORY,
                    ShareAccess.FILE_SHARE_READ,
                    CreateDisposition.FILE_OPEN,
                    CreateOptions.FILE_DIRECTORY_FILE,
                    send=False,
                ),
                dir_open.query_directory(
                    "*",
                    FileInformationClass.FILE_ID_BOTH_DIRECTORY_INFORMATION,
                    send=False,
                ),
                dir_open.close(False, send=False),
            ]

            # Send all three operations in single compound request
            requests = self._conn.connection.send_compound(
                [msg[0] for msg in compound_messages],
                self._conn.session.session_id,
                self._conn.tree.tree_connect_id,
                related=True,
            )

            # Process responses
            results = []
            for i, request in enumerate(requests):
                response = compound_messages[i][1](request)
                if i == 1:  # Query directory response
                    for entry in response:
                        name = entry["file_name"].get_value().decode("utf-16-le")
                        if name in (".", ".."):
                            continue
                        is_dir = bool(
                            entry["file_attributes"].get_value()
                            & FileAttributes.FILE_ATTRIBUTE_DIRECTORY
                        )
                        results.append((name, is_dir))

            return results

        return self._conn.execute_compound(operation, f"scan directory {dir_path}")

    def glob(self, pattern: str) -> List[str]:
        """Find files matching glob pattern on SMB share.

        Uses compound requests to reduce network roundtrips from 3 per directory
        to 1 per directory (3x improvement for directory-heavy operations).
        Skips directories listed in ignore_dirs config to improve performance.

        Args:
            pattern: Glob pattern (e.g., "**/*.yaml").

        Returns:
            Sorted list of relative paths matching pattern.

        Raises:
            SMBConnectionError: If unable to communicate with SMB server.
        """
        results = []
        ignore_dirs = self._ignore_dirs

        def walk_smb(dir_path: str, rel_prefix: str = "") -> List[str]:
            """Recursively walk SMB directory using compound requests."""
            files = []
            display_path = rel_prefix or "(root)"
            logger.debug(f"Scanning directory: {display_path}")
            scan_start = time_module.perf_counter()

            # _compound_scandir handles all connection management via execute_compound
            entries = self._compound_scandir(dir_path)

            dir_count = 0
            file_count = 0
            skipped_count = 0

            for name, is_dir in entries:
                rel_path = f"{rel_prefix}/{name}".lstrip("/") if rel_prefix else name

                if is_dir:
                    dir_count += 1
                    # Skip ignored directories for performance
                    if name in ignore_dirs:
                        skipped_count += 1
                        logger.debug(f"  Skipping ignored dir: {name}")
                        continue
                    # Recurse if pattern indicates recursive search
                    if "**" in pattern:
                        subdir = f"{dir_path}/{name}" if dir_path else name
                        files.extend(walk_smb(subdir, rel_path))
                else:
                    file_count += 1
                    files.append(rel_path)

            scan_elapsed = time_module.perf_counter() - scan_start
            logger.debug(
                f"  Scanned {display_path}: {file_count} files, "
                f"{dir_count} dirs ({skipped_count} skipped) "
                f"in {scan_elapsed:.3f}s"
            )
            return files

        try:
            # Get all files
            all_files = walk_smb("")

            # Filter by pattern
            for file_path in all_files:
                if fnmatch.fnmatch(file_path, pattern):
                    results.append(file_path)
                elif "**" in pattern:
                    # Handle ** patterns specially
                    pattern_parts = pattern.replace("**", "*").split("/")
                    if fnmatch.fnmatch(file_path.split("/")[-1], pattern_parts[-1]):
                        results.append(file_path)

        except PermissionError as e:
            raise IOError(f"Permission denied accessing SMB share: {e}") from e
        except Exception as e:
            from mcp_yamlfilesystem.exceptions import SMBConnectionError

            if isinstance(e, SMBConnectionError):
                raise
            logger.error(f"Error globbing SMB share: {e}")
            raise IOError(f"Error searching SMB share: {e}") from e

        return sorted(results)

    def resolve_path(self, path: str) -> str:
        """Resolve and validate path stays within share root.

        Normalizes the path and checks for traversal attempts.

        Args:
            path: Relative path to resolve.

        Returns:
            Canonical path string.

        Raises:
            ValueError: If path escapes root directory.
        """
        # Normalize path
        normalized = PurePosixPath(path)

        # Check for path traversal
        try:
            # Resolve .. and . in path
            parts = []
            for part in normalized.parts:
                if part == "..":
                    if parts:
                        parts.pop()
                    else:
                        raise ValueError(f"Path escapes root directory: {path}")
                elif part != ".":
                    parts.append(part)

            resolved = "/".join(parts)
            return resolved
        except Exception as e:
            raise ValueError(f"Invalid path: {path} - {e}")
