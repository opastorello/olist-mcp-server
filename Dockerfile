FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY swagger.json .
COPY src/ ./src/
RUN mkdir -p /app/data

EXPOSE 47321

# MCP Server
ENV MCP_SERVER_NAME="swagger-mcp"
ENV MCP_TRANSPORT="streamable-http"
ENV MCP_HOST="0.0.0.0"
ENV MCP_PORT="47321"

# Swagger / OpenAPI
ENV SWAGGER_URL=""

# API (optional — auto-detected from spec)
ENV API_BASE_URL=""

# OAuth2
ENV OAUTH_CLIENT_ID=""
ENV OAUTH_CLIENT_SECRET=""
ENV OAUTH_REDIRECT_URI="http://localhost:47321/auth/callback"
ENV OAUTH_AUTH_URL=""
ENV OAUTH_TOKEN_URL=""
ENV OAUTH_SCOPE="openid"

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import httpx; httpx.get('http://localhost:47321/health', timeout=5.0)" || exit 1

CMD ["python", "-m", "src.server"]
