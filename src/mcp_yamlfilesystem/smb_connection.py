"""
Module: smb_connection

Purpose:
    Self-healing SMB connection manager with automatic reconnection and retry logic.
    Encapsulates all connection state and provides execute() for transparent
    connection management. Callers never need to know about connection lifecycle.

Classes:
    - SMBConnection: Self-healing connection wrapper for SMB operations

Usage Example:
    conn = SMBConnection(server="fileserver", share="configs",
                         username="user", password="pass")

    # High-level operations via execute()
    result = conn.execute(lambda: smbclient.stat(path), "stat file")

    # Low-level compound requests via execute_compound()
    entries = conn.execute_compound(lambda: do_compound_scan(), "scan dir")

Design Notes:
    - Lazy connection: connects on first execute() call
    - Health checked via SMB echo before operations
    - Auto-reconnects on stale connections (max 3 attempts, 3s total)
    - Dual connection: smbprotocol for compound requests, smbclient for file ops
"""

import logging
import time
import uuid as uuid_module
from typing import Callable, TypeVar

from mcp_yamlfilesystem.exceptions import SMBConnectionError

logger = logging.getLogger(__name__)

# Connection resilience configuration
MAX_RECONNECT_ATTEMPTS = 3
RECONNECT_DELAY_SECONDS = 0.5
TOTAL_RECONNECT_TIMEOUT = 3.0

T = TypeVar("T")


