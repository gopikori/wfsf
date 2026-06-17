from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.glance import glance_grid
from app.queries import user_by_share_token
from app.templating import templates

router = APIRouter()


@router.get("/s/{token}", response_class=HTMLResponse)
async def shared_schedule(token: str, request: Request):
    owner = user_by_share_token(token)
    if not owner:
        raise HTTPException(status_code=404)
    ctx = {
        "request": request,
        "user": None,  # public page: no app shell / nav
        "owner_email": owner["email"],
        "grid": glance_grid(owner["id"]),
    }
    return templates.TemplateResponse("share.html", ctx)
