"""Swagger-to-MCP Server - Main entry point.

Generates MCP tools dynamically from any OpenAPI/Swagger spec.
All configuration is done via environment variables.
"""

import os
from typing import Optional
from urllib.parse import urlencode

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from src.oauth import AUTH_URL, OAuthTokenManager
from src.token_auth import get_token_manager as get_api_token_manager
from src.tools_generator import register_tools

# Server config from env
SERVER_NAME = os.getenv("MCP_SERVER_NAME", "swagger-mcp")
SERVER_INSTRUCTIONS = os.getenv(
    "MCP_SERVER_INSTRUCTIONS",
    "MCP Server auto-generated from OpenAPI spec. Auth handled via OAuth2.",
)
TRANSPORT = os.getenv("MCP_TRANSPORT", "streamable-http")
HOST = os.getenv("MCP_HOST", "0.0.0.0")
PORT = int(os.getenv("MCP_PORT", "47321"))

# OAuth config from env
OAUTH_CLIENT_ID = os.getenv("OAUTH_CLIENT_ID", "")
OAUTH_CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET", "")
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:47321/auth/callback")
OAUTH_SCOPE = os.getenv("OAUTH_SCOPE", "openid")

# Global token manager
_token_manager: Optional[OAuthTokenManager] = None


def get_token_manager() -> OAuthTokenManager:
    """Get the global token manager instance."""
    global _token_manager
    if _token_manager is None:
        if not OAUTH_CLIENT_ID or not OAUTH_CLIENT_SECRET:
            raise RuntimeError(
                "OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET must be set."
            )
        _token_manager = OAuthTokenManager(
            client_id=OAUTH_CLIENT_ID,
            client_secret=OAUTH_CLIENT_SECRET,
            redirect_uri=OAUTH_REDIRECT_URI,
        )
    return _token_manager


# Create MCP server
mcp = FastMCP(
    SERVER_NAME,
    instructions=SERVER_INSTRUCTIONS,
    host=HOST,
    port=PORT,
)

# Register all tools from swagger spec (auto-fetches latest from remote, falls back to cache)
tool_count = register_tools(mcp)
print(f"Registered {tool_count} tools")


# ---------------------------------------------------------------------------
# OAuth routes (embedded in the MCP server via custom_route)
# ---------------------------------------------------------------------------

@mcp.custom_route("/auth", methods=["GET"])
async def auth_start(request):
    """Redirect the user to the OAuth authorization page."""
    if not AUTH_URL:
        return HTMLResponse(
            "<h1>OAuth not configured</h1>"
            "<p>Set OAUTH_AUTH_URL environment variable.</p>",
            status_code=500,
        )
    params = urlencode({
        "client_id": OAUTH_CLIENT_ID,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": OAUTH_SCOPE,
    })
    return RedirectResponse(url=f"{AUTH_URL}?{params}")


@mcp.custom_route("/auth/callback", methods=["GET"])
async def auth_callback(request):
    """Receive the OAuth callback, exchange code for tokens."""
    code = request.query_params.get("code")
    error = request.query_params.get("error")

    if error:
        desc = request.query_params.get("error_description", error)
        return HTMLResponse(
            f"<h1>Authentication Error</h1><p>{desc}</p>"
            "<p><a href='/auth'>Try again</a></p>",
            status_code=400,
        )

    if not code:
        return HTMLResponse(
            "<h1>Error</h1><p>No authorization code received.</p>"
            "<p><a href='/auth'>Try again</a></p>",
            status_code=400,
        )

    try:
        manager = get_token_manager()
        await manager.exchange_code(code)
        return HTMLResponse(
            "<h1>Authentication Successful!</h1>"
            "<p>OAuth tokens saved. The MCP server is now ready to use.</p>"
            "<p>You can close this tab.</p>"
        )
    except Exception as exc:
        return HTMLResponse(
            f"<h1>Token Exchange Error</h1><p>{exc}</p>"
            "<p><a href='/auth'>Try again</a></p>",
            status_code=500,
        )


@mcp.custom_route("/auth/status", methods=["GET"])
async def auth_status(request):
    """Return JSON indicating whether the server is authenticated."""
    try:
        manager = get_token_manager()
        return JSONResponse({"authenticated": manager.has_tokens})
    except RuntimeError:
        return JSONResponse({"authenticated": False, "error": "OAuth not configured"})


# ---------------------------------------------------------------------------
# Health / info routes
# ---------------------------------------------------------------------------

@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    """Health check endpoint for load balancers, Docker HEALTHCHECK, etc."""
    authenticated = False
    try:
        manager = get_token_manager()
        authenticated = manager.has_tokens
    except RuntimeError:
        pass

    status = "healthy" if authenticated else "degraded"
    code = 200 if authenticated else 503

    return JSONResponse(
        {
            "status": status,
            "server": SERVER_NAME,
            "tools": tool_count,
            "authenticated": authenticated,
            "transport": TRANSPORT,
        },
        status_code=code,
    )


