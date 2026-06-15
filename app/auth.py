from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Request

from app.config import settings
from app.db import db, tx

logger = logging.getLogger(__name__)


@dataclass
class CurrentUser:
    id: int
    email: str
    role: str
    status: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _hash_code(code: str, email: str) -> str:
    salt = settings.SESSION_SECRET.encode()
    return hmac.new(salt, f"{email.lower()}|{code}".encode(), hashlib.sha256).hexdigest()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _rate_limited(conn, bucket: str, key: str, max_count: int, window: timedelta) -> bool:
    cutoff = (_now_utc() - window).isoformat(sep=" ", timespec="seconds")
    conn.execute("DELETE FROM rate_limit WHERE created_at < ?", (cutoff,))
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM rate_limit WHERE bucket = ? AND key = ? AND created_at >= ?",
        (bucket, key, cutoff),
    ).fetchone()
    if row["c"] >= max_count:
        return True
    conn.execute("INSERT INTO rate_limit(bucket, key) VALUES(?, ?)", (bucket, key))
    return False


def request_otp(email: str, ip: str = "") -> tuple[bool, str, str | None]:
    """Returns (ok, message, dev_code_or_none). dev code is only returned for log/dev use."""
    email = normalize_email(email)
    if not email or "@" not in email:
        return False, "Enter a valid email address.", None

    with tx() as conn:
        if _rate_limited(conn, "otp_req_email", email, settings.OTP_MAX_PER_HOUR, timedelta(hours=1)):
            return False, "Too many requests. Try again later.", None
        if ip and _rate_limited(conn, "otp_req_ip", ip, settings.OTP_MAX_PER_HOUR * 3, timedelta(hours=1)):
            return False, "Too many requests from your network. Try again later.", None

        row = conn.execute("SELECT id, status FROM users WHERE email = ?", (email,)).fetchone()
        if row and row["status"] == "disabled":
            return False, "This account has been disabled. Contact an organizer.", None

        code = generate_otp()
        code_hash = _hash_code(code, email)
        expires_at = (_now_utc() + timedelta(minutes=settings.OTP_TTL_MINUTES)).isoformat(sep=" ", timespec="seconds")
        conn.execute(
            "UPDATE otp_codes SET consumed_at = datetime('now') WHERE email = ? AND consumed_at IS NULL",
            (email,),
        )
        conn.execute(
            "INSERT INTO otp_codes(email, code_hash, expires_at) VALUES(?, ?, ?)",
            (email, code_hash, expires_at),
        )

    from app.email import send_otp_email  # local import to avoid circulars

    delivered = send_otp_email(email, code)
    if not delivered and not settings.DEV_OTP_LOG:
        return False, "Could not send the email. Try again.", None
    if settings.DEV_OTP_LOG:
        logger.warning("DEV OTP for %s: %s", email, code)
    return True, "Code sent. Check your email.", (code if settings.DEV_OTP_LOG else None)


def verify_otp(email: str, code: str, request: Request | None = None) -> tuple[bool, str, CurrentUser | None, str | None]:
    """Verifies the OTP. On success returns (True, msg, user, session_token)."""
    email = normalize_email(email)
    code = (code or "").strip()
    if not email or not code:
        return False, "Enter both email and code.", None, None

    target_hash = _hash_code(code, email)
    with tx() as conn:
        row = conn.execute(
            "SELECT id, code_hash, expires_at, consumed_at, bad_attempts "
            "FROM otp_codes WHERE email = ? AND consumed_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (email,),
        ).fetchone()
        if not row:
            return False, "No active code. Request a new one.", None, None
        if row["bad_attempts"] >= settings.OTP_MAX_BAD_ATTEMPTS:
            conn.execute("UPDATE otp_codes SET consumed_at = datetime('now') WHERE id = ?", (row["id"],))
            return False, "Too many bad attempts. Request a new code.", None, None
        if row["expires_at"] < _now_utc().isoformat(sep=" ", timespec="seconds"):
            return False, "Code expired. Request a new one.", None, None
        if not hmac.compare_digest(row["code_hash"], target_hash):
            conn.execute("UPDATE otp_codes SET bad_attempts = bad_attempts + 1 WHERE id = ?", (row["id"],))
            return False, "Wrong code.", None, None

        conn.execute("UPDATE otp_codes SET consumed_at = datetime('now') WHERE id = ?", (row["id"],))

        user_row = conn.execute("SELECT id, email, role, status FROM users WHERE email = ?", (email,)).fetchone()
        if user_row is None:
            role = "admin" if email in settings.admin_email_set() else "user"
            cur = conn.execute(
                "INSERT INTO users(email, role, status) VALUES(?, ?, 'active') RETURNING id, email, role, status",
                (email, role),
            )
            user_row = cur.fetchone()
        if user_row["status"] == "disabled":
            return False, "This account has been disabled.", None, None
        conn.execute("UPDATE users SET last_login_at = datetime('now') WHERE id = ?", (user_row["id"],))

        token = secrets.token_urlsafe(32)
        expires = (_now_utc() + timedelta(days=settings.SESSION_TTL_DAYS)).isoformat(sep=" ", timespec="seconds")
        ua = (request.headers.get("user-agent", "") if request else "")[:300]
        ip = (request.client.host if request and request.client else "")[:64]
        conn.execute(
            "INSERT INTO sessions(id, user_id, expires_at, user_agent, ip) VALUES(?, ?, ?, ?, ?)",
            (token, user_row["id"], expires, ua, ip),
        )

        user = CurrentUser(
            id=user_row["id"], email=user_row["email"], role=user_row["role"], status=user_row["status"]
        )

    return True, "Signed in.", user, token


def resolve_session(token: str | None) -> CurrentUser | None:
    if not token:
        return None
    with db() as conn:
        row = conn.execute(
            "SELECT s.user_id, s.expires_at, u.email, u.role, u.status "
            "FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.id = ?",
            (token,),
        ).fetchone()
        if not row:
            return None
        if row["expires_at"] < _now_utc().isoformat(sep=" ", timespec="seconds"):
            return None
        if row["status"] != "active":
            return None
        return CurrentUser(id=row["user_id"], email=row["email"], role=row["role"], status=row["status"])


def invalidate_session(token: str | None) -> None:
    if not token:
        return
    with tx() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (token,))


def invalidate_user_sessions(user_id: int) -> None:
    with tx() as conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
