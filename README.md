# Olist ERP MCP Server

Servidor MCP para a **API Olist ERP (Tiny ERP) v3** com **168 tools** geradas automaticamente do Swagger da API.

Compativel com qualquer cliente MCP — **Claude Code**, **Claude Desktop**, **n8n**, **Cursor**, etc.

## O que faz

Conecta qualquer agente de IA ao Olist ERP. As 168 tools cobrem todas as operacoes da API:

| Categoria | Tools | Operacoes |
|---|---|---|
| Produtos | 24 | CRUD, estoque, precos, kits, anexos |
| Pedidos de Venda | 14 | CRUD, notas, etiquetas, rastreio |
| Contatos | 14 | CRUD, tipos, busca |
| Contas a Pagar | 14 | CRUD, baixa, estorno |
| Contas a Receber | 14 | CRUD, baixa, estorno, boletos |
| Notas Fiscais (NFe/NFCe) | 18 | Emissao, consulta, XML, cancelamento |
| PDV | 10 | Vendas, sessoes, caixa |
| CRM | 8 | Oportunidades, funil |
| Contratos | 6 | CRUD, parcelas |
| Ordem de Servico | 6 | CRUD |
| Expedicao | 8 | Volumes, objetos, etiquetas |
| Catalogo | 16 | Categorias, marcas, depositos, vendedores |
| Configuracoes | 16 | Empresa, formas pgto, parcelas |

## Quick Start

### 1. Configure o `.env`

```bash
cp .env.example .env
```

Preencha com suas credenciais Olist:

```env
MCP_SERVER_NAME=olist-erp
SWAGGER_URL=https://erp.tiny.com.br/public-api/v3/swagger/swagger.json

OAUTH_CLIENT_ID=seu-client-id
OAUTH_CLIENT_SECRET=seu-client-secret
OAUTH_AUTH_URL=https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/auth
OAUTH_TOKEN_URL=https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/token
OAUTH_REDIRECT_URI=http://localhost:47321/auth/callback
OAUTH_SCOPE=openid
```

> Para obter `client_id` e `client_secret`, crie uma aplicacao no painel de integracoes da sua conta Olist ERP (Tiny).

### 2. Suba o server

```bash
# Docker (recomendado)
docker compose up -d

# Ou local
pip install -r requirements.txt
python -m src.server
```

### 3. Autentique com a Olist

Abra `http://localhost:47321/auth` no browser e autorize a aplicacao na conta Olist.

### 4. Crie um token de acesso

```bash
curl -X POST http://localhost:47321/api/tokens \
  -H 'Content-Type: application/json' \
  -d '{"name": "meu-token"}'
```

Guarde o token retornado — sera necessario para acessar o endpoint `/mcp`.

### 5. Conecte seu agente

Configure o MCP client apontando para `http://localhost:47321/mcp` com o header `Authorization: Bearer SEU_TOKEN`.

## Configuracao

| Variavel | Default | Descricao |
|---|---|---|
| **MCP Server** | | |
| `MCP_SERVER_NAME` | `swagger-mcp` | Nome do server MCP |
| `MCP_SERVER_INSTRUCTIONS` | (auto) | Instrucoes do server para o LLM |
| `MCP_TRANSPORT` | `streamable-http` | Transporte: `streamable-http`, `sse` ou `stdio` |
| `MCP_HOST` | `0.0.0.0` | Host do servidor |
| `MCP_PORT` | `47321` | Porta do servidor |
| **Swagger** | | |
| `SWAGGER_URL` | — | URL do swagger spec (fetched no startup, cached localmente) |
| **API** | | |
| `API_BASE_URL` | (auto do spec) | Base URL da API (auto-detectado do `servers[0].url` do swagger) |
| **OAuth2** | | |
| `OAUTH_CLIENT_ID` | — | Client ID (obrigatorio) |
| `OAUTH_CLIENT_SECRET` | — | Client Secret (obrigatorio) |
| `OAUTH_AUTH_URL` | — | URL de autorizacao OAuth |
| `OAUTH_TOKEN_URL` | — | URL de troca de tokens |
| `OAUTH_REDIRECT_URI` | `http://localhost:47321/auth/callback` | Redirect URI |
| `OAUTH_SCOPE` | `openid` | Scopes OAuth |
| `OAUTH_TOKEN_FILE` | `data/.oauth_tokens.json` | Caminho para persistir tokens OAuth |
| **API Token** | | |
| `MCP_TOKEN_FILE` | `data/.mcp_tokens.json` | Caminho para persistir tokens de acesso |

## Autenticacao OAuth2

O servidor embute o fluxo OAuth2 completo com a Olist via rotas HTTP.

### Fluxo

1. **Suba o servidor** — funciona mesmo sem tokens
2. **Abra `/auth` no browser** — redireciona para login da Olist
3. **Autorize a aplicacao** — redireciona de volta para `/auth/callback`
4. **Tokens salvos** — troca o code por tokens e salva em `data/.oauth_tokens.json`
5. **Pronto** — todas as 168 tools funcionam

Tokens sao renovados automaticamente via refresh token. Se expirar, abra `/auth` novamente.

