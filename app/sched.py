from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

EVENT_TZ = ZoneInfo("America/Los_Angeles")

DAY_INDEX = {
    "Day 1 — Workshop Day": 0,
    "Day 2 — Session Day 1": 1,
    "Day 3 — Session Day 2": 2,
    "Day 4 — Session Day 3": 3,
}
DAY_DATE = {
    0: "2026-06-29",
    1: "2026-06-30",
    2: "2026-07-01",
    3: "2026-07-02",
}
DAY_SHORT = {
    0: "Mon Jun 29",
    1: "Tue Jun 30",
    2: "Wed Jul 1",
    3: "Thu Jul 2",
}


def event_now() -> datetime:
    return datetime.now(EVENT_TZ)

# Map room -> floor based on llms.md (1: Expo/Registration, 2: Breakouts, 3: Keynotes)
ROOM_FLOOR = {
    "Main Stage": "3",
    "Leadership 1": "3",
    "Leadership 2": "3",
    "Track 1": "2",
    "Track 2": "2",
    "Track 3": "2",
    "Track 4": "2",
    "Track 5": "2",
    "Track 6": "2",
    "Track 7": "2",
    "Track 8": "2",
    "Track 9": "2",
    "Track M": "2",
    "Expo Stage 1": "1",
    "Expo Stage 2": "1",
    "Expo Stage 3": "1",
    "Expo Stage 4": "1",
    "Expo Stage NE": "1",
}


def floor_for(room: str | None) -> str | None:
    if not room:
        return None
    return ROOM_FLOOR.get(room.strip())


_TIME_RE = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([ap]m)\s*$", re.IGNORECASE)


def _parse_one(t: str) -> time | None:
    m = _TIME_RE.match(t)
    if not m:
        return None
    h = int(m.group(1))
    mins = int(m.group(2) or 0)
    ap = m.group(3).lower()
    if ap == "am":
        if h == 12:
            h = 0
    else:
        if h != 12:
            h += 12
    return time(hour=h, minute=mins)


def parse_time_range(label: str | None) -> tuple[str | None, str | None]:
    """Parse a label like '9:00am-11:00am' into 24h ISO time strings (HH:MM)."""
    if not label:
        return None, None
    parts = [p.strip() for p in re.split(r"[-–]", label, maxsplit=1)]
    if len(parts) != 2:
        return None, None
    a, b = _parse_one(parts[0]), _parse_one(parts[1])
    return (a.isoformat(timespec="minutes") if a else None, b.isoformat(timespec="minutes") if b else None)


def session_natural_key(day: str, time_label: str, room: str, title: str) -> str:
    return f"{day}|{time_label}|{room}|{title}".lower()


def session_start_datetime(day_index: int, start_hhmm: str) -> datetime | None:
    iso = DAY_DATE.get(day_index)
    if iso is None or not start_hhmm:
        return None
    try:
        return datetime.fromisoformat(f"{iso}T{start_hhmm}:00").replace(tzinfo=EVENT_TZ)
    except ValueError:
        return None


def session_end_datetime(day_index: int, end_hhmm: str | None, start_hhmm: str | None) -> datetime | None:
    iso = DAY_DATE.get(day_index)
    if iso is None or not end_hhmm:
        return None
    try:
        end = datetime.fromisoformat(f"{iso}T{end_hhmm}:00").replace(tzinfo=EVENT_TZ)
    except ValueError:
        return None
    if start_hhmm:
        try:
            start = datetime.fromisoformat(f"{iso}T{start_hhmm}:00").replace(tzinfo=EVENT_TZ)
            if end < start:
                end = end + timedelta(days=1)
        except ValueError:
            pass
    return end


@dataclass
class NormalizedSession:
    natural_key: str
    title: str
    description: str | None
    day: str
    day_index: int
    start_time: str | None
    end_time: str | None
    time_label: str | None
    room: str | None
    floor: str | None
    type: str | None
    track: str | None
    status: str | None
    speakers_json: str


def normalize_session(row: dict) -> NormalizedSession | None:
    title = (row.get("title") or "").strip()
    day = (row.get("day") or "").strip()
    time_label = (row.get("time") or "").strip()
    room = (row.get("room") or "").strip() or None
    if not title or not day:
        return None
    di = DAY_INDEX.get(day, 0)
    start, end = parse_time_range(time_label)
    speakers = row.get("speakers") or []
    return NormalizedSession(
        natural_key=session_natural_key(day, time_label, room or "", title),
        title=title,
        description=(row.get("description") or "").strip() or None,
        day=day,
        day_index=di,
        start_time=start,
        end_time=end,
        time_label=time_label or None,
        room=room,
        floor=floor_for(room),
        type=(row.get("type") or "").strip() or None,
        track=(row.get("track") or "").strip() or None,
        status=(row.get("status") or "").strip() or None,
        speakers_json=json.dumps(speakers, ensure_ascii=False),
    )


def hhmm_to_minutes(hm: str | None) -> int | None:
    """'09:30' -> 570. None/malformed -> None."""
    if not hm or ":" not in hm:
        return None
    try:
        h, m = hm.split(":", 1)
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def slot_state(primary_count: int, backup_count: int, is_past: bool) -> str:
    """Derive a slot's visual state from the user's picks in it."""
    if is_past:
        return "past"
    if primary_count >= 2:
        return "conflict"
    if primary_count == 1:
        return "primary"
    if backup_count >= 1:
        return "backup"
    return "empty"


def conflicts(a_start: str | None, a_end: str | None, b_start: str | None, b_end: str | None) -> bool:
    if not (a_start and a_end and b_start and b_end):
        return False
    return a_start < b_end and b_start < a_end


def travel_warning(end_a: str | None, room_a: str | None, start_b: str | None, room_b: str | None) -> str | None:
    if not (end_a and start_b and room_a and room_b):
        return None
    if room_a.strip().lower() == room_b.strip().lower():
        return None
    fa, fb = floor_for(room_a), floor_for(room_b)
    try:
        gap_minutes = (datetime.fromisoformat(f"2000-01-01T{start_b}:00") - datetime.fromisoformat(f"2000-01-01T{end_a}:00")).total_seconds() / 60
    except ValueError:
        return None
    if gap_minutes < 0:
        return None
    if fa and fb and fa != fb and gap_minutes <= 15:
        return f"Tight: only {int(gap_minutes)} min and different floor ({room_a} → {room_b})"
    if gap_minutes <= 5:
        return f"Tight: only {int(gap_minutes)} min between rooms ({room_a} → {room_b})"
    return None
