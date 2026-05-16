"""
Garage Meeting Copilot — JWT Integration Middleware
Validates contacts-backend issued JWTs and injects user context.
"""
from __future__ import annotations

from typing import Any

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

security = HTTPBearer(auto_error=False)


class GarageAuthContext:
    """Decoded Garage JWT context injected into request state."""

    __slots__ = (
        "user_id",
        "organization_id",
        "workspace_id",
        "email",
        "roles",
        "raw_token",
    )

    def __init__(
        self,
        user_id: str,
        organization_id: str,
        workspace_id: str | None,
        email: str,
        roles: list[str],
        raw_token: str,
    ) -> None:
        self.user_id = user_id
        self.organization_id = organization_id
        self.workspace_id = workspace_id
        self.email = email
        self.roles = roles
        self.raw_token = raw_token

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles or "org:admin" in self.roles


class GarageJWTValidator:
    """
    Validates JWTs issued by the contacts-backend authentication system.
    HS256 with no audience claim; claims: {userId, orgId, role?, name?, email?}.
    """

    def __init__(self) -> None:
        self._settings = get_settings()

    def decode_token(self, token: str) -> dict[str, Any]:
        try:
            payload = jwt.decode(
                token,
                self._settings.garage_jwt_secret,
                algorithms=["HS256"],
                options={"verify_exp": True, "verify_aud": False},
            )
            return payload
        except JWTError as e:
            logger.warning("jwt_decode_failed", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def extract_context(self, token: str) -> GarageAuthContext:
        payload = self.decode_token(token)

        user_id = payload.get("userId")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing userId claim",
            )

        org_id = payload.get("orgId", "")
        role = payload.get("role")
        roles = [role] if role else []

        return GarageAuthContext(
            user_id=user_id,
            organization_id=org_id,
            workspace_id=None,
            email=payload.get("email", ""),
            roles=roles,
            raw_token=token,
        )


_validator = GarageJWTValidator()


async def require_garage_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> GarageAuthContext:
    """
    FastAPI dependency — validates Garage JWT and returns auth context.
    Injects GarageAuthContext into request.state for downstream use.
    """
    if credentials is None:
        # Try extracting from request directly for WebSocket compatibility
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = auth_header.split(" ", 1)[1]
    else:
        token = credentials.credentials

    context = _validator.extract_context(token)
    request.state.auth = context

    logger.debug(
        "garage_auth_validated",
        user_id=context.user_id,
        org_id=context.organization_id,
    )

    return context


async def extract_ws_token(token: str) -> GarageAuthContext:
    """
    Validate JWT for WebSocket connections (passed as query param).
    """
    return _validator.extract_context(token)


class GarageAPIClient:
    """
    HTTP client for fetching meeting context from the contacts-backend.
    Uses the validated user JWT for authenticated requests.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._base_url = str(self._settings.contacts_backend_base_url).rstrip("/")

    async def get_meeting_context(
        self,
        room_name: str,
        token: str,
    ) -> dict[str, Any]:
        """Fetch meeting context (meeting/organization/host) from contacts-backend."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._base_url}/api/v1/meeting-context/{room_name}",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_workspace_context(
        self,
        workspace_id: str,
        token: str,
    ) -> dict[str, Any]:
        """Deprecated no-op — workspace context no longer separately fetched."""
        return {}

    async def get_user_profile(
        self,
        user_id: str,
        token: str,
    ) -> dict[str, Any]:
        """Deprecated no-op — user profile no longer separately fetched."""
        return {}
