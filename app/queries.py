from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from typing import Any

from app.db import db
from app.sched import DAY_DATE, DAY_INDEX, DAY_SHORT, conflicts, floor_for, travel_warning


def _row_to_session(r: sqlite3.Row) -> dict:
    cols = set(r.keys())
    speakers: list[str] = []
    try:
        speakers = json.loads(r["speakers_json"] or "[]") if "speakers_json" in cols else []
    except (json.JSONDecodeError, TypeError):
        speakers = []
    return {
        "id": r["id"],
        "title": r["title"],
        "description": r["description"] if "description" in cols else None,
        "day": r["day"],
        "day_index": r["day_index"],
        "day_short": DAY_SHORT.get(r["day_index"], r["day"]),
        "date_iso": DAY_DATE.get(r["day_index"]),
        "start_time": r["start_time"],
        "end_time": r["end_time"],
        "time_label": r["time_label"],
        "room": r["room"],
        "floor": r["floor"],
        "type": r["type"],
        "track": r["track"],
        "status": r["status"],
        "speakers": speakers,
        "deleted": bool(r["deleted"]) if "deleted" in cols else False,
    }


def list_sessions(
    *,
    day_indexes: Iterable[int] | None = None,
    tracks: Iterable[str] | None = None,
    types: Iterable[str] | None = None,
    rooms: Iterable[str] | None = None,
    statuses: Iterable[str] | None = None,
    search: str | None = None,
    limit: int = 800,
) -> list[dict]:
    where = ["deleted = 0"]
    params: list[Any] = []
    if day_indexes:
        di = [int(d) for d in day_indexes]
        where.append(f"day_index IN ({','.join(['?']*len(di))})")
        params.extend(di)
    if tracks:
        t = list(tracks)
        where.append(f"track IN ({','.join(['?']*len(t))})")
        params.extend(t)
    if types:
        t = list(types)
        where.append(f"type IN ({','.join(['?']*len(t))})")
        params.extend(t)
    if rooms:
        r = list(rooms)
        where.append(f"room IN ({','.join(['?']*len(r))})")
        params.extend(r)
    if statuses:
        s = list(statuses)
        where.append(f"status IN ({','.join(['?']*len(s))})")
        params.extend(s)
    if search:
        like = f"%{search.strip().lower()}%"
        where.append(
            "(lower(title) LIKE ? OR lower(IFNULL(description,'')) LIKE ? OR lower(IFNULL(speakers_json,'')) LIKE ?)"
        )
        params.extend([like, like, like])
    sql = (
        "SELECT id, title, description, day, day_index, start_time, end_time, time_label, "
        "room, floor, type, track, status, speakers_json, deleted FROM conf_sessions "
        f"WHERE {' AND '.join(where)} ORDER BY day_index, start_time, room, title LIMIT ?"
    )
    params.append(limit)
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_session(r) for r in rows]


