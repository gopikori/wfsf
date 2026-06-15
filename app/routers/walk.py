"""Walk-preview route: animated map of a day's hops between rooms.

Returns the user's picked sessions for the given day, sorted by start time,
each enriched with floor + (x_pct, y_pct) from venue.json. Sessions whose
room isn't on the floorplan (off-venue, missing data) are still included so
the timeline shows them; the frontend just skips animating to them.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.auth import CurrentUser
from app.deps import current_user
from app.queries import annotate_with_conflicts, itinerary_sessions
from app.sched import DAY_DATE, DAY_INDEX, DAY_SHORT
from app.templating import templates
from app.venue import floors as venue_floors
from app.venue import locate, venue_info
from app.venue import rooms as venue_rooms

router = APIRouter()


def _start_min(hm: str | None) -> int:
    if not hm or ":" not in hm:
        return 99999
    try:
        h, m = hm.split(":", 1)
        return int(h) * 60 + int(m)
    except ValueError:
        return 99999


def _build_hops(items: list[dict], day_index: int) -> list[dict]:
    """Return picked PRIMARY sessions for the day, sorted by start time,
    each with location info (floor/x/y) attached when available."""
    day_items = [s for s in items if s["day_index"] == day_index and not s.get("is_backup")]
    day_items.sort(key=lambda s: (_start_min(s.get("start_time")), s.get("title") or ""))
    hops: list[dict] = []
    for s in day_items:
        loc = locate(s.get("room"))
        hops.append({
            "id": s["id"],
            "title": s["title"],
            "room": s.get("room"),
            "start_time": s.get("start_time"),
            "end_time": s.get("end_time"),
            "track": s.get("track"),
            "floor": loc["floor"] if loc else None,
            "x_pct": loc["x_pct"] if loc else None,
            "y_pct": loc["y_pct"] if loc else None,
            "label_on_plan": loc.get("label_on_plan") if loc else None,
            "off_venue": loc is None,
        })
    return hops


@router.get("/walk", response_class=HTMLResponse)
async def walk_default(request: Request, user: CurrentUser = Depends(current_user)):
    """Pick the earliest day that has at least one pick, falling back to day 0."""
    items = annotate_with_conflicts(itinerary_sessions(user.id))
    primary = [s for s in items if not s.get("is_backup")]
    picked_days = sorted({s["day_index"] for s in primary})
    di = picked_days[0] if picked_days else 0
    return await walk(di, request, user)


@router.get("/walk/{day_index}", response_class=HTMLResponse)
async def walk(day_index: int, request: Request, user: CurrentUser = Depends(current_user)):
    if day_index not in DAY_INDEX.values():
        raise HTTPException(status_code=404)
    items = annotate_with_conflicts(itinerary_sessions(user.id))
    hops = _build_hops(items, day_index)
    # Days with any picks — for the day selector.
    primary = [s for s in items if not s.get("is_backup")]
    pick_counts: dict[int, int] = {}
    for s in primary:
        pick_counts[s["day_index"]] = pick_counts.get(s["day_index"], 0) + 1
    days_meta = [{
        "index": idx,
        "short": DAY_SHORT.get(idx, label),
        "date_iso": DAY_DATE.get(idx),
        "count": pick_counts.get(idx, 0),
    } for label, idx in sorted(DAY_INDEX.items(), key=lambda kv: kv[1])]
    ctx = {
        "request": request,
        "user": user,
        "day_index": day_index,
        "day_short": DAY_SHORT.get(day_index, ""),
        "date_iso": DAY_DATE.get(day_index),
        "hops": hops,
        "days_meta": days_meta,
        "floors": venue_floors(),
        "venue": venue_info(),
        "all_rooms": venue_rooms(),
        "total_picks": sum(pick_counts.values()),
    }
    return templates.TemplateResponse("walk.html", ctx)
