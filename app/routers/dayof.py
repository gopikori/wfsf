from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.auth import CurrentUser
from app.config import settings
from app.deps import current_user
from app.queries import (
    annotate_with_conflicts,
    itinerary_sessions,
    list_sessions,
    session_changes_for_user,
)
from app.sched import DAY_DATE, DAY_INDEX, DAY_SHORT, session_end_datetime, session_start_datetime
from app.templating import templates

router = APIRouter()


def _today_day_index(now: datetime) -> int | None:
    today_iso = now.date().isoformat()
    for idx, iso in DAY_DATE.items():
        if iso == today_iso:
            return idx
    if now.date() < date.fromisoformat(DAY_DATE[0]):
        return 0
    if now.date() > date.fromisoformat(DAY_DATE[max(DAY_DATE.keys())]):
        return max(DAY_DATE.keys())
    return None


def _categorize(items: list[dict], now: datetime) -> dict:
    primaries = [s for s in items if not s.get("is_backup")]
    backups = [s for s in items if s.get("is_backup")]
    happening_now = []
    upcoming = []
    past = []
    for s in primaries:
        start = session_start_datetime(s["day_index"], s["start_time"] or "")
        end = session_end_datetime(s["day_index"], s["end_time"], s["start_time"])
        if not start or not end:
            continue
        if start <= now < end:
            happening_now.append({**s, "_start": start, "_end": end})
        elif start > now:
            upcoming.append({**s, "_start": start, "_end": end})
        else:
            past.append({**s, "_start": start, "_end": end})
    upcoming.sort(key=lambda x: x["_start"])
    next_session = upcoming[0] if upcoming else None
    return {
        "now_items": happening_now,
        "next_session": next_session,
        "upcoming": upcoming[:5],
        "past_count": len(past),
        "backups": backups,
    }


def _gap_suggestions(now: datetime, day_idx: int, interests: list[str]) -> list[dict]:
    end_window = now + timedelta(minutes=90)
    sessions = list_sessions(day_indexes=[day_idx], tracks=interests or None)
    out = []
    for s in sessions:
        start = session_start_datetime(s["day_index"], s["start_time"] or "")
        if not start:
            continue
        if now <= start <= end_window:
            out.append({**s, "_start": start})
    out.sort(key=lambda x: x["_start"])
    return out[:5]


def _interest_tracks(user_id: int) -> list[str]:
    import json

    from app.db import db

    with db() as conn:
        row = conn.execute(
            "SELECT interest_tracks_json FROM user_prefs WHERE user_id = ?", (user_id,)
        ).fetchone()
    if not row:
        return []
    try:
        return list(json.loads(row["interest_tracks_json"] or "[]"))
    except json.JSONDecodeError:
        return []


def _resolve_now(request: Request) -> tuple[datetime, str | None]:
    """Returns (effective now, simulation label if overridden).
    The ?as_of=ISO override is honored ONLY when DEV_OTP_LOG=true so it can't
    leak to production. Accepts both 'YYYY-MM-DDTHH:MM' and 'YYYY-MM-DD'.
    """
    if not settings.DEV_OTP_LOG:
        return datetime.now(), None
    raw = (request.query_params.get("as_of") or "").strip()
    if not raw:
        return datetime.now(), None
    try:
        simulated = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.now(), None
    return simulated, simulated.strftime("%a %b %-d %Y · %-I:%M %p")


@router.get("/day-of", response_class=HTMLResponse)
async def day_of(request: Request, user: CurrentUser = Depends(current_user)):
    now, sim_label = _resolve_now(request)
    day_idx = _today_day_index(now)
    items_all = annotate_with_conflicts(itinerary_sessions(user.id))
    today_items = [s for s in items_all if s["day_index"] == day_idx] if day_idx is not None else []
    cat = _categorize(today_items, now)
    suggestions = []
    if day_idx is not None and not cat["now_items"]:
        suggestions = _gap_suggestions(now, day_idx, _interest_tracks(user.id))
    changes = session_changes_for_user(user.id, since_hours=72)
    ctx = {
        "request": request,
        "user": user,
        "now": now,
        "day_index": day_idx,
        "day_label": DAY_SHORT.get(day_idx, "") if day_idx is not None else "Pre-event",
        "categories": cat,
        "suggestions": suggestions,
        "changes": changes,
        "in_event": day_idx is not None and now.date().isoformat() == DAY_DATE.get(day_idx),
        "days_known": [{"index": i, "iso": DAY_DATE[i], "short": DAY_SHORT[i]} for i in sorted(DAY_INDEX.values())],
        "today_total": len(today_items),
        "sim_label": sim_label,
    }
    return templates.TemplateResponse("dayof.html", ctx)
