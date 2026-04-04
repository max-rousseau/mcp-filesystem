"""
Module: server

Purpose:
    MCP server implementation for YAML filesystem management using the official
    MCP SDK. Provides AI agents with secure, controlled access to YAML
    configuration files through Model Context Protocol (MCP) tools. Exposes
    five core operations for reading, writing, searching, and validating YAML files.

Classes:
    - MCPServer: Singleton dataclass managing server state (yaml_manager, diff_engine)

Functions:
    - read_file: MCP tool for reading YAML files
    - update_file: MCP tool for diff-based updates
    - create_file: MCP tool for creating new YAML files
    - grep_files: MCP tool for searching across files
    - list_directory_structure: MCP tool for directory tree view

MCP Tools Exposed:
    1. read_file(file_path) - Read YAML file contents
    2. update_file(file_path, diff_content) - Update using diff
    3. create_file(file_path, content) - Create new YAML file
    4. grep_files(search_pattern, file_pattern) - Search files
    5. list_directory_structure() - Show directory tree

Usage Example:
    # Run server directly
    python -m mcp_yamlfilesystem.server

    # Or use the console script entry point
    mcp-yamlfilesystem --local-path /path/to/yaml/files

Configuration:
    Supports two modes:

    1. Local mode (in priority order):
       - --local-path command line argument
       - MCP_FILESYSTEM_LOCAL_PATH environment variable
       - local_path in ~/.config/mcp-yamlfilesystem/config

    2. SMB mode:
       - MCP_FILESYSTEM_SMB_PATH, MCP_FILESYSTEM_SMB_USER, MCP_FILESYSTEM_SMB_PASSWORD

    Copy config.example to ~/.config/mcp-yamlfilesystem/config to get started.

Happy Path Flow:

```mermaid
sequenceDiagram
    participant Agent
    participant MCPServer
    participant YAMLConfigManager
    participant YAMLDiffEngine
    participant FileSystem

    Agent->>MCPServer: read_file("config.yaml")
    MCPServer->>MCPServer: MCPServer.get()
    MCPServer->>YAMLConfigManager: read_file("config.yaml")
    YAMLConfigManager->>FileSystem: read_text()
    FileSystem-->>YAMLConfigManager: content
    YAMLConfigManager-->>MCPServer: content
    MCPServer-->>Agent: YAML content

    Agent->>MCPServer: update_file("config.yaml", diff)
    MCPServer->>MCPServer: MCPServer.get()
    MCPServer->>YAMLConfigManager: read_file("config.yaml")
    YAMLConfigManager-->>MCPServer: current content
    MCPServer->>YAMLDiffEngine: apply_diff(content, diff)
    YAMLDiffEngine-->>MCPServer: updated content
    MCPServer->>YAMLConfigManager: write_file("config.yaml", updated)
    YAMLConfigManager->>FileSystem: write_text()
    FileSystem-->>YAMLConfigManager: success
    YAMLConfigManager-->>MCPServer: success
    MCPServer-->>Agent: success message
```
"""

import asyncio
import logging
import sys
from dataclasses import dataclass
from typing import Any, Callable, ClassVar, Optional

from mcp.server.fastmcp import FastMCP

from .config import Config, LogConfig
from .diff_engine import YAMLDiffEngine
from .exceptions import FilePathError, YAMLConfigError, YAMLSyntaxError
from .filesystem import SMBFileSystem
from .yaml_manager import YAMLConfigManager

# Exception types safe to surface to MCP callers (no internal details)
_SAFE_EXCEPTIONS = (
    FilePathError,
    YAMLConfigError,
    YAMLSyntaxError,
    FileNotFoundError,
    FileExistsError,
    ValueError,
)

# Default logging config - WARNING level to prevent stdio pollution
# Will be reconfigured on initialize_server if debug mode is enabled
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# Silence noisy third-party loggers early to prevent stdio pollution
logging.getLogger("smbprotocol").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)

# Track if logging has been configured
_logging_configured = False


