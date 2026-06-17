"""Builder for the '4 days at a glance' grid.

Produces a 4-column day grid on a shared global time axis: every conference
slot becomes a block positioned by start time / sized by duration, coloured by
the viewer's pick state. Reused by the authenticated glance page and the public
shared-schedule page so both render from one source of truth.
"""
from __future__ import annotations

from app.queries import itinerary_map, list_sessions
from app.sched import DAY_DATE, DAY_INDEX, DAY_SHORT, hhmm_to_minutes, slot_state
from app.templating import display_time

_PAD_MIN = 15  # breathing room above first / below last block
_COMPACT_MAX_MIN = 15  # at/under this duration a tile is single-row (no wrap)


def _slot_detail(s: dict, is_backup: bool) -> dict:
    return {
        "title": s["title"],
        "start": s["start_time"],
        "end": s["end_time"],
        "room": s["room"],
        "floor": s["floor"],
        "track": s["track"],
        "status": s["status"],
        "speakers": s.get("speakers") or [],
        "is_backup": is_backup,
    }


def _day_header(day_index: int) -> tuple[str, str]:
    short = DAY_SHORT.get(day_index, f"Day {day_index + 1}")
    parts = short.split(" ", 1)
    dow = parts[0]
    rest = parts[1] if len(parts) > 1 else short
    return dow, rest


def _axis_bounds(by_day: dict[int, dict[str, list[dict]]]) -> tuple[int, int]:
    starts: list[int] = []
    ends: list[int] = []
    for slots in by_day.values():
        for key, sess in slots.items():
            st = hhmm_to_minutes(key)
            if st is not None:
                starts.append(st)
            for s in sess:
                en = hhmm_to_minutes(s["end_time"])
                if en is not None:
                    ends.append(en)
    if not starts:
        return 9 * 60, 18 * 60
    lo = min(starts) - _PAD_MIN
    hi = max(ends + starts) + _PAD_MIN
    return lo, max(hi, lo + 60)


def _build_slots(slots: dict[str, list[dict]], picks: dict[int, bool], axis_lo: int, span: int) -> list[dict]:
    keys = sorted(k for k in slots if hhmm_to_minutes(k) is not None)
    starts = [hhmm_to_minutes(k) for k in keys]
    out: list[dict] = []
    for i, key in enumerate(keys):
        sess = slots[key]
        start_min = starts[i]
        next_start = starts[i + 1] if i + 1 < len(keys) else None
        real_end = max((hhmm_to_minutes(s["end_time"]) or start_min for s in sess), default=start_min)
        end_min = real_end if real_end > start_min else start_min + 30
        if next_start is not None and end_min > next_start:
            end_min = next_start  # clip to avoid overlapping the next slot
        end_min = max(end_min, start_min + 10)

        primaries = [s for s in sess if s["id"] in picks and not picks[s["id"]]]
        backups = [s for s in sess if s["id"] in picks and picks[s["id"]]]
        state = slot_state(len(primaries), len(backups), False)
        mine = primaries + backups
        rep = (primaries or backups or [None])[0]
        ends = [s["end_time"] for s in sess if s["end_time"]]
        out.append({
            "key": key.replace(":", ""),
            "state": state,
            "top_pct": round(100 * (start_min - axis_lo) / span, 3),
            "height_pct": round(100 * (end_min - start_min) / span, 3),
            "compact": (end_min - start_min) <= _COMPACT_MAX_MIN,
            "start": display_time(key),
            "end": display_time(max(ends)) if ends else "",
            "title": rep["title"] if rep else None,
            "pick_count": len(mine),
            "extra": max(len(mine) - 1, 0),
            "available": len(sess),
            "sessions": [_slot_detail(s, bool(picks[s["id"]])) for s in mine],
        })
    return out


def glance_grid(user_id: int) -> dict:
    picks = itinerary_map(user_id)
    sessions = list_sessions(limit=2000)
    by_day: dict[int, dict[str, list[dict]]] = {}
    for s in sessions:
        di = s["day_index"]
        key = s["start_time"] or ""
        if not key:
            continue
        by_day.setdefault(di, {}).setdefault(key, []).append(s)

    axis_lo, axis_hi = _axis_bounds(by_day)
    span = axis_hi - axis_lo
    hours = []
    h = ((axis_lo + 59) // 60) * 60
    while h <= axis_hi:
        hours.append({"label": display_time(f"{h // 60:02d}:{h % 60:02d}"), "top_pct": round(100 * (h - axis_lo) / span, 3)})
        h += 60

    days = []
    for di in sorted(DAY_INDEX.values()):
        dow, rest = _day_header(di)
        slots = _build_slots(by_day.get(di, {}), picks, axis_lo, span)
        days.append({
            "day_index": di,
            "dow": dow,
            "date": rest,
            "date_iso": DAY_DATE.get(di),
            "pick_count": sum(s["pick_count"] for s in slots),
            "slots": slots,
        })
    return {"axis": {"span": span, "hours": hours}, "days": days, "total": len(picks)}
