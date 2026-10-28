"""Opt in to model tracing. Called from the API startup only (never from scripts)."""
from __future__ import annotations

from app.core.config import get_settings
from app.services import model_trace


def configure_tracing() -> None:
    s = get_settings()
    secret = s.contacts_backend_service_secret
    model_trace.configure(
        s.model_trace if secret else "",
        str(s.contacts_backend_base_url).rstrip("/") + "/internal/traces",
        {"Authorization": f"Bearer {secret}"} if secret else {},
        "meeting-copilot",
    )