def configure_logging(log_config: LogConfig) -> None:
    """Configure logging based on LogConfig settings.

    When a log file is specified, logs go to the file only to avoid polluting
    MCP protocol communication. Without a log file, logs go to stderr.

    Args:
        log_config: Logging configuration with debug flag and optional log file path.

    Example:
        >>> from mcp_yamlfilesystem.config import LogConfig
        >>> config = LogConfig(debug=True, log_file=Path("./tmp/mcp.log"))
        >>> configure_logging(config)
    """
    global _logging_configured

    level = logging.DEBUG if log_config.debug else logging.INFO
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Get the root logger for the package
    root_logger = logging.getLogger("mcp_yamlfilesystem")

    # Clear existing handlers
    root_logger.handlers.clear()

    # Prevent propagation to root logger (stops FastMCP from capturing logs)
    root_logger.propagate = False

    if log_config.log_file:
        # Log file specified: send logs to file only
        file_handler = logging.FileHandler(
            log_config.log_file, mode="a", encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter(log_format))
        root_logger.addHandler(file_handler)
    else:
        # No log file: send to stderr
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(level)
        stderr_handler.setFormatter(logging.Formatter(log_format))
        root_logger.addHandler(stderr_handler)

    root_logger.setLevel(level)

    # Silence noisy third-party loggers
    logging.getLogger("smbprotocol").setLevel(logging.WARNING)
    logging.getLogger("mcp").setLevel(logging.WARNING)

    _logging_configured = True

    if log_config.debug:
        logger.debug("Debug logging enabled")


# Deferred FastMCP instantiation for OAuth support
# The FastMCP instance is created at runtime in _create_mcp_server() so we can
# pass the auth provider based on configuration.
mcp: FastMCP | None = None
_tool_registry: dict[str, tuple[Callable, dict[str, Any]]] = {}


def _register_tool(func: Callable | None = None, **kwargs: Any) -> Callable:
    """Register a tool function for later registration with FastMCP.

    This decorator stores tool functions and their kwargs in _tool_registry.
    When _create_mcp_server() is called, it creates the FastMCP instance
    (with optional auth) and registers all stored tools.

    Args:
        func: The tool function to register.
        **kwargs: Additional keyword arguments to pass to mcp.tool().

    Returns:
        The original function (unmodified).

    Example:
        >>> @_register_tool
        ... async def my_tool(arg: str) -> str:
        ...     return arg
        >>> "my_tool" in _tool_registry
        True
    """

    def decorator(f: Callable) -> Callable:
        _tool_registry[f.__name__] = (f, kwargs)
        return f

    if func is not None:
        return decorator(func)
    return decorator


def _create_mcp_server(
    token_verifier: Any = None,
    auth_settings: Any = None,
) -> FastMCP:
    """Create FastMCP server instance with optional OAuth authentication.

    Creates the FastMCP server and registers all tools from the registry.
    This deferred instantiation allows passing auth components at runtime.

    Args:
        token_verifier: Optional TokenVerifier for OAuth token validation.
        auth_settings: Optional AuthSettings for OAuth configuration.

    Returns:
        Configured FastMCP instance with all tools registered.

    Example:
        >>> server = _create_mcp_server()  # No auth
        >>> server.name
        'YAML Filesystem Manager'

        >>> from .auth import create_google_auth
        >>> verifier, settings = create_google_auth(...)
        >>> server = _create_mcp_server(token_verifier=verifier, auth_settings=settings)
    """
    global mcp

    if token_verifier and auth_settings:
        server = FastMCP(
            "YAML Filesystem Manager",
            token_verifier=token_verifier,
            auth=auth_settings,
        )
        logger.info("Created FastMCP server with OAuth authentication")
    else:
        server = FastMCP("YAML Filesystem Manager")
        logger.debug("Created FastMCP server without authentication")

    # Register all tools from the registry
    for name, (func, kwargs) in _tool_registry.items():
        server.tool(**kwargs)(func)
        logger.debug(f"Registered tool: {name}")

    mcp = server
    return server


