"""
Token-based authentication for MCP server
Protects access to sensitive API endpoints
"""

import secrets
import hashlib
from typing import Optional
import json
from pathlib import Path
import os

DEFAULT_TOKEN_FILE = Path(__file__).parent.parent / "data" / ".mcp_tokens.json"

class TokenManager:
    """Manage API tokens for MCP server authentication"""

    def __init__(self, token_file: Optional[Path] = None):
        self.token_file = token_file or DEFAULT_TOKEN_FILE
        self.tokens = self._load_tokens()

    def _load_tokens(self) -> dict:
        """Load tokens from disk"""
        if self.token_file.exists():
            try:
                with open(self.token_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _save_tokens(self):
        """Save tokens to disk"""
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.token_file, 'w', encoding='utf-8') as f:
            json.dump(self.tokens, f, indent=2)

    def create_token(self, name: str = "default", description: str = "") -> str:
        """Create a new API token"""
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        self.tokens[token_hash] = {
            "name": name,
            "description": description,
            "created_at": str(__import__('datetime').datetime.now().isoformat()),
            "active": True
        }
        self._save_tokens()
        return token

    def validate_token(self, token: str) -> bool:
        """Validate if token is valid"""
        if not token:
            return False
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        return token_hash in self.tokens and self.tokens[token_hash].get("active", False)

    def revoke_token(self, token: str) -> bool:
        """Revoke a token"""
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        if token_hash in self.tokens:
            self.tokens[token_hash]["active"] = False
            self._save_tokens()
            return True
        return False

    def list_tokens(self) -> list:
        """List all active tokens (hashed for security)"""
        return [
            {
                "hash": hash_key[:8] + "...",
                "name": data.get("name"),
                "created_at": data.get("created_at"),
                "active": data.get("active", False)
            }
            for hash_key, data in self.tokens.items()
            if data.get("active", False)
        ]

    def delete_token(self, token: str) -> bool:
        """Delete a token completely"""
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        if token_hash in self.tokens:
            del self.tokens[token_hash]
            self._save_tokens()
            return True
        return False


# Global instance
_token_manager = None

def get_token_manager() -> TokenManager:
    """Get or create token manager instance"""
    global _token_manager
    if _token_manager is None:
        _token_manager = TokenManager()
    return _token_manager
