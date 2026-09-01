"""
Admin authentication.

One rule drives the design: **fail closed**. If no admin key is configured the
endpoints refuse to serve, rather than falling open. The previous guard had an
`if environment == "development": return` escape hatch, and because
docker-compose sets ENVIRONMENT=development, every staff endpoint was readable
by anyone who could reach the port — client names, phone numbers and order
totals included. An auth check that a config value can switch off is not an
auth check.

The key is a shared secret held by Presprint staff, sent either as
`X-Admin-Key` or as `Authorization: Bearer <key>`. That is proportionate for a
single-tenant back office; it is not a user system. If Presprint later needs
per-person logins and an audit trail of who changed what, this is the seam to
replace — swap the dependency, leave the routers alone.
"""
from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.core.config import settings

MIN_KEY_LENGTH = 16


def _configured_key() -> str:
    return (settings.admin_api_key or "").strip()


def admin_is_configured() -> bool:
    return len(_configured_key()) >= MIN_KEY_LENGTH


async def require_admin(
    x_admin_key: Annotated[str | None, Header(alias="X-Admin-Key")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """FastAPI dependency guarding every admin-only endpoint."""
    key = _configured_key()

    if not key:
        # Deliberately 503, not 401: nothing the caller sends can succeed, and
        # the operator needs to know why.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=("Admin access is not configured on this server. Set ADMIN_API_KEY "
                    "to a long random value and restart. Until then these endpoints "
                    "stay closed."),
        )

    if len(key) < MIN_KEY_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(f"ADMIN_API_KEY is shorter than {MIN_KEY_LENGTH} characters and is "
                    "refused as too weak to guard customer data. Generate one with "
                    "`openssl rand -hex 32`."),
        )

    presented = x_admin_key
    if not presented and authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer":
            presented = value.strip()

    if not presented:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin key required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Constant time, so a wrong key cannot be discovered character by character.
    if not secrets.compare_digest(presented, key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin key.",
            headers={"WWW-Authenticate": "Bearer"},
        )


AdminOnly = Depends(require_admin)
