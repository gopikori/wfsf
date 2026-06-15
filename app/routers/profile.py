from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from app.auth import CurrentUser
from app.db import db, tx
from app.deps import current_user
from app.queries import distinct_facets
from app.templating import templates

router = APIRouter()


def _get_prefs(user_id: int) -> dict:
    with db() as conn:
        row = conn.execute(
            "SELECT interest_tracks_json, reminders_enabled, onboarded FROM user_prefs WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return {"interests": [], "reminders": False, "onboarded": False}
    try:
        interests = json.loads(row["interest_tracks_json"] or "[]")
    except json.JSONDecodeError:
        interests = []
    return {
        "interests": interests,
        "reminders": bool(row["reminders_enabled"]),
        "onboarded": bool(row["onboarded"]),
    }


def _save_prefs(user_id: int, interests: list[str], reminders: bool, onboarded: bool) -> None:
    with tx() as conn:
        conn.execute(
            """INSERT INTO user_prefs(user_id, interest_tracks_json, reminders_enabled, onboarded, updated_at)
               VALUES(?,?,?,?, datetime('now'))
               ON CONFLICT(user_id) DO UPDATE SET
                 interest_tracks_json=excluded.interest_tracks_json,
                 reminders_enabled=excluded.reminders_enabled,
                 onboarded=excluded.onboarded,
                 updated_at=datetime('now')""",
            (user_id, json.dumps(interests), 1 if reminders else 0, 1 if onboarded else 0),
        )


@router.get("/profile", response_class=HTMLResponse)
async def profile(request: Request, user: CurrentUser = Depends(current_user)):
    prefs = _get_prefs(user.id)
    facets = distinct_facets()
    ctx = {"request": request, "user": user, "prefs": prefs, "facets": facets, "saved": False}
    return templates.TemplateResponse("profile.html", ctx)


@router.post("/profile", response_class=HTMLResponse)
async def update_profile(
    request: Request,
    user: CurrentUser = Depends(current_user),
    reminders: str | None = Form(None),
):
    form = await request.form()
    tracks = [v for v in form.getlist("interest") if v]
    _save_prefs(user.id, tracks, reminders == "on", onboarded=True)
    prefs = _get_prefs(user.id)
    facets = distinct_facets()
    ctx = {"request": request, "user": user, "prefs": prefs, "facets": facets, "saved": True}
    return templates.TemplateResponse("profile.html", ctx)


@router.get("/onboarding", response_class=HTMLResponse)
async def onboarding(request: Request, user: CurrentUser = Depends(current_user)):
    prefs = _get_prefs(user.id)
    facets = distinct_facets()
    ctx = {"request": request, "user": user, "prefs": prefs, "facets": facets}
    return templates.TemplateResponse("onboarding.html", ctx)


@router.post("/onboarding", response_class=HTMLResponse)
async def submit_onboarding(request: Request, user: CurrentUser = Depends(current_user)):
    form = await request.form()
    tracks = [v for v in form.getlist("interest") if v]
    prev = _get_prefs(user.id)
    _save_prefs(user.id, tracks, prev["reminders"], onboarded=True)
    resp = HTMLResponse("")
    resp.headers["HX-Redirect"] = "/browse"
    return resp
