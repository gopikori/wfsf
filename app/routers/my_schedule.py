from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.auth import CurrentUser
from app.deps import current_user
from app.queries import (
    annotate_with_conflicts,
    itinerary_sessions,
    remove_itinerary,
    session_changes_for_user,
    set_backup,
)
from app.sched import DAY_DATE, DAY_INDEX, DAY_SHORT
from app.templating import templates

router = APIRouter()


def _by_day(items: list[dict]) -> list[dict]:
    days = []
    for label, idx in DAY_INDEX.items():
        day_items = [s for s in items if s["day_index"] == idx]
        if not day_items:
            continue
        days.append({
            "day_index": idx,
            "label": label,
            "short": DAY_SHORT.get(idx, label),
            "date_iso": DAY_DATE.get(idx),
            "sessions": day_items,
        })
    return days


@router.get("/my-schedule", response_class=HTMLResponse)
async def my_schedule(request: Request, user: CurrentUser = Depends(current_user)):
    items = annotate_with_conflicts(itinerary_sessions(user.id))
    days = _by_day(items)
    changes = session_changes_for_user(user.id)
    ctx = {"request": request, "user": user, "days": days, "total": len(items), "changes": changes}
    return templates.TemplateResponse("my_schedule.html", ctx)


@router.post("/my-schedule/{session_id}/remove", response_class=HTMLResponse)
async def my_schedule_remove(session_id: int, request: Request, user: CurrentUser = Depends(current_user)):
    remove_itinerary(user.id, session_id)
    items = annotate_with_conflicts(itinerary_sessions(user.id))
    days = _by_day(items)
    changes = session_changes_for_user(user.id)
    ctx = {"request": request, "user": user, "days": days, "total": len(items), "changes": changes}
    return templates.TemplateResponse("partials/my_schedule_body.html", ctx)


@router.post("/my-schedule/{session_id}/backup", response_class=HTMLResponse)
async def toggle_backup(session_id: int, request: Request, user: CurrentUser = Depends(current_user)):
    items = itinerary_sessions(user.id)
    target = next((x for x in items if x["id"] == session_id), None)
    if not target:
        raise HTTPException(status_code=404)
    set_backup(user.id, session_id, not target.get("is_backup", False))
    items = annotate_with_conflicts(itinerary_sessions(user.id))
    days = _by_day(items)
    changes = session_changes_for_user(user.id)
    ctx = {"request": request, "user": user, "days": days, "total": len(items), "changes": changes}
    return templates.TemplateResponse("partials/my_schedule_body.html", ctx)
