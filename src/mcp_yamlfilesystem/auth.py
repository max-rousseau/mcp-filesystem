"""
Module: auth

Purpose:
    Custom OAuth authentication components for MCP YAML Filesystem server.
    Implements Google OAuth token verification with email allowlist validation
    using the official MCP SDK's TokenVerifier protocol.

Classes:
    - AccessToken: Extended AccessToken with claims support
    - GoogleTokenVerifier: Verifies Google OAuth tokens
    - EmailAllowlistTokenVerifier: Token verifier that validates email against allowlist

Functions:
    - create_google_auth: Factory function for creating auth components

Usage Example:
    from mcp_yamlfilesystem.auth import create_google_auth

    token_verifier, auth_settings = create_google_auth(
        client_id="123456789.apps.googleusercontent.com",
        client_secret="GOCSPX-abc123",
        base_url="https://my-server.com",
        allowed_emails=["admin@example.com", "user@example.com"]
    )
"""

import logging
import time
from typing import Any

import httpx
from pydantic import AnyHttpUrl

from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.provider import AccessToken as BaseAccessToken
from mcp.server.auth.settings import AuthSettings

logger = logging.getLogger(__name__)


class AccessToken(BaseAccessToken):
    """Extended AccessToken with claims support for backward compatibility.

    Extends the official MCP SDK's AccessToken to include a claims dict
    for storing additional token information like email.

    Attributes:
        claims: Dictionary of additional token claims (e.g., email, sub).
    """

    claims: dict[str, Any] = {}


class GoogleTokenVerifier:
    """Token verifier that validates Google OAuth tokens.

    Verifies tokens by calling Google's tokeninfo endpoint.

    Attributes:
        required_scopes: List of required OAuth scopes.
        timeout_seconds: HTTP request timeout for Google API calls.

    Example:
        >>> verifier = GoogleTokenVerifier(
        ...     required_scopes=["openid", "email"],
        ...     timeout_seconds=10
        ... )
    """

    GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"

    def __init__(
        self,
        *,
        required_scopes: list[str] | None = None,
        timeout_seconds: int = 10,
    ):
        """Initialize the Google token verifier.

        Args:
            required_scopes: Required OAuth scopes for token validation.
            timeout_seconds: HTTP request timeout for Google API calls.
        """
        self.required_scopes = required_scopes or ["openid", "email"]
        self.timeout_seconds = timeout_seconds

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify a Google OAuth token.

        Args:
            token: The OAuth access token to verify.

        Returns:
            AccessToken if token is valid, all required scopes are present,
            and email is verified; None otherwise.
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(
                    self.GOOGLE_TOKENINFO_URL,
                    headers={"Authorization": f"Bearer {token}"},
                )

                if response.status_code != 200:
                    logger.warning(
                        f"Google token verification failed: {response.status_code}"
                    )
                    return None

                token_info = response.json()

                # Validate scopes
                token_scopes = token_info.get("scope", "").split()
                for required_scope in self.required_scopes:
                    if required_scope not in token_scopes:
                        logger.warning(
                            f"Token missing required scope: {required_scope}"
                        )
                        return None

                # Reject tokens with unverified email
                if not token_info.get("email_verified", False):
                    logger.warning("Token email not verified, rejecting")
                    return None

                return AccessToken(
                    token=token,
                    client_id=token_info.get("azp", ""),
                    scopes=token_scopes,
                    expires_at=int(time.time()) + int(token_info.get("expires_in", 0)),
                    claims={
                        "email": token_info.get("email", ""),
                        "sub": token_info.get("sub", ""),
                        "email_verified": token_info.get("email_verified", False),
                    },
                )

        except httpx.HTTPError as e:
            logger.error(f"HTTP error during token verification: {e}")
            return None
        except Exception as e:
            logger.error(f"Error during token verification: {e}")
            return None


class EmailAllowlistTokenVerifier(GoogleTokenVerifier):
    """Token verifier that validates against an email allowlist.

    Extends GoogleTokenVerifier to add email-based access control.
    If allowed_emails is empty, all authenticated users are allowed.

    Attributes:
        allowed_emails: Set of email addresses permitted to access the server.

    Example:
        >>> verifier = EmailAllowlistTokenVerifier(
        ...     allowed_emails=["admin@example.com", "user@example.com"],
        ...     required_scopes=["openid", "email"]
        ... )
    """

    def __init__(
        self,
        *,
        allowed_emails: list[str] | None = None,
        required_scopes: list[str] | None = None,
        timeout_seconds: int = 10,
    ):
        """Initialize the email allowlist token verifier.

        Args:
            allowed_emails: List of allowed email addresses. Empty/None allows all.
            required_scopes: Required OAuth scopes for token validation.
            timeout_seconds: HTTP request timeout for Google API calls.
        """
        super().__init__(
            required_scopes=required_scopes,
            timeout_seconds=timeout_seconds,
        )
        self.allowed_emails: set[str] = (
            {e.lower() for e in allowed_emails} if allowed_emails else set()
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify token and check email against allowlist.

        Args:
            token: The OAuth access token to verify.

        Returns:
            AccessToken if valid and email is allowed, None otherwise.
        """
        # First, do standard Google token verification
        access_token = await super().verify_token(token)

        if access_token is None:
            return None

        # If no allowlist configured, allow all authenticated users
        if not self.allowed_emails:
            logger.debug(
                "No email allowlist configured, allowing all authenticated users"
            )
            return access_token

        # Check email against allowlist
        email = access_token.claims.get("email", "")

        if not email:
            logger.warning("Token valid but no email claim present")
            return None

        if email.lower() not in self.allowed_emails:
            logger.warning(f"Email {email} not in allowlist, denying access")
            return None

        logger.debug(f"Email {email} verified against allowlist")
        return access_token


def create_google_auth(
    client_id: str,
    client_secret: str,
    base_url: str,
    allowed_emails: list[str] | None = None,
) -> tuple[TokenVerifier, AuthSettings]:
    """Create Google OAuth auth components for the MCP SDK.

    Factory function that creates a token verifier and auth settings.
    If an email allowlist is provided, uses EmailAllowlistTokenVerifier.

    Args:
        client_id: Google OAuth client ID.
        client_secret: Google OAuth client secret.
        base_url: Public URL for OAuth callbacks.
        allowed_emails: Optional list of allowed email addresses.

    Returns:
        Tuple of (TokenVerifier, AuthSettings) for use with FastMCP.

    Example:
        >>> verifier, settings = create_google_auth(
        ...     client_id="123.apps.googleusercontent.com",
        ...     client_secret="GOCSPX-abc",
        ...     base_url="https://example.com",
        ...     allowed_emails=["admin@example.com"]
        ... )
    """
    if allowed_emails:
        logger.info(
            f"Creating Google OAuth with email allowlist: "
            f"{len(allowed_emails)} allowed emails"
        )
        token_verifier: TokenVerifier = EmailAllowlistTokenVerifier(
            allowed_emails=allowed_emails,
        )
    else:
        logger.info("Creating Google OAuth (all authenticated users allowed)")
        token_verifier = GoogleTokenVerifier()

    auth_settings = AuthSettings(
        issuer_url=AnyHttpUrl("https://accounts.google.com"),
        resource_server_url=AnyHttpUrl(base_url),
    )

    return token_verifier, auth_settings
