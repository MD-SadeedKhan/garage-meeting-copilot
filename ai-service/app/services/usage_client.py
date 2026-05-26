"""
AI-usage metering client.

Posts per-call token / audio usage to contacts-backend's central ledger
(`POST /internal/usage`) so EarnGPT Live (this service) shows up in the
same billing/metering view as the in-process products.

Best-effort by design: every call is fire-and-forget and swallows all
errors. Metering must NEVER add latency to — or break — the live path.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Short timeout — we never want a slow ledger to stall the live session.
_USAGE_TIMEOUT_SECONDS = 3.0


async def record_usage(
    *,
    user_id: str,
    product: str,
    provider: str,
    model: str,
    kind: str,
    metrics: dict[str, Any],
    ref_id: str | None = None,
) -> None:
    """POST one usage event to contacts-backend. Never raises.

    Args mirror the backend's ingest contract:
      product: "earngpt_live"
      provider: "openai" | "deepgram"
      kind: "chat" | "embedding" | "stt"
      metrics: {promptTokens, completionTokens} | {totalTokens} | {audioSeconds}
    """
    settings = get_settings()
    secret = settings.contacts_backend_service_secret
    if not secret:
        # No secret configured — metering is disabled, not an error.
        logger.debug("usage_metering_skipped_no_secret", product=product)
        return
    if not user_id:
        logger.debug("usage_metering_skipped_no_user", product=product)
        return

    base_url = str(settings.contacts_backend_base_url).rstrip("/")
    payload: dict[str, Any] = {
        "userId": user_id,
        "product": product,
        "provider": provider,
        "model": model,
        "kind": kind,
        "metrics": metrics,
    }
    if ref_id:
        payload["refId"] = ref_id

    try:
        async with httpx.AsyncClient(timeout=_USAGE_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{base_url}/internal/usage",
                headers={"Authorization": f"Bearer {secret}"},
                json=payload,
            )
            if resp.status_code >= 400:
                logger.warning(
                    "usage_metering_rejected",
                    status=resp.status_code,
                    body=resp.text[:200],
                    product=product,
                    kind=kind,
                )
    except Exception as e:  # noqa: BLE001 — best-effort, never propagate
        logger.warning(
            "usage_metering_failed",
            error=str(e),
            product=product,
            kind=kind,
        )
