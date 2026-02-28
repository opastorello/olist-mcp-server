import json
import os
import re
import inspect
from pathlib import Path
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

SWAGGER_URL = os.getenv("SWAGGER_URL", "")
DEFAULT_CACHE_PATH = Path(__file__).parent.parent / "swagger.json"


def _snake_case(name: str) -> str:
    """Convert operationId to snake_case tool name."""
    name = re.sub(r'Action$', '', name)
    s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name)
    result = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
    result = re.sub(r'_+', '_', result)
    return result


def _extract_params(operation: dict, spec: dict) -> list:
    """Extract parameters from an operation, resolving $ref if needed."""
    params = []
    for p in operation.get("parameters", []):
        if "$ref" in p:
            ref_path = p["$ref"].replace("#/", "").split("/")
            resolved = spec
            for part in ref_path:
                resolved = resolved[part]
            p = resolved
        params.append(p)
    return params


def _resolve_ref(ref: str, spec: dict) -> dict:
    """Resolve a $ref pointer in the spec."""
    path = ref.replace("#/", "").split("/")
    resolved = spec
    for part in path:
        resolved = resolved.get(part, {})
    return resolved


def _get_body_schema(operation: dict, spec: dict) -> dict:
    """Extract full request body schema (may be object or array)."""
    body = operation.get("requestBody", {})
    if not body:
        return {}
    content = body.get("content", {})
    json_content = content.get("application/json", {})
    schema = json_content.get("schema", {})

    if "$ref" in schema:
        schema = _resolve_ref(schema["$ref"], spec)

    return schema


TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _build_tool_handler(
    method: str,
    path_template: str,
    path_params: list,
    query_params: list,
    has_body: bool,
):
    """Build a tool handler function with explicit parameter signature."""

    # Collect all parameters for the function signature
    params = []

    for pp in path_params:
        params.append(
            inspect.Parameter(pp, inspect.Parameter.KEYWORD_ONLY, annotation=str)
        )

    for qp in query_params:
        py_type = TYPE_MAP.get(qp["type"], str)
        default = inspect.Parameter.empty if qp["required"] else None
        params.append(
            inspect.Parameter(
                qp["name"],
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=Optional[py_type] if not qp["required"] else py_type,
            )
        )

    if has_body:
        params.append(
            inspect.Parameter(
                "body",
                inspect.Parameter.KEYWORD_ONLY,
                default=None,
                annotation=Optional[dict],
            )
        )

    async def handler(**kwargs) -> str:
        from src.api_client import APIClient
        from src.server import get_token_manager

        client = APIClient(token_manager=get_token_manager())

        # Build path with path params
        path = path_template
        for pp in path_params:
            value = kwargs.get(pp)
            if value is not None:
                path = path.replace(f"{{{pp}}}", str(value))

        # Build query params dict
        qparams = {}
        for qp in query_params:
            val = kwargs.get(qp["name"])
            if val is not None:
                qparams[qp["name"]] = val

        # Build body
        json_body = kwargs.get("body") if has_body else None

        result = await client.request(
            method=method,
            path=path,
            params=qparams if qparams else None,
            json_body=json_body,
        )
        return json.dumps(result, ensure_ascii=False)

    # Set explicit signature so FastMCP sees named params, not **kwargs
    sig = inspect.Signature(params, return_annotation=str)
    handler.__signature__ = sig

    return handler


def fetch_swagger(cache_path: Path = DEFAULT_CACHE_PATH) -> dict:
    """Fetch the latest swagger spec from the remote URL.

    Falls back to the local cached file if the fetch fails.
    Saves the fetched spec to disk as cache for next time.
    """
    # Try fetching from remote
    if SWAGGER_URL:
        try:
            resp = httpx.get(SWAGGER_URL, timeout=15.0, follow_redirects=True)
            resp.raise_for_status()
            spec = resp.json()
            # Save as local cache
            cache_path.write_text(
                json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"Swagger fetched from {SWAGGER_URL}")
            return spec
        except Exception as exc:
            print(f"Could not fetch swagger from {SWAGGER_URL}: {exc}")

    # Fallback to local cache
    if cache_path.exists():
        print(f"Using cached swagger from {cache_path}")
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)

    raise RuntimeError(
        f"No swagger spec available. Remote fetch failed and no cache at {cache_path}"
    )


