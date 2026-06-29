from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from typing import Any

import httpx

from app.config import settings
from app.db import tx
from app.sched import (
    DAY_INDEX,
    NormalizedSession,
    event_now,
    normalize_session,
)

logger = logging.getLogger(__name__)


_SYNC_FIELDS = (
    "title",
    "description",
    "day",
    "day_index",
    "start_time",
    "end_time",
    "time_label",
    "room",
    "floor",
    "type",
    "track",
    "status",
    "speakers_json",
)


def _http_get_json(url: str) -> Any:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        r = client.get(url, headers={"accept": "application/json"})
        r.raise_for_status()
        return r.json()


def _fetch_sessions_via_mcp() -> list[dict]:
    """Backend-only fallback. JSON-RPC 2.0 against MCP `list_sessions`."""
    base = settings.MCP_URL.rstrip("/")
    headers = {"content-type": "application/json", "accept": "application/json"}
    with httpx.Client(timeout=45.0, follow_redirects=True, headers=headers) as client:
        init = client.post(
            base,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "wfsf-sync"}},
            },
        )
        init.raise_for_status()
        r = client.post(
            base,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_sessions", "arguments": {}}},
        )
        r.raise_for_status()
        payload = r.json()
        content = payload.get("result", {}).get("content", [])
        for item in content:
            if item.get("type") == "json":
                data = item.get("json")
                if isinstance(data, dict) and "sessions" in data:
                    return data["sessions"]
                if isinstance(data, list):
                    return data
            if item.get("type") == "text":
                try:
                    data = json.loads(item.get("text", ""))
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict) and "sessions" in data:
                    return data["sessions"]
                if isinstance(data, list):
                    return data
        raise RuntimeError("MCP list_sessions returned no usable content")


def fetch_sessions() -> list[dict]:
    try:
        data = _http_get_json(settings.SESSIONS_URL)
        if isinstance(data, dict) and "sessions" in data:
            return data["sessions"]
        if isinstance(data, list):
            return data
        raise ValueError("Unexpected shape for sessions.json")
    except Exception as exc:  # noqa: BLE001 - fall back to MCP
        logger.warning("sessions.json failed (%s); falling back to MCP", exc)
        return _fetch_sessions_via_mcp()


def fetch_speakers() -> list[dict]:
    data = _http_get_json(settings.SPEAKERS_URL)
    if isinstance(data, dict) and "speakers" in data:
        return data["speakers"]
    if isinstance(data, list):
        return data
    raise ValueError("Unexpected shape for speakers.json")


def _existing_sessions(conn) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT id, natural_key, " + ",".join(_SYNC_FIELDS) + ", deleted FROM conf_sessions"
    ).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        out[r["natural_key"]] = dict(r)
    return out


