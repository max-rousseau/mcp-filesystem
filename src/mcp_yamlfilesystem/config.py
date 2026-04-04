"""
Module: config

Purpose:
    Configuration management for MCP YAML Filesystem tool. Loads and validates
    configuration from multiple sources with strict security checks. Ensures all
    managed directories meet safety requirements before any operations begin.

    Supports two modes of operation:
    1. Local filesystem (default): Uses MCP_FILESYSTEM_LOCAL_PATH for local directory access
    2. SMB mode: Connects directly to SMB/CIFS shares without system mount

Classes:
    - Config: Configuration dataclass holding validated settings
    - SMBConfig: Configuration for SMB connection (optional)

Functions:
    - get_config_file_path: Get the path to the user configuration file

Usage Example:
    import os
    from mcp_yamlfilesystem.config import Config

    # Local mode
    os.environ["MCP_FILESYSTEM_LOCAL_PATH"] = "/path/to/yaml/files"
    config = Config.get()
    print(f"Root: {config.yaml_root_path}")

    # SMB mode (no root required, private to process)
    os.environ["MCP_FILESYSTEM_SMB_PATH"] = "//server/share/path"
    os.environ["MCP_FILESYSTEM_SMB_USER"] = "username"
    os.environ["MCP_FILESYSTEM_SMB_PASSWORD"] = "password"
    config = Config.get()
    print(f"SMB: {config.smb_config.server}/{config.smb_config.share}")

Configuration Requirements:
    Local mode (in priority order):
    - --local-path command line argument (sets MCP_FILESYSTEM_LOCAL_PATH env var)
    - MCP_FILESYSTEM_LOCAL_PATH environment variable
    - MCP_FILESYSTEM_LOCAL_PATH in ~/.config/mcp-yamlfilesystem/config

    Path must exist and be a directory. Git version control is recommended
    but not required. Path is resolved to absolute path with symlinks followed.

    SMB mode:
    - MCP_FILESYSTEM_SMB_PATH must be set (e.g., //server/share or //server/share/subdir)
    - MCP_FILESYSTEM_SMB_USER must be set
    - MCP_FILESYSTEM_SMB_PASSWORD must be set
    - Git requirement is skipped (SMB shares typically don't have .git)

Happy Path Flow:

```mermaid
sequenceDiagram
    participant Server
    participant Config
    participant ConfigFile
    participant Environment
    participant FileSystem

    Server->>Config: Config.get()
    Config->>ConfigFile: parse ~/.config/mcp-yamlfilesystem/config
    ConfigFile-->>Config: file_config dict
    Config->>Environment: check SMB config
    alt SMB Mode
        Environment-->>Config: SMB credentials
        Config-->>Server: Config with SMBConfig
    else Local Mode
        Config->>Environment: get MCP_FILESYSTEM_LOCAL_PATH
        alt MCP_FILESYSTEM_LOCAL_PATH not set
            Config->>ConfigFile: get local_path
        end
        Config->>FileSystem: check exists()
        FileSystem-->>Config: true
        Config->>FileSystem: check is_dir()
        FileSystem-->>Config: true
        Config->>FileSystem: check .git exists (warn if missing)
        FileSystem-->>Config: true/false
        Config-->>Server: Config object (with warning if no .git)
    end
```
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Set, Optional, ClassVar
import logging

from .exceptions import YAMLConfigError

logger = logging.getLogger(__name__)

# Required permission mode for config files (owner read/write only)
REQUIRED_PERMISSION_MODE = 0o600


def _require_config(key: str, file_config: dict[str, str]) -> str:
    """Get a required config value from env var or config file.

    Env var takes precedence. If neither source has the key, raises a fatal error.
    Empty string is a valid value (key present but no value).

    Args:
        key: Configuration key name (same for env var and config file).
        file_config: Parsed config file dictionary.

    Returns:
        The config value string.

    Raises:
        YAMLConfigError: If key is missing from both sources.
    """
    value = os.environ.get(key)
    if value is not None:
        return value
    value = file_config.get(key)
    if value is not None:
        return value
    raise YAMLConfigError(
        f"Missing required configuration: {key}. "
        "Copy config.example to ~/.config/mcp-yamlfilesystem/config "
        "and fill in required values."
    )


@dataclass
class SMBConfig:
    """Configuration for SMB/CIFS share connection.

    Holds credentials and connection details for accessing an SMB share
    directly without system mount (no root required, private to process).

    Attributes:
        server: SMB server hostname or IP address
        share: Name of the share on the server
        username: Username for authentication
        password: Password for authentication
        base_path: Optional subdirectory within share to use as root
        ignore_dirs: Set of directory names to skip during recursive glob

    Example:
        >>> smb = SMBConfig(
        ...     server="fileserver",
        ...     share="configs",
        ...     username="user",
        ...     password="secret",
        ...     base_path="homeassistant"
        ... )
        >>> print(f"//{smb.server}/{smb.share}/{smb.base_path}")
        //fileserver/configs/homeassistant
    """

    server: str
    share: str
    username: str
    password: str
    base_path: str = ""
    ignore_dirs: frozenset[str] = frozenset()


@dataclass
class LogConfig:
    """Configuration for debug logging.

    Attributes:
        debug: Whether debug logging is enabled. Required in config file.
        log_file: Path to log file. Empty = stderr only. Supports ~ expansion.

    Example:
        >>> log_config = LogConfig(debug=True, log_file=Path("/var/log/mcp.log"))
        >>> print(log_config.debug)
        True
    """

    debug: bool = False
    log_file: Optional[Path] = None


@dataclass
class HTTPConfig:
    """Configuration for HTTP streaming transport.

    Attributes:
        enabled: Whether HTTP transport is enabled. Required in config file.
        host: Host address to bind to. Required in config file.
        port: Port to bind to (1-65535). Required in config file.
        path: Endpoint path. Required in config file.

    Example:
        >>> http_config = HTTPConfig(enabled=True, host="0.0.0.0", port=9000)
        >>> print(http_config.port)
        9000
    """

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8000
    path: str = "/mcp"


@dataclass
class OAuthConfig:
    """Configuration for Google OAuth authentication.

    Only applicable when HTTP transport is enabled. OAuth provides
    authentication for the MCP server, restricting access to authorized
    Google accounts.

    Attributes:
        enabled: Whether OAuth is enabled. Required in config file.
        client_id: Google OAuth client ID from Google Cloud Console.
        client_secret: Google OAuth client secret.
        base_url: Public URL for OAuth callbacks (e.g., https://your-server.com).
        allowed_emails: Comma-separated email addresses allowed to access the server.
                       Empty means all authenticated users are allowed.

    Example:
        >>> oauth_config = OAuthConfig(
        ...     enabled=True,
        ...     client_id="123456789.apps.googleusercontent.com",
        ...     client_secret="GOCSPX-abc123",
        ...     base_url="https://my-server.com",
        ...     allowed_emails=["admin@example.com"]
        ... )
        >>> oauth_config.enabled
        True
    """

    enabled: bool = True
    client_id: str = ""
    client_secret: str = ""
    base_url: str = ""
    allowed_emails: list[str] | None = None


@dataclass
class Config:
    """Configuration for YAML filesystem manager (singleton).

    Holds validated configuration values for the MCP server. Supports two modes:
    1. Local mode: yaml_root_path points to local directory
    2. SMB mode: smb_config contains SMB connection details

    All local paths are resolved to absolute paths with symlinks followed.

    This is a singleton - use Config.get() to access the instance. The config
    is lazy-loaded on first access. Use Config.reset() in tests to clear state.

    Attributes:
        yaml_root_path: Absolute path to root directory for YAML files (local mode)
                       or None if using SMB mode
        allowed_extensions: Set of allowed file extensions (e.g., {'.yaml', '.yml'})
        smb_config: SMB connection configuration (SMB mode) or None for local mode
        log_config: Logging configuration (debug level, log file path)
        http_config: HTTP transport configuration (host, port, path, enabled)
        oauth_config: OAuth authentication configuration (Google OAuth, email allowlist)

    Example:
        >>> # Access config (lazy-loads on first call)
        >>> config = Config.get()
        >>> print(config.yaml_root_path)
        /home/user/configs

        >>> # Check mode
        >>> Config.get().is_smb_mode
        False
    """

    # Singleton instance
    _instance: ClassVar[Config | None] = None

    yaml_root_path: Optional[Path]
    allowed_extensions: Set[str]
    smb_config: Optional[SMBConfig] = None
    log_config: LogConfig = None
    http_config: HTTPConfig = None
    oauth_config: OAuthConfig = None

    def __post_init__(self):
        """Initialize default configs if not provided."""
        if self.log_config is None:
            self.log_config = LogConfig()
        if self.http_config is None:
            self.http_config = HTTPConfig()
        if self.oauth_config is None:
            self.oauth_config = OAuthConfig()

    @property
    def is_smb_mode(self) -> bool:
        """Check if configuration is for SMB mode."""
        return self.smb_config is not None

    @classmethod
    def get(cls) -> Config:
        """Get the singleton config instance, loading if needed.

        Lazy-loads configuration from environment and config file on first
        access. Subsequent calls return the cached instance.

        Returns:
            The singleton Config instance.

        Raises:
            YAMLConfigError: If configuration is invalid or incomplete.

        Example:
            >>> config = Config.get()
            >>> config.allowed_extensions
            {'.yaml', '.yml'}
        """
        if cls._instance is None:
            cls._instance = _load_config_internal()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton instance (for testing).

        Clears the cached config so the next Config.get() call will
        reload from environment and files.
        """
        cls._instance = None


def get_config_file_path() -> Path:
    """Get the path to the user configuration file.

    Returns:
        Path to ~/.config/mcp-yamlfilesystem/config

    Example:
        >>> path = get_config_file_path()
        >>> str(path).endswith('.config/mcp-yamlfilesystem/config')
        True
    """
    return Path.home() / ".config" / "mcp-yamlfilesystem" / "config"


def _get_config_dir_path() -> Path:
    """Get the path to the configuration directory.

    Returns:
        Path to ~/.config/mcp-yamlfilesystem/
    """
    return Path.home() / ".config" / "mcp-yamlfilesystem"


def _check_file_permissions(file_path: Path) -> None:
    """Check that a config file has secure permissions (600).

    Config files must have mode 600 (owner read/write only) to prevent
    other users from reading sensitive credentials.

    Args:
        file_path: Path to file to check.

    Raises:
        YAMLConfigError: If file permissions are too permissive.
    """
    # Skip permission check on Windows
    if sys.platform == "win32":
        return

    file_stat = file_path.stat()
    # Get only the permission bits (last 9 bits)
    current_mode = stat.S_IMODE(file_stat.st_mode)

    # Check if any group or other permissions are set
    if current_mode & 0o077:
        current_perms = oct(current_mode)
        raise YAMLConfigError(
            f"Insecure permissions on config file: {file_path}\n"
            f"Current permissions: {current_perms}, required: 0o600\n"
            f"Config files may contain sensitive credentials and must not be readable by others.\n"
            f"Fix with: chmod 600 {file_path}"
        )


def _validate_config_directory_permissions() -> None:
    """Validate permissions on all files in the config directory.

    Checks that all files in ~/.config/mcp-yamlfilesystem/ have secure
    permissions (600). This prevents other users from reading sensitive
    data like SMB credentials.

    Raises:
        YAMLConfigError: If any config file has insecure permissions.
    """
    # Skip on Windows
    if sys.platform == "win32":
        return

    config_dir = _get_config_dir_path()

    if not config_dir.exists():
        return  # No config directory yet

    if not config_dir.is_dir():
        return  # Not a directory, will be handled elsewhere

    # Check all files in the config directory
    for file_path in config_dir.iterdir():
        if file_path.is_file():
            _check_file_permissions(file_path)


def _parse_config_file(config_path: Path) -> dict[str, str]:
    """Parse simple key=value configuration file.

    Supports:
    - Comments starting with #
    - Blank lines
    - key=value format
    - Whitespace trimming

    Args:
        config_path: Path to configuration file.

    Returns:
        Dictionary of configuration key-value pairs.

    Example:
        >>> from tempfile import NamedTemporaryFile
        >>> with NamedTemporaryFile(mode='w', delete=False) as f:
        ...     _ = f.write("# Comment\\n")
        ...     _ = f.write("allowed_extensions=.yaml,.yml\\n")
        ...     path = Path(f.name)
        >>> config = _parse_config_file(path)
        >>> config['allowed_extensions']
        '.yaml,.yml'
        >>> path.unlink()
    """
    config = {}
    if not config_path.exists():
        return config

    content = config_path.read_text(encoding="utf-8")
    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            config[key.strip()] = value.strip()

    return config


def _parse_smb_path(smb_path: str) -> tuple[str, str, str]:
    """Parse SMB path into server, share, and base_path components.

    Supports formats:
    - //server/share
    - //server/share/path/to/dir
    - \\\\server\\share
    - \\\\server\\share\\path\\to\\dir
    - smb://server/share
    - smb://server/share/path/to/dir

    Args:
        smb_path: SMB path string.

    Returns:
        Tuple of (server, share, base_path).

    Raises:
        YAMLConfigError: If path format is invalid.

    Example:
        >>> _parse_smb_path("//fileserver/configs/homeassistant")
        ('fileserver', 'configs', 'homeassistant')
        >>> _parse_smb_path("smb://server/share")
        ('server', 'share', '')
    """
    # Normalize path separators
    normalized = smb_path.replace("\\", "/")

    # Remove smb:// prefix if present
    if normalized.startswith("smb://"):
        normalized = "//" + normalized[6:]

    # Validate format
    if not normalized.startswith("//"):
        raise YAMLConfigError(
            f"Invalid SMB path format: {smb_path}. "
            "Expected format: //server/share or //server/share/path"
        )

    # Remove leading //
    path_part = normalized[2:]

    # Split into components
    parts = path_part.split("/")
    parts = [p for p in parts if p]  # Remove empty parts

    if len(parts) < 2:
        raise YAMLConfigError(
            f"Invalid SMB path: {smb_path}. "
            "Must include at least server and share name (e.g., //server/share)"
        )

    server = parts[0]
    share = parts[1]
    base_path = "/".join(parts[2:]) if len(parts) > 2 else ""

    return server, share, base_path


def _load_smb_config(file_config: dict[str, str]) -> Optional[SMBConfig]:
    """Load SMB configuration from environment and config file.

    Environment variables take precedence over config file values.

    Environment variables:
        - MCP_FILESYSTEM_SMB_PATH: SMB share path (e.g., //server/share)
        - MCP_FILESYSTEM_SMB_USER: Username for authentication
        - MCP_FILESYSTEM_SMB_PASSWORD: Password for authentication

    Config file keys (same as environment variables for consistency):
        - MCP_FILESYSTEM_SMB_PATH: SMB share path
        - MCP_FILESYSTEM_SMB_USER: Username
        - MCP_FILESYSTEM_SMB_PASSWORD: Password

    Args:
        file_config: Parsed config file dictionary.

    Returns:
        SMBConfig if SMB is configured, None otherwise.

    Raises:
        YAMLConfigError: If SMB is partially configured (missing required fields).
    """
    # Get values from env vars (priority) or config file (same key names for consistency)
    smb_path = os.environ.get("MCP_FILESYSTEM_SMB_PATH") or file_config.get(
        "MCP_FILESYSTEM_SMB_PATH"
    )
    smb_user = os.environ.get("MCP_FILESYSTEM_SMB_USER") or file_config.get(
        "MCP_FILESYSTEM_SMB_USER"
    )
    smb_password = os.environ.get("MCP_FILESYSTEM_SMB_PASSWORD") or file_config.get(
        "MCP_FILESYSTEM_SMB_PASSWORD"
    )

    # Check if any SMB config is provided
    smb_values = [smb_path, smb_user, smb_password]
    if not any(smb_values):
        return None  # No SMB config

    # If partially configured, that's an error
    if not all(smb_values):
        missing = []
        if not smb_path:
            missing.append("MCP_FILESYSTEM_SMB_PATH")
        if not smb_user:
            missing.append("MCP_FILESYSTEM_SMB_USER")
        if not smb_password:
            missing.append("MCP_FILESYSTEM_SMB_PASSWORD")
        raise YAMLConfigError(
            f"Incomplete SMB configuration. Missing: {', '.join(missing)}. "
            "Either provide all SMB settings or none."
        )

    # Parse the SMB path
    server, share, base_path = _parse_smb_path(smb_path)

    # Parse ignore_dirs (comma-separated list of directory names to skip)
    ignore_dirs_str = _require_config("MCP_FILESYSTEM_SMB_IGNORE_DIRS", file_config)
    ignore_dirs = frozenset(d.strip() for d in ignore_dirs_str.split(",") if d.strip())

    logger.info(
        f"SMB mode configured: //{server}/{share}"
        + (f"/{base_path}" if base_path else "")
    )
    if ignore_dirs:
        logger.info(f"SMB ignore directories: {', '.join(sorted(ignore_dirs))}")

    return SMBConfig(
        server=server,
        share=share,
        username=smb_user,
        password=smb_password,
        base_path=base_path,
        ignore_dirs=ignore_dirs,
    )


def _load_log_config(file_config: dict[str, str]) -> LogConfig:
    """Load logging configuration from environment and config file.

    Environment variables take precedence over config file values.

    Required config keys (env var overrides config file):
        - DEBUG: Enable debug logging (true/false, 1/0, yes/no)
        - LOG_FILE: Path to log file (supports ~ expansion, empty = stderr only)

    Args:
        file_config: Parsed config file dictionary.

    Returns:
        LogConfig with debug setting and optional log file path.

    Example:
        >>> config = {"DEBUG": "true", "LOG_FILE": "~/mcp-debug.log"}
        >>> log_config = _load_log_config(config)
        >>> log_config.debug
        True
    """
    # Get debug setting (env var takes precedence)
    debug_str = _require_config("DEBUG", file_config)
    debug = debug_str.lower() in ("true", "1", "yes", "on")

    # Get log file path (env var takes precedence)
    log_file_str = _require_config("LOG_FILE", file_config)
    log_file = None

    if log_file_str:
        # Expand ~ and resolve to absolute path
        log_file = Path(log_file_str).expanduser().resolve()
        # Ensure parent directory exists
        log_file.parent.mkdir(parents=True, exist_ok=True)

    return LogConfig(debug=debug, log_file=log_file)


def _load_http_config(file_config: dict[str, str]) -> HTTPConfig:
    """Load HTTP transport configuration from environment and config file.

    Environment variables take precedence over config file values.

    Required config keys (env var overrides config file):
        - MCP_HTTP_ENABLED: Enable HTTP transport (true/false, 1/0, yes/no)
        - MCP_HTTP_HOST: Host address to bind to
        - MCP_HTTP_PORT: Port to bind to
        - MCP_HTTP_PATH: Endpoint path

    Args:
        file_config: Parsed config file dictionary.

    Returns:
        HTTPConfig with transport settings.

    Raises:
        YAMLConfigError: If MCP_HTTP_PORT is not a valid integer or is
            outside the range 1-65535.

    Example:
        >>> config = {"MCP_HTTP_ENABLED": "true", "MCP_HTTP_PORT": "9000"}
        >>> http_config = _load_http_config(config)
        >>> http_config.enabled
        True
        >>> http_config.port
        9000
    """
    # Get enabled setting (env var takes precedence)
    enabled_str = _require_config("MCP_HTTP_ENABLED", file_config)
    enabled = enabled_str.lower() in ("true", "1", "yes", "on")

    # Get host (env var takes precedence)
    host = _require_config("MCP_HTTP_HOST", file_config)

    # Get port (env var takes precedence)
    port_str = _require_config("MCP_HTTP_PORT", file_config)
    try:
        port = int(port_str)
    except ValueError:
        raise YAMLConfigError(
            f"Invalid MCP_HTTP_PORT value: {port_str}. Must be an integer."
        )

    if not (1 <= port <= 65535):
        raise YAMLConfigError(
            f"Invalid MCP_HTTP_PORT value: {port}. Must be between 1 and 65535."
        )

    # Get path (env var takes precedence)
    path = _require_config("MCP_HTTP_PATH", file_config)

    return HTTPConfig(enabled=enabled, host=host, port=port, path=path)


def _load_oauth_config(file_config: dict[str, str], http_enabled: bool) -> OAuthConfig:
    """Load OAuth configuration from environment and config file.

    Environment variables take precedence over config file values.
    OAuth is only relevant when HTTP mode is enabled.

    Required config keys (env var overrides config file):
        - MCP_OAUTH_ENABLED: Enable/disable OAuth (true/false, 1/0, yes/no)
        - MCP_OAUTH_CLIENT_ID: Google OAuth client ID
        - MCP_OAUTH_CLIENT_SECRET: Google OAuth client secret
        - MCP_OAUTH_BASE_URL: Public URL for OAuth callbacks
        - MCP_OAUTH_ALLOWED_EMAILS: Comma-separated list of allowed emails

    Args:
        file_config: Parsed config file dictionary.
        http_enabled: Whether HTTP transport is enabled.

    Returns:
        OAuthConfig with OAuth settings.

    Raises:
        YAMLConfigError: If OAuth is enabled but required credentials are missing.

    Example:
        >>> config = {"MCP_OAUTH_CLIENT_ID": "123.apps.googleusercontent.com"}
        >>> oauth_config = _load_oauth_config(config, http_enabled=True)
        >>> oauth_config.enabled
        True
    """
    # Get enabled setting (env var takes precedence)
    enabled_str = _require_config("MCP_OAUTH_ENABLED", file_config)
    enabled = enabled_str.lower() in ("true", "1", "yes", "on")

    # Get credentials (env var takes precedence)
    client_id = _require_config("MCP_OAUTH_CLIENT_ID", file_config)
    client_secret = _require_config("MCP_OAUTH_CLIENT_SECRET", file_config)
    base_url = _require_config("MCP_OAUTH_BASE_URL", file_config)

    # Get allowed emails (comma-separated)
    emails_str = _require_config("MCP_OAUTH_ALLOWED_EMAILS", file_config)
    allowed_emails = [email.strip() for email in emails_str.split(",") if email.strip()]

    # Validate: if enabled and HTTP is enabled, credentials are required
    if enabled and http_enabled:
        missing = []
        if not client_id:
            missing.append("MCP_OAUTH_CLIENT_ID")
        if not client_secret:
            missing.append("MCP_OAUTH_CLIENT_SECRET")
        if not base_url:
            missing.append("MCP_OAUTH_BASE_URL")

        if missing:
            raise YAMLConfigError(
                f"OAuth is enabled but missing required configuration: {', '.join(missing)}.\n"
                "Either provide all OAuth settings or disable OAuth with MCP_OAUTH_ENABLED=false"
            )

    return OAuthConfig(
        enabled=enabled,
        client_id=client_id,
        client_secret=client_secret,
        base_url=base_url,
        allowed_emails=allowed_emails,
    )


def _parse_allowed_extensions(extensions_str: str) -> Set[str]:
    """Parse comma-separated list of file extensions.

    Ensures all extensions start with a dot.

    Args:
        extensions_str: Comma-separated extensions (e.g., ".yaml,.yml" or "yaml,yml").

    Returns:
        Set of normalized extensions with leading dots.

    Example:
        >>> _parse_allowed_extensions(".yaml,.yml")
        {'.yaml', '.yml'}
        >>> _parse_allowed_extensions("yaml,yml,json")
        {'.yaml', '.yml', '.json'}
        >>> _parse_allowed_extensions("")
        set()
    """
    if not extensions_str:
        return set()

    extensions = set()
    for ext in extensions_str.split(","):
        ext = ext.strip()
        if ext and not ext.startswith("."):
            ext = f".{ext}"
        if ext:
            extensions.add(ext.lower())

    return extensions


def _load_config_internal() -> Config:
    """Load and validate configuration from environment and config file.

    Internal function called by Config.get() on first access. Do not call
    directly - use Config.get() instead.

    Supports two modes:

    1. SMB Mode (if SMB config provided):
       - Requires MCP_FILESYSTEM_SMB_PATH, MCP_FILESYSTEM_SMB_USER, MCP_FILESYSTEM_SMB_PASSWORD
       - Same keys work in config file for consistency
       - Git requirement is skipped (SMB shares typically don't have .git)
       - Works without root privileges, connection is private to process

    2. Local Mode (default):
       - Reads local path with priority order:
         1. MCP_FILESYSTEM_LOCAL_PATH environment variable (set by --local-path CLI)
         2. MCP_FILESYSTEM_LOCAL_PATH in ~/.config/mcp-yamlfilesystem/config
       - Path must exist and be a directory (git version control recommended)

    Reads allowed_extensions with priority order:
    1. Config file: ~/.config/mcp-yamlfilesystem/config (ALLOWED_EXTENSIONS=.yaml,.yml)
    2. Environment variable: ALLOWED_EXTENSIONS (e.g., export ALLOWED_EXTENSIONS=.yaml,.yml,.json)
    3. Default: {'.yaml', '.yml'}

    Returns:
        Validated Config object with absolute paths and allowed extensions.

    Raises:
        YAMLConfigError: If configuration is invalid or incomplete.
    """
    # Validate config directory permissions before reading any files
    _validate_config_directory_permissions()

    # Load config file first (needed for both SMB and local mode)
    config_file_path = get_config_file_path()
    file_config = _parse_config_file(config_file_path)

    # Load allowed extensions with priority: config file > env var > default
    default_extensions = {".yaml", ".yml"}
    allowed_extensions = None

    # Priority 1: Check config file (using consistent ALLOWED_EXTENSIONS key)
    if extensions_str := file_config.get("ALLOWED_EXTENSIONS"):
        allowed_extensions = _parse_allowed_extensions(extensions_str)

    # Priority 2: Check environment variable if not in config file
    if not allowed_extensions:
        if env_extensions := os.environ.get("ALLOWED_EXTENSIONS"):
            allowed_extensions = _parse_allowed_extensions(env_extensions)

    # Priority 3: Use defaults if neither config file nor env var set
    if not allowed_extensions:
        allowed_extensions = default_extensions

    # Load logging configuration
    log_config = _load_log_config(file_config)

    # Load HTTP transport configuration
    http_config = _load_http_config(file_config)

    # Load OAuth configuration (depends on HTTP being enabled)
    oauth_config = _load_oauth_config(file_config, http_config.enabled)

    # Check for SMB configuration first
    smb_config = _load_smb_config(file_config)

    if smb_config:
        # SMB mode - no local path needed, git check skipped
        logger.info("Running in SMB mode - git requirement skipped")
        return Config(
            yaml_root_path=None,
            allowed_extensions=allowed_extensions,
            smb_config=smb_config,
            log_config=log_config,
            http_config=http_config,
            oauth_config=oauth_config,
        )

    # Local mode - determine path with priority: env var > config file
    local_path_str = os.environ.get("MCP_FILESYSTEM_LOCAL_PATH")

    if not local_path_str:
        local_path_str = file_config.get("MCP_FILESYSTEM_LOCAL_PATH")

    if not local_path_str:
        raise YAMLConfigError(
            "Configuration required. Set local path using one of these methods:\n"
            "  1. --local-path command line argument\n"
            "  2. MCP_FILESYSTEM_LOCAL_PATH environment variable\n"
            "  3. MCP_FILESYSTEM_LOCAL_PATH in ~/.config/mcp-yamlfilesystem/config\n\n"
            "Or configure SMB mode with MCP_FILESYSTEM_SMB_PATH, MCP_FILESYSTEM_SMB_USER, "
            "and MCP_FILESYSTEM_SMB_PASSWORD.\n\n"
            "Copy config.example to ~/.config/mcp-yamlfilesystem/config and edit it."
        )

    yaml_root_path = Path(local_path_str).resolve()

    if not yaml_root_path.exists():
        raise YAMLConfigError(
            f"MCP_FILESYSTEM_LOCAL_PATH directory does not exist: {yaml_root_path}"
        )

    if not yaml_root_path.is_dir():
        raise YAMLConfigError(
            f"MCP_FILESYSTEM_LOCAL_PATH is not a directory: {yaml_root_path}"
        )

    git_dir = yaml_root_path / ".git"
    if not git_dir.exists():
        logger.warning(
            "Directory is not git-controlled: %s - "
            "Git version control is recommended for safety and traceability. "
            "Run 'git init' in the directory to enable change tracking.",
            yaml_root_path,
        )

    return Config(
        yaml_root_path=yaml_root_path,
        allowed_extensions=allowed_extensions,
        log_config=log_config,
        http_config=http_config,
        oauth_config=oauth_config,
    )