class SMBConnection:
    """Self-healing SMB connection - owns its complete lifecycle.

    Manages both low-level smbprotocol objects (for compound requests) and
    high-level smbclient registration (for standard file operations).
    Provides execute() and execute_compound() methods that handle all
    connection management transparently.

    Attributes:
        server: SMB server hostname or IP
        share: Share name on the server
    """

    def __init__(
        self,
        server: str,
        share: str,
        username: str,
        password: str,
    ) -> None:
        """Initialize connection parameters (does not connect yet).

        Args:
            server: SMB server hostname or IP address.
            share: Name of the share on the server.
            username: Username for SMB authentication.
            password: Password for SMB authentication.
        """
        self._server = server
        self._share = share
        self._username = username
        self._password = password

        # Connection state - all None until first execute()
        self._connected = False
        self._connection = None  # smbprotocol.connection.Connection
        self._session = None  # smbprotocol.session.Session
        self._tree = None  # smbprotocol.tree.TreeConnect

        logger.debug(f"SMBConnection configured for //{server}/{share}")

    @property
    def server(self) -> str:
        """Get server hostname."""
        return self._server

    @property
    def share(self) -> str:
        """Get share name."""
        return self._share

    @property
    def tree(self):
        """Get TreeConnect for compound requests (ensures connected first)."""
        self._ensure_connected()
        return self._tree

    @property
    def connection(self):
        """Get Connection for compound requests (ensures connected first)."""
        self._ensure_connected()
        return self._connection

    @property
    def session(self):
        """Get Session for compound requests (ensures connected first)."""
        self._ensure_connected()
        return self._session

    @staticmethod
    def _is_file_not_found(exc: Exception) -> bool:
        """Check if exception represents a file-not-found condition.

        smbclient raises SMBOSError (subclass of OSError) with errno=2 for
        missing files/paths, but Python's auto-subclass selection only promotes
        OSError itself to FileNotFoundError, not subclasses. This helper catches
        both standard FileNotFoundError and SMBOSError with errno ENOENT.
        """
        if isinstance(exc, FileNotFoundError):
            return True
        if isinstance(exc, OSError) and exc.errno == 2:
            return True
        return False

    def execute(self, operation: Callable[[], T], operation_name: str) -> T:
        """Execute an SMB operation with transparent connection management.

        Handles:
        - Initial connection if not connected
        - Health check before operation
        - Automatic retry on connection failure
        - Clear error messages when truly unavailable

        Args:
            operation: Callable that performs the SMB operation.
            operation_name: Human-readable name for error messages.

        Returns:
            Result of the operation.

        Raises:
            SMBConnectionError: When connection unavailable after retries.
            FileNotFoundError: Propagated from operation (legitimate result).
            OSError: Propagated when errno is ENOENT (file not found).
            Other exceptions from operation are wrapped in SMBConnectionError.
        """
        self._ensure_connected()

        try:
            return operation()
        except Exception as e:
            if self._is_file_not_found(e):
                raise
            # Connection may have died mid-operation - reconnect and retry once
            logger.debug(f"Error during {operation_name}, attempting reconnect: {e}")
            self._disconnect()
            self._ensure_connected()

            try:
                return operation()
            except Exception as retry_error:
                if self._is_file_not_found(retry_error):
                    raise
                raise SMBConnectionError(
                    f"Tool unavailable due to SMB connectivity error: "
                    f"Cannot {operation_name}: {retry_error}"
                )

    def execute_compound(self, operation: Callable[[], T], operation_name: str) -> T:
        """Execute a compound SMB request with connection management.

        Same as execute() but validates low-level connection objects first.
        Use for operations that directly access tree, connection, session.

        Args:
            operation: Callable using self.tree, self.connection, self.session.
            operation_name: Human-readable name for error messages.

        Returns:
            Result of the operation.

        Raises:
            SMBConnectionError: When connection unavailable or objects invalid.
        """
        self._ensure_connected()

        if self._connection is None or self._session is None or self._tree is None:
            raise SMBConnectionError(
                "Tool unavailable due to SMB connectivity error: "
                "Connection objects are not initialized"
            )

        try:
            return operation()
        except SMBConnectionError:
            raise
        except Exception as e:
            logger.debug(f"Error during {operation_name}, attempting reconnect: {e}")
            self._disconnect()
            self._ensure_connected()

            try:
                return operation()
            except Exception as retry_error:
                raise SMBConnectionError(
                    f"Tool unavailable due to SMB connectivity error: "
                    f"Cannot {operation_name}: {retry_error}"
                )

    def _connect(self) -> None:
        """Establish SMB connection (internal).

        Creates both low-level smbprotocol objects and registers with smbclient.
        """
        if self._connected:
            return

        try:
            from smbclient import register_session

            from smbprotocol.connection import Connection
            from smbprotocol.session import Session
            from smbprotocol.tree import TreeConnect

            connection = Connection(uuid_module.uuid4(), self._server, port=445)
            connection.connect()

            session = Session(
                connection=connection,
                username=self._username,
                password=self._password,
            )
            session.connect()

            tree = TreeConnect(session, f"\\\\{self._server}\\{self._share}")
            tree.connect()

            register_session(
                self._server,
                username=self._username,
                password=self._password,
            )

            self._connection = connection
            self._session = session
            self._tree = tree
            self._connected = True
            logger.info(f"Connected to SMB share //{self._server}/{self._share}")

        except Exception as e:
            logger.error(f"Failed to connect to SMB share: {e}")
            raise IOError(f"SMB connection failed: {e}")

    def _disconnect(self) -> None:
        """Disconnect and reset state (internal)."""
        if self._tree is not None:
            try:
                self._tree.disconnect()
            except Exception as e:
                logger.debug(f"Error disconnecting tree: {e}")
        if self._session is not None:
            try:
                self._session.disconnect()
            except Exception as e:
                logger.debug(f"Error disconnecting session: {e}")
        if self._connection is not None:
            try:
                self._connection.disconnect()
            except Exception as e:
                logger.debug(f"Error disconnecting connection: {e}")

        self._connection = None
        self._session = None
        self._tree = None
        self._connected = False
        logger.debug("SMB connection state reset")

    def _is_connection_alive(self) -> bool:
        """Check if connection is alive via echo request."""
        if not self._connected or self._connection is None:
            return False

        try:
            self._connection.echo()
            return True
        except Exception as e:
            logger.debug(f"Connection health check failed: {e}")
            return False

    def _ensure_connected(self) -> None:
        """Ensure connection is alive, reconnecting if necessary."""
        if not self._connected:
            self._connect_with_retry()
            return

        if self._is_connection_alive():
            return

        logger.info("SMB connection is stale, attempting to reconnect...")
        self._disconnect()
        self._connect_with_retry()

    def _connect_with_retry(self) -> None:
        """Connect with retry logic (max 3 seconds total)."""
        start_time = time.monotonic()
        last_error = None

        for attempt in range(1, MAX_RECONNECT_ATTEMPTS + 1):
            elapsed = time.monotonic() - start_time
            if elapsed >= TOTAL_RECONNECT_TIMEOUT:
                break

            try:
                logger.debug(
                    f"SMB connection attempt {attempt}/{MAX_RECONNECT_ATTEMPTS}"
                )
                self._connect()
                logger.info(
                    f"SMB reconnection successful on attempt {attempt}"
                    if attempt > 1
                    else "SMB connection established"
                )
                return
            except Exception as e:
                last_error = e
                logger.warning(f"SMB connection attempt {attempt} failed: {e}")

                if attempt < MAX_RECONNECT_ATTEMPTS:
                    remaining_time = TOTAL_RECONNECT_TIMEOUT - elapsed
                    delay = min(RECONNECT_DELAY_SECONDS, remaining_time)
                    if delay > 0:
                        time.sleep(delay)

        error_msg = (
            f"Tool unavailable due to SMB connectivity error: "
            f"Failed to connect after {MAX_RECONNECT_ATTEMPTS} attempts. "
            f"Last error: {last_error}"
        )
        logger.error(error_msg)
        raise SMBConnectionError(error_msg)