@dataclass
class MCPServer:
    """MCP server instance with encapsulated state.

    Manages YAMLConfigManager, YAMLDiffEngine, and Config instances.
    Provides clean initialization and cleanup lifecycle.
    Replaces module-level global variables with proper singleton pattern.

    Attributes:
        config: Server configuration instance.
        yaml_manager: YAML file manager instance.
        diff_engine: Diff application engine instance.

    Example:
        >>> server = MCPServer.get()  # Get singleton instance
        >>> content = server.yaml_manager.read_file("config.yaml")

        >>> MCPServer.reset()  # For testing - reset singleton
    """

    config: Config
    yaml_manager: YAMLConfigManager
    diff_engine: YAMLDiffEngine

    _instance: ClassVar[Optional["MCPServer"]] = None

    @classmethod
    def get(cls) -> "MCPServer":
        """Get or create the singleton server instance.

        Lazy initialization - creates instance on first access.
        Subsequent calls return the same instance.

        Returns:
            The singleton MCPServer instance.
        """
        if cls._instance is None:
            cls._instance = cls._create()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton instance (for testing).

        Clears the cached instance so next get() creates fresh instance.
        Also resets Config singleton.
        """
        cls._instance = None
        Config.reset()

    @classmethod
    def _create(cls) -> "MCPServer":
        """Create a new server instance (internal).

        Loads configuration and creates all manager instances.

        Returns:
            New MCPServer instance.

        Raises:
            YAMLConfigError: If configuration is invalid.
        """
        config = Config.get()

        # Configure logging from config (only once)
        if not _logging_configured:
            configure_logging(config.log_config)

        extensions_str = ", ".join(sorted(config.allowed_extensions))

        if config.is_smb_mode:
            # SMB mode - create SMBFileSystem backend
            smb = config.smb_config
            filesystem = SMBFileSystem(
                server=smb.server,
                share=smb.share,
                username=smb.username,
                password=smb.password,
                base_path=smb.base_path,
                ignore_dirs=smb.ignore_dirs,
            )
            yaml_manager = YAMLConfigManager(
                filesystem=filesystem, allowed_extensions=config.allowed_extensions
            )
            root_display = f"//{smb.server}/{smb.share}"
            if smb.base_path:
                root_display += f"/{smb.base_path}"
            logger.info(
                f"YAML Filesystem Manager initialized with SMB share: {root_display} "
                f"(allowed extensions: {extensions_str})"
            )
        else:
            # Local mode - use Path directly
            yaml_manager = YAMLConfigManager(
                config.yaml_root_path, allowed_extensions=config.allowed_extensions
            )
            logger.info(
                f"YAML Filesystem Manager initialized with root: "
                f"{config.yaml_root_path} (allowed extensions: {extensions_str})"
            )

        diff_engine = YAMLDiffEngine()

        return cls(config=config, yaml_manager=yaml_manager, diff_engine=diff_engine)


@_register_tool
async def read_file(file_path: str) -> str:
    """Read a YAML configuration file.

    MCP tool for reading YAML file contents. Returns raw file content
    as string. All paths must be relative to the configured root path.

    Args:
        file_path: Relative path to YAML file (e.g., "config/settings.yaml").

    Returns:
        Raw YAML file contents as string.

    Raises:
        ValueError: If file cannot be read (wraps underlying exceptions).

    Example:
        >>> content = await read_file("configuration.yaml")
        >>> print(content[:20])
        database:
          host:...

        >>> content = await read_file("configs/automation/office.yaml")
    """
    logger.debug(f"Tool call: read_file(file_path={file_path!r})")
    try:
        server = MCPServer.get()
        content = server.yaml_manager.read_file(file_path)
        logger.debug(f"Tool response: read_file returned {len(content)} bytes")
        return content
    except Exception as e:
        logger.error(f"Tool error: read_file failed - {e}", exc_info=True)
        detail = str(e) if isinstance(e, _SAFE_EXCEPTIONS) else "internal error"
        raise ValueError(f"Failed to read file: {detail}")


@_register_tool
async def update_file(file_path: str, diff_content: str) -> str:
    """Update a YAML file using diff-based search/replace.

    MCP tool for precise file updates using exact search/replace blocks.
    The diff format requires exact content matching (whitespace-sensitive).

    The diff uses exact search/replace blocks with this format:

    <<<<<<< SEARCH
    exact content to find (whitespace-sensitive)
    =======
    replacement content
    >>>>>>> REPLACE

    Multiple diff blocks can be included in a single update.

    Args:
        file_path: Relative path to YAML file.
        diff_content: Diff in SEARCH/REPLACE format.

    Returns:
        Success message with file path.

    Raises:
        ValueError: If update fails (wraps underlying exceptions).

    Example:
        >>> diff = '''<<<<<<< SEARCH
        ... timeout: 30
        ... =======
        ... timeout: 60
        ... >>>>>>> REPLACE'''
        >>> result = await update_file("config.yaml", diff)
        >>> print(result)
        Successfully updated config.yaml

        >>> multi_diff = '''<<<<<<< SEARCH
        ... host: localhost
        ... =======
        ... host: prod-server
        ... >>>>>>> REPLACE
        ...
        ... <<<<<<< SEARCH
        ... port: 8080
        ... =======
        ... port: 9000
        ... >>>>>>> REPLACE'''
        >>> await update_file("app.yaml", multi_diff)
    """
    logger.debug(f"Tool call: update_file(file_path={file_path!r})")
    try:
        server = MCPServer.get()
        current_content = server.yaml_manager.read_file(file_path)
        updated_content = server.diff_engine.apply_diff(current_content, diff_content)
        server.yaml_manager.write_file(file_path, updated_content)
        logger.info(f"Successfully updated {file_path}")
        return f"Successfully updated {file_path}"
    except Exception as e:
        logger.error(f"Tool error: update_file failed - {e}", exc_info=True)
        detail = str(e) if isinstance(e, _SAFE_EXCEPTIONS) else "internal error"
        raise ValueError(f"Failed to update file: {detail}")


@_register_tool
async def create_file(file_path: str, content: str) -> str:
    """Create a new YAML configuration file.

    MCP tool for creating new YAML files. Validates YAML syntax before
    creation. Fails if file already exists.

    Args:
        file_path: Relative path for new file.
        content: Valid YAML content for the new file.

    Returns:
        Success message with file path.

    Raises:
        ValueError: If file already exists or content is invalid YAML.

    Example:
        >>> yaml_content = "key: value\\nlist:\\n  - item1\\n  - item2"
        >>> result = await create_file("configs/new_config.yaml", yaml_content)
        >>> print(result)
        Successfully created configs/new_config.yaml

        >>> await create_file("configs/new_config.yaml", "more: data")
        Traceback (most recent call last):
        ...
        ValueError: Failed to create file: File already exists...
    """
    logger.debug(f"Tool call: create_file(file_path={file_path!r})")
    try:
        server = MCPServer.get()
        server.yaml_manager.create_file(file_path, content)
        logger.info(f"Successfully created {file_path}")
        return f"Successfully created {file_path}"
    except Exception as e:
        logger.error(f"Tool error: create_file failed - {e}", exc_info=True)
        detail = str(e) if isinstance(e, _SAFE_EXCEPTIONS) else "internal error"
        raise ValueError(f"Failed to create file: {detail}")


@_register_tool
async def grep_files(search_pattern: str, file_pattern: str = "**/*.yaml") -> str:
    """Search for text patterns across YAML files.

    MCP tool for case-insensitive regex search across YAML files. Returns
    results in grep-like format: file:line: content. Limits to 500 matches
    to prevent excessive memory usage.

    Args:
        search_pattern: Text or regex pattern to search for (case-insensitive).
        file_pattern: Glob pattern to filter files (default: "**/*.yaml").

    Returns:
        Search results showing file:line: content format, or "No matches found".

    Raises:
        ValueError: If search fails (wraps underlying exceptions).

    Example:
        >>> results = await grep_files("api_key")
        >>> print(results)
        config/app.yaml:15: api_key: xxx
        config/db.yaml:3:   api_key: yyy

        >>> results = await grep_files("timeout.*[0-9]+", "configs/automation/*.yaml")
        >>> print(results)
        configs/automation/sensor.yaml:23: timeout: 30
        configs/automation/light.yaml:45: timeout: 60

        >>> results = await grep_files("nonexistent")
        >>> print(results)
        No matches found
    """
    logger.debug(
        f"Tool call: grep_files(search_pattern={search_pattern!r}, file_pattern={file_pattern!r})"
    )
    try:
        server = MCPServer.get()
        # Use asyncio.to_thread for SMB to avoid blocking the event loop
        results = await asyncio.to_thread(
            server.yaml_manager.grep_files, search_pattern, file_pattern
        )

        if not results:
            return "No matches found"

        output = []
        for result in results:
            output.append(f"{result['file']}:{result['line']}: {result['content']}")

        result_text = "\n".join(output)
        logger.debug(f"Tool response: grep_files returned {len(results)} matches")
        return result_text
    except Exception as e:
        logger.error(f"Tool error: grep_files failed - {e}", exc_info=True)
        detail = str(e) if isinstance(e, _SAFE_EXCEPTIONS) else "internal error"
        raise ValueError(f"Failed to search files: {detail}")


@_register_tool
async def list_directory_structure() -> str:
    """List the YAML file directory structure.

    MCP tool for displaying directory tree showing YAML files and directories.
    Uses tree-like ASCII art format. Prunes directories that contain no YAML
    files to optimize token usage. Works with both local and SMB backends.

    Returns:
        Tree view of config directory structure showing only YAML files
        and directories containing YAML files.

    Raises:
        ValueError: If listing fails (wraps underlying exceptions).

    Example:
        >>> tree = await list_directory_structure()
        >>> print(tree)
        configs/
        ├── app/
        │   ├── database.yaml
        │   └── settings.yaml
        ├── automation/
        │   ├── lights.yaml
        │   └── sensors.yaml
        └── configuration.yaml
    """
    logger.debug("Tool call: list_directory_structure()")
    try:
        server = MCPServer.get()

        # Get all YAML files from the filesystem backend
        # Use asyncio.to_thread for SMB to avoid blocking the event loop
        all_files = await asyncio.to_thread(
            server.yaml_manager.list_yaml_files, "**/*.yaml"
        )

        root_path = server.yaml_manager._filesystem.root_path
        result_text = _build_file_tree(all_files, root_path)
        logger.debug("Tool response: list_directory_structure succeeded")
        return result_text
    except Exception as e:
        logger.error(
            f"Tool error: list_directory_structure failed - {e}", exc_info=True
        )
        detail = str(e) if isinstance(e, _SAFE_EXCEPTIONS) else "internal error"
        raise ValueError(f"Failed to list structure: {detail}")


def _build_file_tree(all_files: list[str], root_path: str) -> str:
    """Build tree-view string from a list of file paths.

    Args:
        all_files: List of relative file paths.
        root_path: Root path for display name extraction.

    Returns:
        Tree-formatted string showing directory structure.
    """
    if not all_files:
        if "/" in root_path:
            root_name = root_path.rstrip("/").split("/")[-1] or "root"
        elif "\\" in root_path:
            root_name = root_path.rstrip("\\").split("\\")[-1] or "root"
        else:
            root_name = root_path or "root"
        return f"{root_name}/\n  (no YAML files found)"

    tree_data: dict = {}
    for file_path in all_files:
        parts = file_path.replace("\\", "/").split("/")
        current = tree_data
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = None

    def _render_tree(node: dict, prefix: str = "", is_root: bool = False) -> list:
        lines = []
        items = sorted(node.keys(), key=lambda x: (node[x] is None, x))
        for i, name in enumerate(items):
            is_last = i == len(items) - 1
            connector = "" if is_root else ("└── " if is_last else "├── ")
            if node[name] is None:
                lines.append(f"{prefix}{connector}{name}")
            else:
                lines.append(f"{prefix}{connector}{name}/")
                child_prefix = prefix + (
                    "" if is_root else ("    " if is_last else "│   ")
                )
                lines.extend(_render_tree(node[name], child_prefix))
        return lines

    if "/" in root_path:
        root_name = root_path.rstrip("/").split("/")[-1] or "root"
    elif "\\" in root_path:
        root_name = root_path.rstrip("\\").split("\\")[-1] or "root"
    else:
        root_name = root_path or "root"

    structure = [f"{root_name}/"]
    structure.extend(_render_tree(tree_data, ""))
    return "\n".join(structure)


def _run_test() -> None:
    """Test connection and list_directory_structure performance.

    Runs the list_directory_structure tool using the real config file
    and displays timing information. Useful for testing SMB ignore_dirs
    configuration.

    Prints directory tree and elapsed time on success, or error on failure.
    """
    import sys
    import time

    try:
        # Initialize MCPServer singleton
        mcp_server = MCPServer.get()

        # Show debug status so user knows logging is configured
        if mcp_server.config.log_config.debug:
            print("DEBUG mode: enabled (logs go to stderr)")
            logger.debug(
                "Debug logging verification - if you see this, DEBUG is working"
            )

        # Get display info from the initialized filesystem
        filesystem = mcp_server.yaml_manager._filesystem
        root_path = filesystem.root_path

        # Check if SMB mode by looking at filesystem type
        is_smb = hasattr(filesystem, "_ignore_dirs")
        if is_smb:
            print(f"Testing SMB connection to {root_path}...")
            ignore_dirs = filesystem._ignore_dirs
            if ignore_dirs:
                print(f"Ignoring directories: {', '.join(sorted(ignore_dirs))}")
            else:
                print("No ignore_dirs configured (consider adding for performance)")
        else:
            print(f"Testing local filesystem at {root_path}...")

        # Run the actual directory listing with timing
        print("\nRunning list_directory_structure...")
        start_time = time.perf_counter()

        all_files = mcp_server.yaml_manager.list_yaml_files("**/*.yaml")

        elapsed = time.perf_counter() - start_time

        print(f"\n{_build_file_tree(all_files, filesystem.root_path)}")

        print(f"\n--- Found {len(all_files)} YAML file(s) in {elapsed:.2f}s ---")

    except Exception as e:
        print(f"ERROR - Test failed: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    """Entry point for console script.

    Parses CLI arguments, sets corresponding environment variables, loads
    configuration via Config.get(), and starts the MCP server.

    Options:
    - --local-path: Path to directory containing YAML files
    - --test: Test connection to configured filesystem and exit
    - --http: Enable HTTP streaming transport
    - --host: Host address for HTTP transport
    - --port: Port for HTTP transport
    - --path: Endpoint path for HTTP transport
    - --oauth-enabled: Enable/disable OAuth for HTTP mode
    - --oauth-base-url: Public URL for OAuth callbacks
    """
    import argparse
    import os

    parser = argparse.ArgumentParser(
        description="MCP server for managing YAML configuration files"
    )

    parser.add_argument(
        "--local-path",
        type=str,
        help="Path to directory containing YAML files",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test connection to configured filesystem (SMB or local) and exit",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Enable HTTP streaming transport (default: stdio)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Host address for HTTP transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port for HTTP transport (default: 8000)",
    )
    parser.add_argument(
        "--path",
        type=str,
        default=None,
        help="Endpoint path for HTTP transport (default: /mcp)",
    )
    parser.add_argument(
        "--oauth-enabled",
        type=str,
        choices=["true", "false"],
        default=None,
        help="Enable/disable OAuth authentication for HTTP mode (default: true when HTTP enabled)",
    )
    parser.add_argument(
        "--oauth-base-url",
        type=str,
        default=None,
        help="Public URL for OAuth callbacks (required when OAuth enabled)",
    )

    args = parser.parse_args()

    # Set local path if provided (applies to both --test and server run)
    if args.local_path:
        os.environ["MCP_FILESYSTEM_LOCAL_PATH"] = args.local_path

    # Set HTTP config from CLI args (CLI takes precedence via env vars)
    if args.http:
        os.environ["MCP_HTTP_ENABLED"] = "true"
    if args.host:
        os.environ["MCP_HTTP_HOST"] = args.host
    if args.port:
        os.environ["MCP_HTTP_PORT"] = str(args.port)
    if args.path:
        os.environ["MCP_HTTP_PATH"] = args.path

    # Set OAuth config from CLI args
    if args.oauth_enabled:
        os.environ["MCP_OAUTH_ENABLED"] = args.oauth_enabled
    if args.oauth_base_url:
        os.environ["MCP_OAUTH_BASE_URL"] = args.oauth_base_url

    # Handle --test option
    if args.test:
        _run_test()
        return

    # Load config to determine transport mode (cached for later use)
    config = Config.get()

    # Configure logging (only once)
    if not _logging_configured:
        configure_logging(config.log_config)

    # Create OAuth components if HTTP + OAuth enabled
    token_verifier = None
    auth_settings = None
    if config.http_config.enabled and config.oauth_config.enabled:
        from .auth import create_google_auth

        token_verifier, auth_settings = create_google_auth(
            client_id=config.oauth_config.client_id,
            client_secret=config.oauth_config.client_secret,
            base_url=config.oauth_config.base_url,
            allowed_emails=config.oauth_config.allowed_emails or None,
        )
        logger.info(
            f"OAuth enabled with base URL: {config.oauth_config.base_url}"
            + (
                f" (allowlist: {len(config.oauth_config.allowed_emails)} emails)"
                if config.oauth_config.allowed_emails
                else " (all authenticated users allowed)"
            )
        )

    # Create FastMCP server with auth (deferred instantiation)
    server = _create_mcp_server(
        token_verifier=token_verifier, auth_settings=auth_settings
    )

    # Run server with appropriate transport
    if config.http_config.enabled:
        import uvicorn

        logger.info(
            f"Starting HTTP server on "
            f"{config.http_config.host}:{config.http_config.port}{config.http_config.path}"
        )
        app = server.streamable_http_app()
        uvicorn.run(
            app,
            host=config.http_config.host,
            port=config.http_config.port,
        )
    else:
        server.run()


if __name__ == "__main__":
    main()