## Seguranca — Token de Acesso

O endpoint `/mcp` e protegido por **Bearer token**. Ao criar o primeiro token, a autenticacao e ativada automaticamente — qualquer request sem token valido recebe `401 Unauthorized`.

Rotas publicas (sem token): `/auth`, `/auth/callback`, `/auth/status`, `/health`, `/info`, `/api/tokens`.

### Criar token

```bash
curl -X POST http://localhost:47321/api/tokens \
  -H 'Content-Type: application/json' \
  -d '{"name": "meu-token", "description": "Token para meus scripts"}'
```

Resposta:
```json
{
  "token": "dKx8vZ-pQ_H2mN4r8tL9...",
  "name": "meu-token",
  "message": "Save this token securely. You won't be able to see it again."
}
```

### Usar o token

```bash
curl -X POST http://localhost:47321/mcp \
  -H 'Authorization: Bearer dKx8vZ-pQ_H2mN4r8tL9...' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{...}}'
```

### Listar tokens

```bash
curl http://localhost:47321/api/tokens
```

### Revogar token

```bash
curl -X DELETE http://localhost:47321/api/tokens/dummy \
  -H 'Content-Type: application/json' \
  -d '{"token": "dKx8vZ-pQ_H2mN4r8tL9..."}'
```

> Tokens sao salvos com hash SHA-256. Se perder o token, crie um novo.

## Rotas HTTP

| Rota | Descricao |
|---|---|
| `GET /auth` | Redireciona para login OAuth da Olist |
| `GET /auth/callback` | Recebe o code e troca por tokens |
| `GET /auth/status` | Retorna `{"authenticated": true/false}` |
| `GET /api/tokens` | Lista tokens ativos |
| `POST /api/tokens` | Cria novo token |
| `DELETE /api/tokens/{hash}` | Revoga token |
| `GET /health` | Health check (200 healthy / 503 degraded) |
| `GET /info` | Metadata: nome, transport, tools, swagger_url |
| `POST /mcp` | Endpoint MCP — **requer Bearer token** |

## Integracao

### Claude Desktop

**1. Configure o MCP server** em `claude_desktop_config.json` (Settings > Developer > Edit Config):

```json
{
  "mcpServers": {
    "olist-erp": {
      "url": "http://localhost:47321/mcp",
      "headers": {
        "Authorization": "Bearer SEU_TOKEN_AQUI"
      }
    }
  }
}
```

**2. Adicione o Agent Prompt** — copie o conteudo de [`agents/olist-erp.md`](agents/olist-erp.md) como **Project Instructions** no Claude Desktop.

Isso ensina o Claude as quirks da API Olist (validacao de EAN, workflows de NF, regras do ERP brasileiro). Sem o agent prompt, o Claude vai errar frequentemente.

### Claude Code

```json
{
  "mcpServers": {
    "olist-erp": {
      "url": "http://localhost:47321/mcp",
      "headers": {
        "Authorization": "Bearer SEU_TOKEN_AQUI"
      }
    }
  }
}
```

### n8n

1. Suba o container com `docker compose up -d`
2. Autentique via `http://localhost:47321/auth`
3. Crie um token: `curl -X POST http://localhost:47321/api/tokens -H 'Content-Type: application/json' -d '{"name":"n8n"}'`
4. No n8n, adicione um MCP Client node apontando para `http://host.docker.internal:47321/mcp` com header `Authorization: Bearer SEU_TOKEN`

### stdio (sem Docker)

```json
{
  "mcpServers": {
    "olist-erp": {
      "command": "python",
      "args": ["-m", "src.server"],
      "cwd": "/caminho/para/olist-mcp-server"
    }
  }
}
```

## Docker

### docker-compose.yml

```yaml
services:
  olist-mcp:
    build: .
    ports:
      - "47321:47321"
    env_file:
      - .env
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

### Imagem do GHCR

```bash
docker pull ghcr.io/opastorello/olist-mcp-server:1.0.0
```

### Health check

```bash
curl http://localhost:47321/health
# {"status":"healthy","server":"olist-erp","tools":168,"authenticated":true,"transport":"streamable-http"}
```

## Arquitetura

```
src/
├── server.py           # Entry point - FastMCP + rotas OAuth/health + auth middleware
├── api_client.py       # Cliente HTTP async generico
├── tools_generator.py  # Gera tools dinamicamente do swagger + auto-fetch
├── oauth.py            # OAuth2 token manager (exchange, refresh, persistencia)
├── token_auth.py       # API token manager (SHA-256 hash, CRUD, validacao)
├── __main__.py         # python -m src
└── __init__.py

agents/
└── olist-erp.md        # Agent prompt para Claude Desktop (168 tools documentadas)
```

O swagger e buscado da `SWAGGER_URL` no startup e cacheado localmente. Se a Olist adicionar endpoints novos, basta reiniciar o server — novas tools aparecem automaticamente.

## Pre-requisitos

- Python 3.12+
- Docker (opcional, recomendado)
- Credenciais OAuth2 da Olist (crie no painel de integracoes da sua conta Olist ERP)

## Licenca

MIT