def get_session(session_id: int) -> dict | None:
    with db() as conn:
        r = conn.execute(
            "SELECT id, title, description, day, day_index, start_time, end_time, time_label, "
            "room, floor, type, track, status, speakers_json, deleted FROM conf_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    return _row_to_session(r) if r else None


def distinct_facets() -> dict[str, list]:
    """Legacy facets: full distinct lists, no counts. Used by profile/onboarding."""
    with db() as conn:
        tracks = [r[0] for r in conn.execute(
            "SELECT DISTINCT track FROM conf_sessions WHERE deleted=0 AND track IS NOT NULL AND track != '' ORDER BY track"
        ).fetchall()]
        rooms = [r[0] for r in conn.execute(
            "SELECT DISTINCT room FROM conf_sessions WHERE deleted=0 AND room IS NOT NULL AND room != '' ORDER BY room"
        ).fetchall()]
        types = [r[0] for r in conn.execute(
            "SELECT DISTINCT type FROM conf_sessions WHERE deleted=0 AND type IS NOT NULL AND type != '' ORDER BY type"
        ).fetchall()]
        statuses = [r[0] for r in conn.execute(
            "SELECT DISTINCT status FROM conf_sessions WHERE deleted=0 AND status IS NOT NULL AND status != '' ORDER BY status"
        ).fetchall()]
    days = [{"index": i, "label": k, "short": DAY_SHORT.get(i, k)} for k, i in DAY_INDEX.items()]
    return {"tracks": tracks, "rooms": rooms, "types": types, "statuses": statuses, "days": days}


_FACET_COLS = {"track": "track", "room": "room", "type": "type", "day": "day_index"}


def _where_for(active: dict[str, list], exclude_dim: str | None) -> tuple[str, list[Any]]:
    where = ["deleted = 0"]
    params: list[Any] = []
    if active.get("search"):
        like = f"%{str(active['search']).strip().lower()}%"
        where.append(
            "(lower(title) LIKE ? OR lower(IFNULL(description,'')) LIKE ? OR lower(IFNULL(speakers_json,'')) LIKE ?)"
        )
        params.extend([like, like, like])
    mapping = (("day", "day_index", int), ("track", "track", str), ("type", "type", str), ("room", "room", str))
    for dim, col, cast in mapping:
        if dim == exclude_dim:
            continue
        vals = active.get(dim) or []
        if not vals:
            continue
        v = [cast(x) for x in vals]
        where.append(f"{col} IN ({','.join(['?']*len(v))})")
        params.extend(v)
    return " AND ".join(where), params


def faceted_counts(active: dict[str, list]) -> dict[str, list[dict]]:
    """Return per-dimension options + counts, honoring active filters except the dimension itself."""
    out: dict[str, list[dict]] = {}
    selected = {dim: set(active.get(dim) or []) for dim in ("track", "type", "room")}
    selected_days = {int(d) for d in (active.get("day") or [])}
    with db() as conn:
        for dim in ("track", "type", "room"):
            col = _FACET_COLS[dim]
            sql_where, params = _where_for(active, exclude_dim=dim)
            sql = (
                f"SELECT {col} AS v, COUNT(*) AS c FROM conf_sessions "
                f"WHERE {sql_where} AND {col} IS NOT NULL AND {col} != '' "
                f"GROUP BY {col} ORDER BY c DESC, {col}"
            )
            rows = conn.execute(sql, params).fetchall()
            sel = selected[dim]
            out[dim] = [{"value": r["v"], "count": r["c"], "selected": r["v"] in sel} for r in rows]
        sql_where, params = _where_for(active, exclude_dim="day")
        rows = conn.execute(
            f"SELECT day_index AS v, COUNT(*) AS c FROM conf_sessions WHERE {sql_where} GROUP BY day_index",
            params,
        ).fetchall()
        day_counts = {int(r["v"]): r["c"] for r in rows}
    out["day"] = [
        {
            "index": i,
            "label": k,
            "short": DAY_SHORT.get(i, k),
            "count": day_counts.get(i, 0),
            "selected": i in selected_days,
        }
        for k, i in DAY_INDEX.items()
    ]
    return out


def list_speakers(search: str | None = None, limit: int = 500) -> list[dict]:
    sql = "SELECT id, name, role, company, twitter, sessions_count FROM conf_speakers"
    params: list[Any] = []
    if search:
        sql += " WHERE lower(name) LIKE ? OR lower(IFNULL(company,'')) LIKE ? OR lower(IFNULL(role,'')) LIKE ?"
        like = f"%{search.strip().lower()}%"
        params.extend([like, like, like])
    sql += " ORDER BY name LIMIT ?"
    params.append(limit)
    with db() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def speaker_with_sessions(name: str) -> dict | None:
    with db() as conn:
        sp = conn.execute(
            "SELECT id, name, role, company, twitter FROM conf_speakers WHERE name = ?", (name,)
        ).fetchone()
        if not sp:
            return None
        rows = conn.execute(
            "SELECT id, title, description, day, day_index, start_time, end_time, time_label, "
            "room, floor, type, track, status, speakers_json, deleted FROM conf_sessions "
            "WHERE deleted=0 AND speakers_json LIKE ? ORDER BY day_index, start_time",
            (f"%{name}%",),
        ).fetchall()
    sessions = []
    for r in rows:
        s = _row_to_session(r)
        if name in s["speakers"]:
            sessions.append(s)
    return {**dict(sp), "sessions": sessions}


def itinerary_sessions(user_id: int) -> list[dict]:
    sql = (
        "SELECT cs.id, cs.title, cs.description, cs.day, cs.day_index, cs.start_time, cs.end_time, "
        "cs.time_label, cs.room, cs.floor, cs.type, cs.track, cs.status, cs.speakers_json, cs.deleted, "
        "it.is_backup FROM itinerary it JOIN conf_sessions cs ON cs.id = it.session_id "
        "WHERE it.user_id = ? ORDER BY cs.day_index, cs.start_time"
    )
    with db() as conn:
        rows = conn.execute(sql, (user_id,)).fetchall()
    out = []
    for r in rows:
        s = _row_to_session(r)
        s["is_backup"] = bool(r["is_backup"])
        out.append(s)
    return out


def itinerary_map(user_id: int) -> dict[int, bool]:
    """session_id → is_backup."""
    with db() as conn:
        rows = conn.execute(
            "SELECT session_id, is_backup FROM itinerary WHERE user_id = ?", (user_id,)
        ).fetchall()
    return {int(r["session_id"]): bool(r["is_backup"]) for r in rows}


def itinerary_ids(user_id: int) -> set[int]:
    with db() as conn:
        return {r[0] for r in conn.execute("SELECT session_id FROM itinerary WHERE user_id = ?", (user_id,)).fetchall()}


def annotate_with_conflicts(items: list[dict]) -> list[dict]:
    """Return the items with `conflicts_with` (list of conflicting ids on same day) and `travel_warn`."""
    by_day: dict[int, list[dict]] = {}
    for s in items:
        by_day.setdefault(s["day_index"], []).append(s)
    for day_items in by_day.values():
        day_items.sort(key=lambda x: (x["start_time"] or "", x["title"]))
        for a in day_items:
            a.setdefault("conflicts_with", [])
            a.setdefault("travel_warn", None)
            primaries = [x for x in day_items if not x.get("is_backup")]
            for b in primaries:
                if b["id"] == a["id"]:
                    continue
                if conflicts(a["start_time"], a["end_time"], b["start_time"], b["end_time"]):
                    a["conflicts_with"].append(b["id"])
        primaries = [x for x in day_items if not x.get("is_backup")]
        for prev, nxt in zip(primaries, primaries[1:], strict=False):
            warn = travel_warning(prev["end_time"], prev["room"], nxt["start_time"], nxt["room"])
            if warn:
                nxt["travel_warn"] = warn
    return items


def add_itinerary(user_id: int, session_id: int) -> None:
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO itinerary(user_id, session_id) VALUES(?, ?)", (user_id, session_id)
        )


