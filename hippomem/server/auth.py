"""
Daemon authentication.

Tokens are optional in local-dev (nothing configured). Once any token is
configured, API routes require Bearer auth.

Environment:
  HIPPOMEM_API_TOKEN   — single admin token (namespace=*, can write config / delete)
  HIPPOMEM_TOKENS      — comma list of name:token:ns=<prefix>[:admin]
                         ns=* allows every user_id; otherwise user_id must equal
                         the prefix or start with ``{prefix}:``.
"""
from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class AuthContext:
    name: str
    namespace: str
    is_admin: bool

    def allows_user(self, user_id: str) -> bool:
        if self.namespace == "*":
            return True
        return user_id == self.namespace or user_id.startswith(f"{self.namespace}:")


def tokens_configured() -> bool:
    return bool(os.environ.get("HIPPOMEM_API_TOKEN") or os.environ.get("HIPPOMEM_TOKENS"))


def _parse_tokens() -> list[tuple[str, str, str, bool]]:
    """Return list of (name, token, namespace, is_admin)."""
    out: list[tuple[str, str, str, bool]] = []
    simple = os.environ.get("HIPPOMEM_API_TOKEN", "").strip()
    if simple:
        out.append(("default", simple, "*", True))
    raw = os.environ.get("HIPPOMEM_TOKENS", "").strip()
    if not raw:
        return out
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split(":")
        if len(bits) < 2:
            continue
        name, token = bits[0], bits[1]
        namespace = "*"
        is_admin = False
        for extra in bits[2:]:
            if extra.startswith("ns="):
                namespace = extra[3:] or "*"
            elif extra == "admin":
                is_admin = True
        out.append((name, token, namespace, is_admin))
    return out


def resolve_bearer(authorization: Optional[str]) -> Optional[AuthContext]:
    configured = _parse_tokens()
    if not configured:
        return AuthContext(name="anonymous", namespace="*", is_admin=True)

    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    offered = authorization[7:].strip()
    if not offered:
        return None
    for name, token, namespace, is_admin in configured:
        if hmac.compare_digest(offered, token):
            return AuthContext(name=name, namespace=namespace, is_admin=is_admin)
    return None


def context_from_request(request: Request) -> AuthContext:
    ctx = resolve_bearer(request.headers.get("authorization"))
    if ctx is None:
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token.")
    return ctx


def require_user(ctx: AuthContext, user_id: str) -> None:
    if not ctx.allows_user(user_id):
        raise HTTPException(status_code=403, detail="Token is not scoped to this user.")


def require_admin(ctx: AuthContext) -> None:
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="Admin token required.")


# Path prefixes that stay public even when tokens are configured.
PUBLIC_PREFIXES = frozenset({"health", "assets"})
