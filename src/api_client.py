"""Generic async HTTP client for REST APIs.

Uses OAuthTokenManager for automatic token refresh.
Base URL is read from API_BASE_URL env var or from the swagger spec.
"""

import os
import httpx
from typing import Any, Optional

from src.oauth import OAuthTokenManager

class APIClient:
    """Async HTTP client with OAuth2 support."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        token_manager: Optional[OAuthTokenManager] = None,
    ):
        self.base_url = (base_url or os.getenv("API_BASE_URL", "")).rstrip("/")
        self.token_manager = token_manager

    def _headers(self, api_token: str) -> dict:
        return {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _resolve_token(self, api_token: Optional[str] = None) -> str:
        """Get token from explicit param or token manager."""
        if api_token:
            return api_token
        if self.token_manager:
            return await self.token_manager.get_access_token()
        raise RuntimeError(
            "No api_token provided and no OAuth token manager configured. "
            "Authorize via /auth."
        )

    async def request(
        self,
        method: str,
        path: str,
        api_token: Optional[str] = None,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
    ) -> Any:
        """Execute an HTTP request."""
        token = await self._resolve_token(api_token)
        url = f"{self.base_url}{path}"

        # Remove None values from params
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=method.upper(),
                url=url,
                headers=self._headers(token),
                params=params,
                json=json_body,
            )

            if response.status_code == 204:
                return {"status": "success", "message": "No content"}

            try:
                data = response.json()
            except Exception:
                data = {"raw_response": response.text}

            if response.status_code >= 400:
                return {
                    "error": True,
                    "status_code": response.status_code,
                    "detail": data,
                }

            return data

    async def get(self, path: str, api_token: Optional[str] = None, params: Optional[dict] = None) -> Any:
        return await self.request("GET", path, api_token=api_token, params=params)

    async def post(self, path: str, api_token: Optional[str] = None, params: Optional[dict] = None, json_body: Optional[dict] = None) -> Any:
        return await self.request("POST", path, api_token=api_token, params=params, json_body=json_body)

    async def put(self, path: str, api_token: Optional[str] = None, params: Optional[dict] = None, json_body: Optional[dict] = None) -> Any:
        return await self.request("PUT", path, api_token=api_token, params=params, json_body=json_body)

    async def delete(self, path: str, api_token: Optional[str] = None, params: Optional[dict] = None) -> Any:
        return await self.request("DELETE", path, api_token=api_token, params=params)