def register_tools(mcp: FastMCP, swagger_path: str | None = None) -> int:
    """Fetch (or load) swagger spec and register all API endpoints as MCP tools.

    If swagger_path is provided, it is used as the cache location.
    Returns the number of tools registered.
    """
    cache = Path(swagger_path) if swagger_path else DEFAULT_CACHE_PATH
    spec = fetch_swagger(cache_path=cache)

    # Extract base URL from spec and set as env var if not already set
    if not os.getenv("API_BASE_URL"):
        servers = spec.get("servers", [])
        if servers:
            base_url = servers[0].get("url", "")
            if base_url:
                os.environ["API_BASE_URL"] = base_url
                print(f"API base URL: {base_url}")

    count = 0
    for path, methods in spec.get("paths", {}).items():
        for method, operation in methods.items():
            if method.lower() not in ("get", "post", "put", "delete", "patch"):
                continue

            operation_id = operation.get("operationId", "")
            if not operation_id:
                operation_id = f"{method}_{path.replace('/', '_').replace('{', '').replace('}', '')}"

            tool_name = _snake_case(operation_id)
            tags = operation.get("tags", ["General"])
            summary = operation.get("summary", f"{method.upper()} {path}")
            description = f"[{', '.join(tags)}] {summary}\n\nEndpoint: {method.upper()} {path}"

            # Extract path parameters
            path_params = re.findall(r'\{(\w+)\}', path)

            # Extract query parameters
            query_params = []
            for p in _extract_params(operation, spec):
                if p.get("in") == "query":
                    query_params.append({
                        "name": p.get("name", ""),
                        "description": p.get("description", ""),
                        "required": p.get("required", False),
                        "type": p.get("schema", {}).get("type", "string"),
                        "enum": p.get("schema", {}).get("enum"),
                        "default": p.get("schema", {}).get("default"),
                    })

            # Extract body schema
            body_schema = {}
            has_body = False
            if method.lower() in ("post", "put", "patch"):
                body_schema = _get_body_schema(operation, spec)
                has_body = bool(body_schema)

            # Build description with parameter info
            if path_params:
                description += "\n\nPath parameters:"
                for pp in path_params:
                    description += f"\n- {pp} (required)"

            if query_params:
                description += "\n\nQuery parameters:"
                for qp in query_params:
                    req = " (required)" if qp["required"] else " (optional)"
                    desc_text = qp["description"] or ""
                    if qp["enum"]:
                        desc_text += f" Values: {qp['enum']}"
                    if qp["default"] is not None:
                        desc_text += f" Default: {qp['default']}"
                    description += f"\n- {qp['name']}{req}: {desc_text}"

            if has_body:
                schema_type = body_schema.get("type", "object")
                if schema_type == "array":
                    items = body_schema.get("items", {})
                    if "$ref" in items:
                        items = _resolve_ref(items["$ref"], spec)
                    description += "\n\nRequest body (JSON) - pass as 'body' parameter."
                    description += f"\n- body: array of objects. Item schema type: {items.get('type', 'object')}"
                    props = items.get("properties", {})
                    for prop_name, prop_schema in props.items():
                        if "$ref" in prop_schema:
                            prop_schema = _resolve_ref(prop_schema["$ref"], spec)
                        prop_type = prop_schema.get("type", "any")
                        prop_desc = prop_schema.get("description", "")
                        description += f"\n  - {prop_name} ({prop_type}): {prop_desc}"
                else:
                    body_props = body_schema.get("properties", {})
                    description += "\n\nRequest body (JSON) - pass as 'body' parameter (dict)."
                    for prop_name, prop_schema in body_props.items():
                        if "$ref" in prop_schema:
                            prop_schema = _resolve_ref(prop_schema["$ref"], spec)
                        prop_type = prop_schema.get("type", "any")
                        prop_desc = prop_schema.get("description", "")
                        description += f"\n- {prop_name} ({prop_type}): {prop_desc}"

            # Build handler with explicit signature
            handler = _build_tool_handler(
                method=method.upper(),
                path_template=path,
                path_params=path_params,
                query_params=query_params,
                has_body=has_body,
            )
            handler.__name__ = tool_name
            handler.__doc__ = description

            mcp.tool(name=tool_name, description=description)(handler)
            count += 1

    return count
