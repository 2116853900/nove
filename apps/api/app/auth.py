from __future__ import annotations

import hashlib
import hmac
import secrets
from contextvars import ContextVar
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .config import settings
from .db import get_session
from .models import Workspace


DEFAULT_WORKSPACE_ID = "local"
_workspace_ctx: ContextVar[str] = ContextVar("nove_workspace_id", default=DEFAULT_WORKSPACE_ID)


def current_workspace_id() -> str:
    return _workspace_ctx.get()


def set_workspace_id(workspace_id: str) -> None:
    _workspace_ctx.set(workspace_id)


@dataclass(frozen=True)
class AuthContext:
    workspace_id: str
    auth_mode: str  # none | api_key | dev


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_api_key(provided: str) -> bool:
    expected = settings.api_key
    if not expected:
        return False
    return hmac.compare_digest(_hash_key(provided), _hash_key(expected))


def get_auth_context(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
) -> AuthContext:
    """Resolve auth for the request.

    - If API_KEY is set: require matching X-API-Key or Bearer token.
    - If development and no API_KEY: allow open access to default workspace.
    - If production and no API_KEY: refuse (fail closed).
    """
    provided = x_api_key
    if not provided and authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()

    if settings.api_key:
        if not provided or not verify_api_key(provided):
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        set_workspace_id(DEFAULT_WORKSPACE_ID)
        return AuthContext(workspace_id=DEFAULT_WORKSPACE_ID, auth_mode="api_key")

    if settings.is_production:
        raise HTTPException(
            status_code=503,
            detail="API_KEY is required in production",
        )

    _ = request
    set_workspace_id(DEFAULT_WORKSPACE_ID)
    return AuthContext(workspace_id=DEFAULT_WORKSPACE_ID, auth_mode="dev")


def get_current_workspace(
    auth: AuthContext = Depends(get_auth_context),
    session: Session = Depends(get_session),
) -> Workspace:
    workspace = session.get(Workspace, auth.workspace_id)
    if workspace is None:
        workspace = Workspace(id=auth.workspace_id, name="Local workspace")
        session.add(workspace)
        session.commit()
        session.refresh(workspace)
    return workspace


def require_workspace_id(auth: AuthContext = Depends(get_auth_context)) -> str:
    return auth.workspace_id


def new_api_key() -> str:
    return secrets.token_urlsafe(32)
