"""
Module: mcp_yamlfilesystem

Purpose:
    MCP YAML Filesystem Manager - A security-focused Model Context Protocol (MCP)
    server for safe YAML file management. Provides AI agents with controlled access
    to YAML configuration files while enforcing strict security boundaries.

    Supports two modes:
    1. Local mode: Work with local directories (git version control recommended)
    2. SMB mode: Direct access to SMB/CIFS shares (no root, private to process)

Classes:
    - YAMLConfigManager: Core manager for YAML file operations with path security
    - YAMLDiffEngine: Diff-based update engine for precise YAML modifications
    - LocalFileSystem: Filesystem backend for local directory operations
    - SMBFileSystem: Filesystem backend for SMB share operations (no root required)

Exceptions:
    - YAMLConfigError: Base exception for configuration errors
    - YAMLSyntaxError: Raised when YAML syntax validation fails
    - FilePathError: Raised for invalid or unauthorized file paths
    - SMBConnectionError: Raised when SMB connection fails or becomes unavailable

Usage Example:
    from mcp_yamlfilesystem import YAMLConfigManager, YAMLDiffEngine
    from pathlib import Path

    # Local mode: Initialize manager with root directory
    manager = YAMLConfigManager(Path("/path/to/yaml/root"))

    # SMB mode: Initialize with SMB backend (no root required)
    from mcp_yamlfilesystem import SMBFileSystem
    smb_fs = SMBFileSystem(
        server="fileserver",
        share="configs",
        username="user",
        password="pass"
    )
    manager = YAMLConfigManager(filesystem=smb_fs)

    # Read YAML file
    content = manager.read_file("config/settings.yaml")

    # Update using diff engine
    engine = YAMLDiffEngine()
    updated = engine.apply_diff(content, diff_content)
    manager.write_file("config/settings.yaml", updated)

Security Model:
    - All file paths must be relative (no absolute paths)
    - All operations contained within root directory
    - Only .yaml and .yml files allowed
    - YAML validation before writes
    - Git version control recommended for traceability
    - Path traversal protection via symlink resolution

Happy Path Flow:

```mermaid
sequenceDiagram
    participant Agent
    participant YAMLConfigManager
    participant FileSystem
    participant YAMLDiffEngine

    Agent->>YAMLConfigManager: read_file("config.yaml")
    YAMLConfigManager->>YAMLConfigManager: validate_path()
    YAMLConfigManager->>FileSystem: read_text()
    FileSystem-->>YAMLConfigManager: content
    YAMLConfigManager-->>Agent: YAML content

    Agent->>YAMLDiffEngine: apply_diff(content, diff)
    YAMLDiffEngine->>YAMLDiffEngine: parse_diff()
    YAMLDiffEngine->>YAMLDiffEngine: apply replacements
    YAMLDiffEngine->>YAMLDiffEngine: validate_yaml()
    YAMLDiffEngine-->>Agent: updated content

    Agent->>YAMLConfigManager: write_file("config.yaml", updated)
    YAMLConfigManager->>YAMLConfigManager: validate_yaml()
    YAMLConfigManager->>YAMLConfigManager: validate_path()
    YAMLConfigManager->>FileSystem: write_text()
    FileSystem-->>YAMLConfigManager: success
    YAMLConfigManager-->>Agent: success
```
"""

__version__ = "1.0.0"

from .exceptions import (
    YAMLConfigError,
    YAMLSyntaxError,
    FilePathError,
    SMBConnectionError,
)
from .yaml_manager import YAMLConfigManager
from .diff_engine import YAMLDiffEngine
from .filesystem import FileSystemBackend, LocalFileSystem, SMBFileSystem
from .config import Config, SMBConfig

__all__ = [
    "YAMLConfigError",
    "YAMLSyntaxError",
    "FilePathError",
    "SMBConnectionError",
    "YAMLConfigManager",
    "YAMLDiffEngine",
    "FileSystemBackend",
    "LocalFileSystem",
    "SMBFileSystem",
    "Config",
    "SMBConfig",
]
