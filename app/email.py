from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)


def send_otp_email(email: str, code: str) -> bool:
    if not settings.RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not configured; dev-mode OTP for %s: %s", email, code)
        return False
    try:
        import resend

        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send(
            {
                "from": settings.RESEND_FROM,
                "to": [email],
                "subject": "Your WFSF sign-in code",
                "html": _render_html(code),
                "text": _render_text(code),
            }
        )
        return True
    except Exception as exc:  # noqa: BLE001 - external email failure isolated
        logger.exception("Resend send failed: %s", exc)
        return False


def _render_html(code: str) -> str:
    return f"""
    <div style="font-family: 'Inter','Helvetica Neue',Helvetica,Arial,sans-serif; max-width: 480px; margin: 0 auto; padding: 32px 24px;">
      <p style="font-size:14px; letter-spacing:0.06em; text-transform:uppercase; color:#7a7a7a; margin:0 0 16px">WFSF · AI Engineer World's Fair 2026</p>
      <h1 style="font-size:22px; margin:0 0 12px; color:#111">Your sign-in code</h1>
      <p style="font-size:14px; color:#333">Use this 6-digit code to sign in. It expires in {settings.OTP_TTL_MINUTES} minutes and can only be used once.</p>
      <p style="font-family:'Menlo','SF Mono',monospace; font-size:34px; letter-spacing:0.18em; background:#0f1a2b; color:#f7fff5; padding:18px 24px; border-radius:10px; text-align:center; margin:24px 0;">{code}</p>
      <p style="font-size:12px; color:#7a7a7a">If you didn't request this code, you can ignore this email.</p>
    </div>
    """


def _render_text(code: str) -> str:
    return f"Your WFSF sign-in code is: {code}\nIt expires in {settings.OTP_TTL_MINUTES} minutes."
