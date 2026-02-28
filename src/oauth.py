"""OAuth2 token manager.

Handles authorization code flow and automatic token refresh.
Tokens are persisted to disk so they survive server restarts.
All URLs are configurable via environment variables.
"""

import json
import os
import time
import asyncio
from pathlib import Path
from typing import Optional

import httpx

TOKEN_URL = os.getenv("OAUTH_TOKEN_URL", "")
AUTH_URL = os.getenv("OAUTH_AUTH_URL", "")
DEFAULT_TOKEN_FILE = Path(
    os.getenv("OAUTH_TOKEN_FILE", str(Path(__file__).parent.parent / "data" / ".oauth_tokens.json"))
)


class OAuthTokenManager:
    """Manages OAuth2 tokens with automatic refresh."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str = "http://localhost:47321/auth/callback",
        token_url: str = "",
        token_file: Optional[Path] = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.token_url = token_url or TOKEN_URL
        self.token_file = token_file or DEFAULT_TOKEN_FILE
        self._tokens: dict = {}
        self._obtained_at: float = 0
        self._lock = asyncio.Lock()
        self._load_tokens()

    def _load_tokens(self):
        """Load tokens from disk if available."""
        if self.token_file.exists():
            try:
                with open(self.token_file, encoding="utf-8") as f:
                    data = json.load(f)
                self._tokens = data
                self._obtained_at = data.get("obtained_at", 0)
            except (json.JSONDecodeError, OSError):
                self._tokens = {}

    def _save_tokens(self):
        """Persist tokens to disk."""
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self._tokens["obtained_at"] = self._obtained_at
        with open(self.token_file, "w", encoding="utf-8") as f:
            json.dump(self._tokens, f, indent=2)

    @property
    def has_tokens(self) -> bool:
        return bool(self._tokens.get("access_token"))

    @property
    def access_token(self) -> Optional[str]:
        return self._tokens.get("access_token")

    @property
    def refresh_token(self) -> Optional[str]:
        return self._tokens.get("refresh_token")

    def _is_expired(self) -> bool:
        """Check if access token is expired (with 5min buffer)."""
        if not self._obtained_at:
            return True
        expires_in = self._tokens.get("expires_in", 14400)
        return time.time() > (self._obtained_at + expires_in - 300)

    async def exchange_code(self, code: str) -> dict:
        """Exchange authorization code for tokens."""
        if not self.token_url:
            raise RuntimeError("OAUTH_TOKEN_URL is not configured.")
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                self.token_url,
                data={
                    "grant_type": "authorization_code",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            self._tokens = r.json()
            self._obtained_at = time.time()
            self._save_tokens()
            return self._tokens

    async def _refresh(self) -> dict:
        """Refresh the access token using the refresh token."""
        if not self.refresh_token:
            raise RuntimeError("No refresh token available. Re-authorize via /auth.")
        if not self.token_url:
            raise RuntimeError("OAUTH_TOKEN_URL is not configured.")

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                self.token_url,
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            self._tokens = r.json()
            self._obtained_at = time.time()
            self._save_tokens()
            return self._tokens

    async def get_access_token(self) -> str:
        """Get a valid access token, refreshing if needed."""
        async with self._lock:
            if self._is_expired() and self.refresh_token:
                try:
                    await self._refresh()
                except httpx.HTTPStatusError:
                    raise RuntimeError(
                        "Refresh token expired. Re-authorize via /auth."
                    )
            if not self.access_token:
                raise RuntimeError(
                    "No access token. Authorize via /auth."
                )
            return self.access_token
