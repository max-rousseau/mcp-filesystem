"""Tests for OAuth authentication components."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from mcp_yamlfilesystem.auth import (
    AccessToken,
    GoogleTokenVerifier,
    EmailAllowlistTokenVerifier,
    create_google_auth,
)
from mcp.server.auth.settings import AuthSettings


class TestAccessToken:
    """Tests for extended AccessToken with claims support."""

    def test_access_token_with_claims(self):
        """Test AccessToken creation with claims."""
        token = AccessToken(
            token="test_token",
            client_id="test_client",
            scopes=["openid", "email"],
            claims={"email": "user@example.com", "sub": "12345"},
        )
        assert token.claims["email"] == "user@example.com"
        assert token.claims["sub"] == "12345"

    def test_access_token_default_claims(self):
        """Test AccessToken with default empty claims."""
        token = AccessToken(
            token="test_token",
            client_id="test_client",
            scopes=["openid"],
        )
        assert token.claims == {}


class TestEmailAllowlistTokenVerifier:
    """Tests for EmailAllowlistTokenVerifier class."""

    def test_init_with_empty_allowlist(self):
        """Test initialization with empty allowlist."""
        verifier = EmailAllowlistTokenVerifier(allowed_emails=[])
        assert verifier.allowed_emails == set()

    def test_init_with_allowlist(self):
        """Test initialization with email allowlist."""
        emails = ["admin@example.com", "user@example.com"]
        verifier = EmailAllowlistTokenVerifier(allowed_emails=emails)
        assert verifier.allowed_emails == {"admin@example.com", "user@example.com"}

    def test_init_normalizes_emails_to_lowercase(self):
        """Test that email addresses are normalized to lowercase."""
        emails = ["Admin@Example.COM", "User@Example.COM"]
        verifier = EmailAllowlistTokenVerifier(allowed_emails=emails)
        assert verifier.allowed_emails == {"admin@example.com", "user@example.com"}

    def test_init_with_none_allowlist(self):
        """Test initialization with None allowlist."""
        verifier = EmailAllowlistTokenVerifier(allowed_emails=None)
        assert verifier.allowed_emails == set()

    @pytest.mark.asyncio
    async def test_verify_token_no_allowlist_allows_all(self):
        """Test that empty allowlist allows all authenticated users."""
        verifier = EmailAllowlistTokenVerifier(allowed_emails=None)

        # Mock the parent class verify_token
        mock_token = AccessToken(
            token="valid_token",
            client_id="test_client",
            scopes=["openid", "email"],
            claims={"email": "anyone@example.com", "sub": "12345"},
        )

        with patch.object(
            GoogleTokenVerifier,
            "verify_token",
            new_callable=AsyncMock,
            return_value=mock_token,
        ):
            result = await verifier.verify_token("test_token")
            assert result is not None
            assert result.claims["email"] == "anyone@example.com"

    @pytest.mark.asyncio
    async def test_verify_token_invalid_token_returns_none(self):
        """Test that invalid token returns None."""
        verifier = EmailAllowlistTokenVerifier(allowed_emails=["admin@example.com"])

        with patch.object(
            GoogleTokenVerifier,
            "verify_token",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await verifier.verify_token("invalid_token")
            assert result is None

    @pytest.mark.asyncio
    async def test_verify_token_email_in_allowlist_succeeds(self):
        """Test that token with allowed email succeeds."""
        verifier = EmailAllowlistTokenVerifier(
            allowed_emails=["admin@example.com", "user@example.com"]
        )

        mock_token = AccessToken(
            token="valid_token",
            client_id="test_client",
            scopes=["openid", "email"],
            claims={"email": "admin@example.com", "sub": "12345"},
        )

        with patch.object(
            GoogleTokenVerifier,
            "verify_token",
            new_callable=AsyncMock,
            return_value=mock_token,
        ):
            result = await verifier.verify_token("test_token")
            assert result is not None
            assert result.claims["email"] == "admin@example.com"

    @pytest.mark.asyncio
    async def test_verify_token_email_not_in_allowlist_fails(self):
        """Test that token with non-allowed email fails."""
        verifier = EmailAllowlistTokenVerifier(allowed_emails=["admin@example.com"])

        mock_token = AccessToken(
            token="valid_token",
            client_id="test_client",
            scopes=["openid", "email"],
            claims={"email": "hacker@badsite.com", "sub": "12345"},
        )

        with patch.object(
            GoogleTokenVerifier,
            "verify_token",
            new_callable=AsyncMock,
            return_value=mock_token,
        ):
            result = await verifier.verify_token("test_token")
            assert result is None

    @pytest.mark.asyncio
    async def test_verify_token_case_insensitive_email_check(self):
        """Test that email check is case-insensitive."""
        verifier = EmailAllowlistTokenVerifier(allowed_emails=["Admin@Example.COM"])

        mock_token = AccessToken(
            token="valid_token",
            client_id="test_client",
            scopes=["openid", "email"],
            claims={"email": "admin@example.com", "sub": "12345"},
        )

        with patch.object(
            GoogleTokenVerifier,
            "verify_token",
            new_callable=AsyncMock,
            return_value=mock_token,
        ):
            result = await verifier.verify_token("test_token")
            assert result is not None

    @pytest.mark.asyncio
    async def test_verify_token_no_email_claim_fails(self):
        """Test that token without email claim fails."""
        verifier = EmailAllowlistTokenVerifier(allowed_emails=["admin@example.com"])

        mock_token = AccessToken(
            token="valid_token",
            client_id="test_client",
            scopes=["openid"],
            claims={"sub": "12345"},  # No email claim
        )

        with patch.object(
            GoogleTokenVerifier,
            "verify_token",
            new_callable=AsyncMock,
            return_value=mock_token,
        ):
            result = await verifier.verify_token("test_token")
            assert result is None

    @pytest.mark.asyncio
    async def test_verify_token_empty_email_claim_fails(self):
        """Test that token with empty email claim fails."""
        verifier = EmailAllowlistTokenVerifier(allowed_emails=["admin@example.com"])

        mock_token = AccessToken(
            token="valid_token",
            client_id="test_client",
            scopes=["openid", "email"],
            claims={"email": "", "sub": "12345"},
        )

        with patch.object(
            GoogleTokenVerifier,
            "verify_token",
            new_callable=AsyncMock,
            return_value=mock_token,
        ):
            result = await verifier.verify_token("test_token")
            assert result is None


class TestCreateGoogleAuth:
    """Tests for create_google_auth factory function."""

    def test_create_without_allowlist_returns_google_verifier(self):
        """Test that provider without allowlist uses GoogleTokenVerifier."""
        token_verifier, auth_settings = create_google_auth(
            client_id="test-id.apps.googleusercontent.com",
            client_secret="test-secret",
            base_url="https://example.com",
            allowed_emails=None,
        )

        assert isinstance(token_verifier, GoogleTokenVerifier)
        assert not isinstance(token_verifier, EmailAllowlistTokenVerifier)
        assert isinstance(auth_settings, AuthSettings)

    def test_create_with_empty_list_returns_google_verifier(self):
        """Test that empty allowlist returns GoogleTokenVerifier."""
        token_verifier, auth_settings = create_google_auth(
            client_id="test-id.apps.googleusercontent.com",
            client_secret="test-secret",
            base_url="https://example.com",
            allowed_emails=[],
        )

        assert isinstance(token_verifier, GoogleTokenVerifier)
        assert not isinstance(token_verifier, EmailAllowlistTokenVerifier)

    def test_create_with_allowlist_returns_allowlist_verifier(self):
        """Test that allowlist returns EmailAllowlistTokenVerifier."""
        token_verifier, auth_settings = create_google_auth(
            client_id="test-id.apps.googleusercontent.com",
            client_secret="test-secret",
            base_url="https://example.com",
            allowed_emails=["admin@example.com"],
        )

        assert isinstance(token_verifier, EmailAllowlistTokenVerifier)
        assert isinstance(auth_settings, AuthSettings)

    def test_create_with_multiple_emails_in_allowlist(self):
        """Test creation with multiple allowed emails."""
        emails = ["admin@example.com", "user@example.com", "support@example.com"]
        token_verifier, auth_settings = create_google_auth(
            client_id="test-id.apps.googleusercontent.com",
            client_secret="test-secret",
            base_url="https://example.com",
            allowed_emails=emails,
        )

        assert isinstance(token_verifier, EmailAllowlistTokenVerifier)
        assert token_verifier.allowed_emails == {e.lower() for e in emails}

    def test_auth_settings_configured_correctly(self):
        """Test that AuthSettings is configured with correct URLs."""
        token_verifier, auth_settings = create_google_auth(
            client_id="test-id.apps.googleusercontent.com",
            client_secret="test-secret",
            base_url="https://my-server.example.com",
            allowed_emails=None,
        )

        assert str(auth_settings.issuer_url) == "https://accounts.google.com/"
        assert (
            str(auth_settings.resource_server_url) == "https://my-server.example.com/"
        )


class TestGoogleTokenVerifier:
    """Tests for GoogleTokenVerifier class."""

    def test_init_default_scopes(self):
        """Test initialization with default scopes."""
        verifier = GoogleTokenVerifier()
        assert verifier.required_scopes == ["openid", "email"]
        assert verifier.timeout_seconds == 10

    def test_init_custom_scopes(self):
        """Test initialization with custom scopes."""
        verifier = GoogleTokenVerifier(
            required_scopes=["openid", "profile"],
            timeout_seconds=30,
        )
        assert verifier.required_scopes == ["openid", "profile"]
        assert verifier.timeout_seconds == 30

    @pytest.mark.asyncio
    async def test_verify_token_returns_access_token_on_success(self):
        """Test that successful verification returns AccessToken."""
        verifier = GoogleTokenVerifier()

        # Create a mock response - json() is sync, not async in httpx
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "azp": "test_client",
            "scope": "openid email",
            "expires_in": 3600,
            "email": "user@example.com",
            "sub": "12345",
            "email_verified": True,
        }

        with patch("mcp_yamlfilesystem.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await verifier.verify_token("test_token")

            assert result is not None
            assert result.client_id == "test_client"
            assert result.claims["email"] == "user@example.com"
            assert result.claims["sub"] == "12345"

    @pytest.mark.asyncio
    async def test_verify_token_returns_none_on_http_error(self):
        """Test that HTTP errors return None."""
        verifier = GoogleTokenVerifier()

        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("mcp_yamlfilesystem.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await verifier.verify_token("invalid_token")
            assert result is None
