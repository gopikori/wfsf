from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.auth import CurrentUser
from app.deps import current_user
from app.queries import itinerary_ids, list_speakers, speaker_with_sessions
from app.templating import is_htmx, templates

router = APIRouter()


@router.get("/speakers", response_class=HTMLResponse)
async def speakers_list(request: Request, user: CurrentUser = Depends(current_user)):
    search = (request.query_params.get("q") or "").strip() or None
    items = list_speakers(search=search)
    ctx = {"request": request, "user": user, "speakers": items, "q": search or "", "total": len(items)}
    if is_htmx(request) and request.headers.get("hx-target") == "speakers-list":
        return templates.TemplateResponse("partials/speakers_list.html", ctx)
    return templates.TemplateResponse("speakers.html", ctx)


@router.get("/speakers/{name}", response_class=HTMLResponse)
async def speaker_detail(name: str, request: Request, user: CurrentUser = Depends(current_user)):
    sp = speaker_with_sessions(name)
    if not sp:
        raise HTTPException(status_code=404)
    saved_ids = itinerary_ids(user.id)
    ctx = {"request": request, "user": user, "speaker": sp, "saved_ids": saved_ids}
    return templates.TemplateResponse("speaker_detail.html", ctx)
