from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "WFSF"
    APP_BASE_URL: str = "http://localhost:10000"
    APP_PORT: int = 10000
    APP_HOST: str = "0.0.0.0"

    DATABASE_PATH: str = "data/wfsf.db"

    SESSION_SECRET: str = "change-me-in-prod-please"
    SESSION_COOKIE_NAME: str = "wfsf_session"
    SESSION_TTL_DAYS: int = 30
    # Marks the session cookie Secure so browsers only send it over HTTPS.
    # Default True for prod (Render serves HTTPS); set false for plain-HTTP LAN dev.
    COOKIE_SECURE: bool = True

    RESEND_API_KEY: str = ""
    RESEND_FROM: str = "WFSF <onboarding@resend.dev>"

    # Comma-separated emails granted admin role on first OTP verify. Set via .env.
    ADMIN_EMAILS: str = ""

    OTP_TTL_MINUTES: int = 10
    OTP_MAX_PER_HOUR: int = 5
    OTP_MAX_BAD_ATTEMPTS: int = 5
    OTP_RESEND_COOLDOWN_SECONDS: int = 30

    SYNC_SOURCES_FILE: str = "sources.txt"
    SYNC_INTERVAL_NORMAL_MINUTES: int = 60
    SYNC_INTERVAL_EVENT_MINUTES: int = 15
    EVENT_START: str = "2026-06-28"
    EVENT_END: str = "2026-07-02"

    SESSIONS_URL: str = "https://www.ai.engineer/worldsfair/2026/sessions.json"
    SPEAKERS_URL: str = "https://www.ai.engineer/worldsfair/2026/speakers.json"
    MCP_URL: str = "https://www.ai.engineer/worldsfair/2026/mcp"

    # Logs OTP codes to stdout. Default False (prod-safe); enable in local dev
    # when no RESEND_API_KEY is set so you can read the code from the console.
    DEV_OTP_LOG: bool = False

    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.ADMIN_EMAILS.split(",") if e.strip()}

    def db_dir(self) -> Path:
        p = Path(self.DATABASE_PATH).resolve().parent
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