def remove_itinerary(user_id: int, session_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM itinerary WHERE user_id = ? AND session_id = ?", (user_id, session_id))


def set_backup(user_id: int, session_id: int, is_backup: bool) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE itinerary SET is_backup = ? WHERE user_id = ? AND session_id = ?",
            (1 if is_backup else 0, user_id, session_id),
        )


def floor_label(room: str | None) -> str | None:
    f = floor_for(room)
    if not f:
        return None
    return {"1": "Floor 1", "2": "Floor 2", "3": "Floor 3"}[f]


def last_sessions_sync_at() -> str | None:
    sql = (
        "SELECT finished_at FROM sync_log "
        "WHERE source='sessions' AND status='ok' AND finished_at IS NOT NULL "
        "ORDER BY finished_at DESC LIMIT 1"
    )
    with db() as conn:
        row = conn.execute(sql).fetchone()
    return row["finished_at"] if row else None


def get_share_token(user_id: int) -> str | None:
    with db() as conn:
        row = conn.execute("SELECT share_token FROM users WHERE id = ?", (user_id,)).fetchone()
    return row["share_token"] if row else None


def set_share_token(user_id: int, token: str) -> None:
    with db() as conn:
        conn.execute("UPDATE users SET share_token = ? WHERE id = ?", (token, user_id))


def clear_share_token(user_id: int) -> None:
    with db() as conn:
        conn.execute("UPDATE users SET share_token = NULL WHERE id = ?", (user_id,))


def user_by_share_token(token: str) -> dict | None:
    if not token:
        return None
    with db() as conn:
        row = conn.execute(
            "SELECT id, email, share_token FROM users WHERE share_token = ? AND status = 'active'",
            (token,),
        ).fetchone()
    return dict(row) if row else None


def session_changes_for_user(user_id: int, since_hours: int = 72) -> list[dict]:
    sql = (
        "SELECT sc.id, sc.session_id, sc.change_type, sc.field, sc.old_value, sc.new_value, sc.detected_at, "
        "cs.title, cs.day, cs.day_index, cs.time_label, cs.room "
        "FROM session_changes sc JOIN conf_sessions cs ON cs.id = sc.session_id "
        "JOIN itinerary it ON it.session_id = sc.session_id AND it.user_id = ? "
        "WHERE sc.detected_at >= datetime('now', ?) "
        "ORDER BY sc.detected_at DESC LIMIT 50"
    )
    with db() as conn:
        rows = conn.execute(sql, (user_id, f"-{int(since_hours)} hours")).fetchall()
    return [dict(r) for r in rows]
