from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from starlette.datastructures import FormData

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
from app.sched import hhmm_to_minutes as _to_minutes
from app.sched import slot_state as _slot_state
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


def _filters_from_form(form: FormData) -> dict:
    """Same shape as _read_filters but sourced from the POST body (hx-include=#filters)."""
    return {
        "day": [int(v) for v in form.getlist("day") if str(v).lstrip("-").isdigit()],
        "track": [v for v in form.getlist("track") if v and v.strip()],
        "type": [v for v in form.getlist("type") if v and v.strip()],
        "room": [v for v in form.getlist("room") if v and v.strip()],
        "search": (form.get("q") or "").strip() or None,
    }


def _chrome_for(session: dict, active: dict, user_id: int) -> dict | None:
    """Recompute the slot data for the day containing `session` under the
    user's current filter set. Returns the day dict the chrome partial expects,
    or None if the day isn't in scope (e.g., filtered out, or no filter form
    was posted so the request didn't come from the browse list)."""
    day_idx = session.get("day_index")
    if day_idx is None:
        return None
    filter_days = active.get("day") or []
    if filter_days and day_idx not in filter_days:
        return None
    sessions = list_sessions(
        day_indexes=[day_idx],
        tracks=active["track"] or None,
        types=active["type"] or None,
        rooms=active["room"] or None,
        search=active["search"],
    )
    if not sessions:
        return None
    grouped = _group_by_day_slot(sessions, itinerary_map(user_id))
    return grouped[0] if grouped else None


async def _save_response_ctx(request: Request, s: dict, user: CurrentUser) -> dict:
    saved_ids = itinerary_ids(user.id)
    form = await request.form()
    # 'q' is always present in #filters; its absence signals the POST didn't
    # come from the browse list (e.g., session_detail page) — skip OOB chrome.
    chrome_day = None
    facets_data = None
    if "q" in form:
        active = _filters_from_form(form)
        chrome_day = _chrome_for(s, active, user.id)
        if chrome_day is not None:
            facets_data = faceted_counts(active)
    return {
        "request": request,
        "user": user,
        "session": s,
        "saved_ids": saved_ids,
        "chrome_day": chrome_day,
        "facets": facets_data,
    }


@router.post("/session/{session_id}/save", response_class=HTMLResponse)
async def save_session(session_id: int, request: Request, user: CurrentUser = Depends(current_user)):
    s = get_session(session_id)
    if not s:
        raise HTTPException(status_code=404)
    add_itinerary(user.id, session_id)
    ctx = await _save_response_ctx(request, s, user)
    return templates.TemplateResponse("partials/save_button.html", ctx)


@router.post("/session/{session_id}/unsave", response_class=HTMLResponse)
async def unsave_session(session_id: int, request: Request, user: CurrentUser = Depends(current_user)):
    s = get_session(session_id)
    if not s:
        raise HTTPException(status_code=404)
    remove_itinerary(user.id, session_id)
    ctx = await _save_response_ctx(request, s, user)
    return templates.TemplateResponse("partials/save_button.html", ctx)
