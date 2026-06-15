from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.config import settings

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','admin')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_login_at TEXT
);
CREATE INDEX IF NOT EXISTS users_email_idx ON users(email);

CREATE TABLE IF NOT EXISTS otp_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    bad_attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS otp_email_idx ON otp_codes(email);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    user_agent TEXT,
    ip TEXT
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(user_id);

CREATE TABLE IF NOT EXISTS conf_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    natural_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    day TEXT NOT NULL,
    day_index INTEGER NOT NULL,
    start_time TEXT,
    end_time TEXT,
    time_label TEXT,
    room TEXT,
    floor TEXT,
    type TEXT,
    track TEXT,
    status TEXT,
    speakers_json TEXT,
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS conf_sessions_day_idx ON conf_sessions(day_index, start_time);
CREATE INDEX IF NOT EXISTS conf_sessions_track_idx ON conf_sessions(track);
CREATE INDEX IF NOT EXISTS conf_sessions_room_idx ON conf_sessions(room);
CREATE INDEX IF NOT EXISTS conf_sessions_type_idx ON conf_sessions(type);
CREATE INDEX IF NOT EXISTS conf_sessions_status_idx ON conf_sessions(status);

CREATE TABLE IF NOT EXISTS conf_speakers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    role TEXT,
    company TEXT,
    twitter TEXT,
    sessions_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS conf_speakers_name_idx ON conf_speakers(name);

CREATE TABLE IF NOT EXISTS itinerary (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id INTEGER NOT NULL REFERENCES conf_sessions(id) ON DELETE CASCADE,
    is_backup INTEGER NOT NULL DEFAULT 0,
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, session_id)
);
CREATE INDEX IF NOT EXISTS itinerary_user_idx ON itinerary(user_id);

CREATE TABLE IF NOT EXISTS session_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES conf_sessions(id) ON DELETE CASCADE,
    change_type TEXT NOT NULL,
    field TEXT,
    old_value TEXT,
    new_value TEXT,
    detected_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS session_changes_session_idx ON session_changes(session_id, detected_at);

CREATE TABLE IF NOT EXISTS user_prefs (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    interest_tracks_json TEXT,
    reminders_enabled INTEGER NOT NULL DEFAULT 0,
    onboarded INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS admin_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_user_id INTEGER NOT NULL REFERENCES users(id),
    target_user_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS audit_actor_idx ON admin_audit(actor_user_id);

CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    items_seen INTEGER,
    items_changed INTEGER,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS rate_limit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bucket TEXT NOT NULL,
    key TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS rate_limit_bucket_key_idx ON rate_limit(bucket, key, created_at);
"""


def get_db_path() -> Path:
    p = Path(settings.DATABASE_PATH)
    if not p.is_absolute():
        p = Path.cwd() / p
    settings.db_dir()
    return p


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(get_db_path()), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        conn.execute("BEGIN")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        finally:
            pass
        raise
    finally:
        conn.close()


def init_schema() -> None:
    with db() as conn:
        conn.executescript(_SCHEMA)
    _seed_admins()


def _seed_admins() -> None:
    emails = settings.admin_email_set()
    if not emails:
        return
    with tx() as conn:
        for email in emails:
            row = conn.execute("SELECT id, role, status FROM users WHERE email = ?", (email,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO users(email, role, status) VALUES(?, 'admin', 'active')", (email,)
                )
            elif row["role"] != "admin" or row["status"] != "active":
                conn.execute(
                    "UPDATE users SET role='admin', status='active' WHERE id = ?", (row["id"],)
                )
