from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def enabled() -> bool:
    """Turnstile gating is active only when both keys are configured."""
    return bool(settings.TURNSTILE_SITE_KEY and settings.TURNSTILE_SECRET_KEY)


def site_key() -> str:
    return settings.TURNSTILE_SITE_KEY


async def verify(token: str, ip: str = "") -> bool:
    """Validate a Turnstile token with Cloudflare.

    Fail closed: a missing token, network error, or non-success verdict all
    return False. When Turnstile is not configured, gating is off and this
    returns True so the login flow is unchanged.
    """
    if not enabled():
        return True
    if not token:
        return False
    data = {"secret": settings.TURNSTILE_SECRET_KEY, "response": token}
    if ip:
        data["remoteip"] = ip
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(_VERIFY_URL, data=data)
            resp.raise_for_status()
            return bool(resp.json().get("success"))
    except Exception:  # noqa: BLE001 - any failure means un-verified
        logger.warning("Turnstile verification request failed", exc_info=True)
        return False
