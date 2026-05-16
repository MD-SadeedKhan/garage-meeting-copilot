"""
Garage Meeting Copilot — JWT Integration Middleware
Validates Garage-issued JWTs and injects user context.
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
    Validates JWTs issued by the Garage authentication system.
    Supports both local secret validation and Garage JWKS endpoint.
    """

    def __init__(self) -> None:
        self._settings = get_settings()

    def decode_token(self, token: str) -> dict[str, Any]:
        try:
            payload = jwt.decode(
                token,
                self._settings.garage_jwt_secret,
                algorithms=[self._settings.garage_jwt_algorithm],
                audience=self._settings.garage_jwt_audience,
                options={"verify_exp": True},
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

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing subject claim",
            )

        return GarageAuthContext(
            user_id=user_id,
            organization_id=payload.get("org") or payload.get("org_id", ""),
            workspace_id=payload.get("workspace") or payload.get("workspace_id"),
            email=payload.get("email", ""),
            roles=payload.get("roles", []),
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
    HTTP client for fetching context from Garage ecosystem APIs.
    Uses the validated user JWT for authenticated requests.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._base_url = str(self._settings.garage_api_base_url).rstrip("/")

    async def get_meeting_context(
        self,
        meeting_id: str,
        token: str,
    ) -> dict[str, Any]:
        """Fetch meeting metadata from Garage API."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._base_url}/api/v1/meetings/{meeting_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_workspace_context(
        self,
        workspace_id: str,
        token: str,
    ) -> dict[str, Any]:
        """Fetch workspace metadata from Garage API."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._base_url}/api/v1/workspaces/{workspace_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_user_profile(
        self,
        user_id: str,
        token: str,
    ) -> dict[str, Any]:
        """Fetch user profile from Garage API."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._base_url}/api/v1/users/{user_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return resp.json()