@mcp.custom_route("/info", methods=["GET"])
async def info(request):
    """Server metadata: name, version, tool count, config."""
    from src.tools_generator import SWAGGER_URL
    return JSONResponse({
        "server": SERVER_NAME,
        "transport": TRANSPORT,
        "tools": tool_count,
        "swagger_url": SWAGGER_URL,
        "oauth_configured": bool(OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET and AUTH_URL),
    })


# ---------------------------------------------------------------------------
# API Token Management routes (unprotected for initial setup)
# ---------------------------------------------------------------------------

@mcp.custom_route("/api/tokens", methods=["GET"])
async def list_tokens(request):
    """List all active API tokens (hashed for security)."""
    try:
        token_mgr = get_api_token_manager()
        tokens = token_mgr.list_tokens()
        return JSONResponse({"tokens": tokens})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@mcp.custom_route("/api/tokens", methods=["POST"])
async def create_token(request):
    """Create a new API token for MCP access.

    Request body:
    {
        "name": "token name (optional)",
        "description": "token description (optional)"
    }
    """
    try:
        import json
        body = await request.json()
        name = body.get("name", "default")
        description = body.get("description", "")

        token_mgr = get_api_token_manager()
        token = token_mgr.create_token(name=name, description=description)

        return JSONResponse(
            {
                "token": token,
                "name": name,
                "message": "Save this token securely. You won't be able to see it again."
            },
            status_code=201
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON in request body"}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@mcp.custom_route("/api/tokens/{token_hash}", methods=["DELETE"])
async def revoke_token(request):
    """Revoke/delete an API token by its hash.

    Note: You need the full token to revoke it.
    """
    try:
        import json
        body = await request.json()
        token = body.get("token", "")

        if not token:
            return JSONResponse({"error": "Missing 'token' in request body"}, status_code=400)

        token_mgr = get_api_token_manager()
        if token_mgr.revoke_token(token):
            return JSONResponse({"message": "Token revoked successfully"})
        else:
            return JSONResponse({"error": "Token not found"}, status_code=404)
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON in request body"}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# Token auth ASGI middleware — protects /mcp when tokens exist
# ---------------------------------------------------------------------------


class TokenAuthMiddleware:
    """ASGI middleware that enforces Bearer token auth on /mcp.

    Rules:
    - If no tokens exist yet, /mcp is open (first-use setup)
    - Once at least one token is created, Bearer auth is required
    - All other routes (/auth, /health, /api/tokens, etc.) are always open
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http" and scope["path"] == "/mcp":
            token_mgr = get_api_token_manager()
            active_tokens = token_mgr.list_tokens()

            if active_tokens:
                headers = dict(scope.get("headers", []))
                auth_header = headers.get(b"authorization", b"").decode()

                if not auth_header.startswith("Bearer "):
                    response = JSONResponse(
                        {"error": "Authentication required. Pass Bearer token in Authorization header."},
                        status_code=401,
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                    await response(scope, receive, send)
                    return

                token = auth_header[7:]
                if not token_mgr.validate_token(token):
                    response = JSONResponse(
                        {"error": "Invalid or revoked token."},
                        status_code=401,
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                    await response(scope, receive, send)
                    return

        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------


def main():
    # Validate OAuth config on startup
    try:
        manager = get_token_manager()
        if manager.has_tokens:
            print("OAuth tokens loaded from disk.")
        else:
            print(f"\n  No OAuth tokens found.")
            print(f"  Open http://localhost:{PORT}/auth to authenticate\n")
    except RuntimeError as exc:
        print(f"\n  OAuth not configured: {exc}")
        print(f"  Set OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, OAUTH_AUTH_URL, OAUTH_TOKEN_URL\n")

    # Check API token manager
    try:
        api_token_mgr = get_api_token_manager()
        existing_tokens = api_token_mgr.list_tokens()
        if existing_tokens:
            print(f"API tokens available: {len(existing_tokens)} active token(s)")
        else:
            print("\n  [API Token Management]")
            print(f"  No API tokens found. Create one to secure MCP access:")
            print(f"  curl -X POST http://localhost:{PORT}/api/tokens \\")
            print(f"    -H 'Content-Type: application/json' \\")
            print('    -d \'{"name": "default", "description": "My first token"}\'')
            print(f"  Then use: Authorization: Bearer <token>\n")
    except Exception:
        pass

    _run_with_auth(mcp, TRANSPORT)


async def _run_with_auth_async(server: FastMCP):
    """Run streamable-http with TokenAuthMiddleware wrapping the ASGI app."""
    import uvicorn

    starlette_app = server.streamable_http_app()
    wrapped_app = TokenAuthMiddleware(starlette_app)

    config = uvicorn.Config(
        wrapped_app,
        host=server.settings.host,
        port=server.settings.port,
        log_level=server.settings.log_level.lower(),
    )
    uvi_server = uvicorn.Server(config)
    await uvi_server.serve()


def _run_with_auth(server: FastMCP, transport: str):
    """Run FastMCP with token auth middleware on streamable-http."""
    import anyio

    if transport == "streamable-http":
        anyio.run(lambda: _run_with_auth_async(server))
    else:
        server.run(transport=transport)


if __name__ == "__main__":
    main()