def _upsert_session(conn, ns: NormalizedSession, existing: dict | None) -> tuple[int, list[tuple[str, str | None, str | None]]]:
    """Returns (session_id, list of (field, old, new) changes)."""
    if existing is None:
        cur = conn.execute(
            """INSERT INTO conf_sessions
                (natural_key, title, description, day, day_index, start_time, end_time, time_label,
                 room, floor, type, track, status, speakers_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ns.natural_key, ns.title, ns.description, ns.day, ns.day_index, ns.start_time,
                ns.end_time, ns.time_label, ns.room, ns.floor, ns.type, ns.track, ns.status,
                ns.speakers_json,
            ),
        )
        return cur.lastrowid, []

    changes: list[tuple[str, str | None, str | None]] = []
    new_vals = {
        "title": ns.title, "description": ns.description, "day": ns.day, "day_index": ns.day_index,
        "start_time": ns.start_time, "end_time": ns.end_time, "time_label": ns.time_label,
        "room": ns.room, "floor": ns.floor, "type": ns.type, "track": ns.track, "status": ns.status,
        "speakers_json": ns.speakers_json,
    }
    for k, v in new_vals.items():
        old = existing.get(k)
        if (old or "") != (v or "") and k not in ("description", "speakers_json"):
            changes.append((k, str(old) if old is not None else None, str(v) if v is not None else None))
        elif k in ("description", "speakers_json") and (old or "") != (v or ""):
            changes.append((k, None, None))
    conn.execute(
        "UPDATE conf_sessions SET title=?, description=?, day=?, day_index=?, start_time=?, end_time=?, "
        "time_label=?, room=?, floor=?, type=?, track=?, status=?, speakers_json=?, "
        "last_seen_at=datetime('now'), updated_at=datetime('now'), deleted=0 WHERE id = ?",
        (
            ns.title, ns.description, ns.day, ns.day_index, ns.start_time, ns.end_time, ns.time_label,
            ns.room, ns.floor, ns.type, ns.track, ns.status, ns.speakers_json, existing["id"],
        ),
    )
    return existing["id"], changes


def sync_sessions() -> dict:
    started = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
    seen = 0
    changed_count = 0
    soft_deleted = 0
    with tx() as conn:
        log = conn.execute(
            "INSERT INTO sync_log(source, status, started_at) VALUES('sessions', 'running', ?) RETURNING id",
            (started,),
        ).fetchone()
        sync_id = log["id"]
    try:
        sessions = fetch_sessions()
    except Exception as exc:  # noqa: BLE001
        with tx() as conn:
            conn.execute(
                "UPDATE sync_log SET status='error', message=?, finished_at=datetime('now') WHERE id = ?",
                (str(exc), sync_id),
            )
        raise
    with tx() as conn:
        existing = _existing_sessions(conn)
        seen_keys: set[str] = set()
        for raw in sessions:
            ns = normalize_session(raw)
            if ns is None:
                continue
            seen += 1
            seen_keys.add(ns.natural_key)
            existing_row = existing.get(ns.natural_key)
            session_id, changes = _upsert_session(conn, ns, existing_row)
            if existing_row is None or changes:
                changed_count += 1
            for field, old, new in changes:
                conn.execute(
                    "INSERT INTO session_changes(session_id, change_type, field, old_value, new_value) VALUES(?, 'updated', ?, ?, ?)",
                    (session_id, field, old, new),
                )
        for nat_key, row in existing.items():
            if nat_key not in seen_keys and not row.get("deleted"):
                conn.execute("UPDATE conf_sessions SET deleted=1, updated_at=datetime('now') WHERE id = ?", (row["id"],))
                conn.execute(
                    "INSERT INTO session_changes(session_id, change_type, field, old_value, new_value) VALUES(?, 'cancelled', NULL, NULL, NULL)",
                    (row["id"],),
                )
                soft_deleted += 1
        conn.execute(
            "UPDATE sync_log SET status='ok', items_seen=?, items_changed=?, message=?, finished_at=datetime('now') WHERE id = ?",
            (seen, changed_count + soft_deleted, json.dumps({"deleted": soft_deleted}), sync_id),
        )
    return {"seen": seen, "changed": changed_count, "deleted": soft_deleted}


def sync_speakers() -> dict:
    with tx() as conn:
        log = conn.execute(
            "INSERT INTO sync_log(source, status) VALUES('speakers', 'running') RETURNING id"
        ).fetchone()
        sync_id = log["id"]
    try:
        speakers = fetch_speakers()
    except Exception as exc:  # noqa: BLE001
        with tx() as conn:
            conn.execute(
                "UPDATE sync_log SET status='error', message=?, finished_at=datetime('now') WHERE id = ?",
                (str(exc), sync_id),
            )
        raise
    seen = 0
    with tx() as conn:
        for sp in speakers:
            name = (sp.get("name") or "").strip()
            if not name:
                continue
            seen += 1
            conn.execute(
                """INSERT INTO conf_speakers(name, role, company, twitter, sessions_count, updated_at)
                   VALUES(?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(name) DO UPDATE SET
                     role=excluded.role, company=excluded.company, twitter=excluded.twitter,
                     sessions_count=excluded.sessions_count, updated_at=datetime('now')""",
                (
                    name,
                    (sp.get("role") or "").strip() or None,
                    (sp.get("company") or "").strip() or None,
                    (sp.get("twitter") or "").strip() or None,
                    len(sp.get("sessions") or []),
                ),
            )
        conn.execute(
            "UPDATE sync_log SET status='ok', items_seen=?, finished_at=datetime('now') WHERE id = ?",
            (seen, sync_id),
        )
    return {"seen": seen}


def sync_all() -> dict:
    s = sync_sessions()
    sp = sync_speakers()
    return {"sessions": s, "speakers": sp}


def current_interval_minutes() -> int:
    today = event_now().date()
    try:
        start = date.fromisoformat(settings.EVENT_START)
        end = date.fromisoformat(settings.EVENT_END)
    except ValueError:
        return settings.SYNC_INTERVAL_NORMAL_MINUTES
    if start <= today <= end:
        return settings.SYNC_INTERVAL_EVENT_MINUTES
    return settings.SYNC_INTERVAL_NORMAL_MINUTES


def known_days() -> list[str]:
    return list(DAY_INDEX.keys())
