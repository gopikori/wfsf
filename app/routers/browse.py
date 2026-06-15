from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.auth import CurrentUser
from app.deps import current_user
from app.queries import (
    add_itinerary,
    faceted_counts,
    get_session,
    itinerary_ids,
    itinerary_map,
    list_sessions,
    remove_itinerary,
)
from app.templating import is_htmx, templates

router = APIRouter()


def _parse_multi(values: list[str] | None) -> list[str]:
    return [v for v in (values or []) if v.strip()]


def _read_filters(request: Request) -> dict:
    params = request.query_params
    day_indexes = [int(v) for v in params.getlist("day") if v.lstrip("-").isdigit()]
    tracks = _parse_multi(params.getlist("track"))
    types = _parse_multi(params.getlist("type"))
    rooms = _parse_multi(params.getlist("room"))
    search = (params.get("q") or "").strip() or None
    return {
        "day": day_indexes,
        "track": tracks,
        "type": types,
        "room": rooms,
        "search": search,
    }


def _slot_anchor(day_index: int, start_time: str | None) -> str:
    t = (start_time or "tba").replace(":", "")
    return f"slot-{day_index}-{t}"


def _to_minutes(hm: str | None) -> int | None:
    if not hm or ":" not in hm:
        return None
    try:
        h, m = hm.split(":", 1)
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def _slot_state(primary_count: int, backup_count: int, is_past: bool) -> str:
    if is_past:
        return "past"
    if primary_count >= 2:
        return "conflict"
    if primary_count == 1:
        return "primary"
    if backup_count >= 1:
        return "backup"
    return "empty"


def _group_by_day_slot(sessions: list[dict], pick_map: dict[int, bool]) -> list[dict]:
    days: dict[int, dict] = {}
    for s in sessions:
        di = s["day_index"]
        d = days.get(di)
        if d is None:
            d = days[di] = {
                "day_index": di,
                "day": s["day"],
                "day_short": s["day_short"],
                "date_iso": s["date_iso"],
                "_slots": {},
            }
        key = s["start_time"] or ""
        slot = d["_slots"].get(key)
        if slot is None:
            slot = d["_slots"][key] = {
                "time": key or None,
                "anchor": _slot_anchor(di, key),
                "sessions": [],
            }
        slot["sessions"].append(s)
    today_iso = date.today().isoformat()
    now_min = datetime.now().hour * 60 + datetime.now().minute
    out = []
    for di in sorted(days.keys()):
        d = days[di]
        ordered = [d["_slots"][k] for k in sorted(d["_slots"].keys())]
        starts = [_to_minutes(s["time"]) for s in ordered]
        for i, slot in enumerate(ordered):
            slot["count"] = len(slot["sessions"])
            primaries = 0
            backups = 0
            for s in slot["sessions"]:
                if s["id"] in pick_map:
                    if pick_map[s["id"]]:
                        backups += 1
                    else:
                        primaries += 1
            is_past = bool(d["date_iso"] and d["date_iso"] < today_iso) or (
                d["date_iso"] == today_iso and starts[i] is not None and starts[i] < now_min
            )
            slot["primary_count"] = primaries
            slot["backup_count"] = backups
            slot["state"] = _slot_state(primaries, backups, is_past)
            cur = starts[i]
            nxt = starts[i + 1] if i + 1 < len(starts) else None
            if cur is not None and nxt is not None and nxt > cur:
                slot["span_min"] = nxt - cur
            elif cur is not None:
                slot["span_min"] = 30
            else:
                slot["span_min"] = 30
        total_span = sum(s["span_min"] for s in ordered) or 1
        for slot in ordered:
            slot["span_pct"] = round(100 * slot["span_min"] / total_span, 3)
        out.append({
            "day_index": d["day_index"],
            "day": d["day"],
            "day_short": d["day_short"],
            "date_iso": d["date_iso"],
            "slots": ordered,
        })
    return out


def _active_chips(active: dict) -> list[dict]:
    """Flatten active filters into a chip strip with remove URLs."""
    out: list[dict] = []
    for d in active.get("day") or []:
        out.append({"dim": "day", "value": str(d), "label": f"Day {int(d)+1}"})
    for v in active.get("type") or []:
        out.append({"dim": "type", "value": v, "label": v})
    for v in active.get("track") or []:
        out.append({"dim": "track", "value": v, "label": v})
    for v in active.get("room") or []:
        out.append({"dim": "room", "value": v, "label": v})
    return out


@router.get("/browse", response_class=HTMLResponse)
async def browse(request: Request, user: CurrentUser = Depends(current_user)):
    active = _read_filters(request)
    sessions = list_sessions(
        day_indexes=active["day"] or None,
        tracks=active["track"] or None,
        types=active["type"] or None,
        rooms=active["room"] or None,
        search=active["search"],
    )
    saved_ids = itinerary_ids(user.id)
    pick_map = itinerary_map(user.id)
    facets = faceted_counts(active)
    grouped = _group_by_day_slot(sessions, pick_map)
    ctx = {
        "request": request,
        "user": user,
        "sessions": sessions,
        "days_grouped": grouped,
        "facets": facets,
        "saved_ids": saved_ids,
        "active": {**active, "q": active["search"] or ""},
        "active_chips": _active_chips(active),
        "active_count": sum(len(active.get(k) or []) for k in ("day", "track", "type", "room")),
        "total_count": len(sessions),
    }
    if is_htmx(request):
        return templates.TemplateResponse("partials/results_region.html", ctx)
    return templates.TemplateResponse("browse.html", ctx)


@router.get("/browse/facets", response_class=HTMLResponse)
async def browse_facets(request: Request, user: CurrentUser = Depends(current_user)):
    active = _read_filters(request)
    facets = faceted_counts(active)
    ctx = {
        "request": request,
        "user": user,
        "facets": facets,
        "active": {**active, "q": active["search"] or ""},
        "active_count": sum(len(active.get(k) or []) for k in ("day", "track", "type", "room")),
    }
    return templates.TemplateResponse("partials/filter_sheet.html", ctx)


@router.get("/session/{session_id}", response_class=HTMLResponse)
async def session_detail(session_id: int, request: Request, user: CurrentUser = Depends(current_user)):
    s = get_session(session_id)
    if not s:
        raise HTTPException(status_code=404)
    saved_ids = itinerary_ids(user.id)
    ctx = {"request": request, "user": user, "session": s, "saved_ids": saved_ids}
    return templates.TemplateResponse("session_detail.html", ctx)


@router.post("/session/{session_id}/save", response_class=HTMLResponse)
async def save_session(session_id: int, request: Request, user: CurrentUser = Depends(current_user)):
    s = get_session(session_id)
    if not s:
        raise HTTPException(status_code=404)
    add_itinerary(user.id, session_id)
    saved_ids = itinerary_ids(user.id)
    ctx = {"request": request, "user": user, "session": s, "saved_ids": saved_ids}
    return templates.TemplateResponse("partials/save_button.html", ctx)


@router.post("/session/{session_id}/unsave", response_class=HTMLResponse)
async def unsave_session(session_id: int, request: Request, user: CurrentUser = Depends(current_user)):
    s = get_session(session_id)
    if not s:
        raise HTTPException(status_code=404)
    remove_itinerary(user.id, session_id)
    saved_ids = itinerary_ids(user.id)
    ctx = {"request": request, "user": user, "session": s, "saved_ids": saved_ids}
    return templates.TemplateResponse("partials/save_button.html", ctx)
