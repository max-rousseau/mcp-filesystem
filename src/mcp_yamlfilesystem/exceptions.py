"""
Module: exceptions

Purpose:
    Custom exception hierarchy for MCP YAML Filesystem tool. Provides specific
    exception types for different failure modes to enable precise error handling
    and clear error messages to AI agents and users.

Classes:
    - YAMLConfigError: Base exception for all configuration errors
    - YAMLSyntaxError: Invalid YAML syntax errors
    - FilePathError: File path security and validation errors
    - SMBConnectionError: SMB share connectivity failures

Usage Example:
    from mcp_yamlfilesystem.exceptions import FilePathError

    def validate_path(path):
        if path.is_absolute():
            raise FilePathError("Absolute paths not allowed")

Exception Hierarchy:
    YAMLConfigError (base for configuration errors)
    ├── YAMLSyntaxError
    └── FilePathError

    SMBConnectionError (standalone - runtime connectivity errors)

Happy Path Flow:

```mermaid
sequenceDiagram
    participant Client
    participant Manager
    participant Validator
    participant Exception

    Client->>Manager: operation()
    Manager->>Validator: validate()

    alt Validation Succeeds
        Validator-->>Manager: success
        Manager-->>Client: result
    else Validation Fails
        Validator->>Exception: raise specific error
        Exception-->>Manager: exception
        Manager-->>Client: propagate exception
    end
```
"""


class YAMLConfigError(Exception):
    """Base exception for YAML configuration errors.

    This is the parent class for all MCP YAML Filesystem exceptions. It provides
    a common base for catching any configuration-related error.

    Example:
        >>> try:
        ...     manager.read_file("config.yaml")
        ... except YAMLConfigError as e:
        ...     print(f"Configuration error: {e}")
    """

    pass


class YAMLSyntaxError(YAMLConfigError):
    """Raised when YAML syntax is invalid.

    This exception is raised when YAML content fails parsing validation.
    It prevents writing syntactically invalid YAML files.

    Example:
        >>> content = "key: [unclosed list"
        >>> manager.validate_yaml(content)
        Traceback (most recent call last):
        ...
        YAMLSyntaxError: Invalid YAML syntax: ...
    """

    pass


class FilePathError(YAMLConfigError):
    """Raised when file path is invalid or outside allowed directory.

    This exception enforces security boundaries by rejecting:
    - Absolute paths
    - Paths outside root directory
    - Paths with invalid characters
    - Non-YAML file extensions

    Example:
        >>> manager.validate_path("/etc/passwd")
        Traceback (most recent call last):
        ...
        FilePathError: Absolute paths are not allowed...

        >>> manager.validate_path("../../../etc/passwd")
        Traceback (most recent call last):
        ...
        FilePathError: File path must be within config directory...
    """

    pass


class SMBConnectionError(Exception):
    """Raised when SMB connection fails or becomes unavailable.

    This exception indicates that the SMB filesystem backend cannot communicate
    with the remote server. It is raised after reconnection attempts have been
    exhausted, providing a clear error message for the calling AI agent.

    This exception is intentionally NOT a subclass of YAMLConfigError as it
    represents a runtime connectivity issue rather than a configuration problem.

    Example:
        >>> smb_fs.read_text("config.yaml")
        Traceback (most recent call last):
        ...
        SMBConnectionError: Tool unavailable due to SMB connectivity error:
        Connection timed out after 3 reconnection attempts

    Typical causes:
        - Server became unreachable (network issue, server restart)
        - Session expired after long idle period
        - Authentication credentials expired or revoked
        - Share became unavailable on the server
    """

    pass
