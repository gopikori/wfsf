from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.auth import CurrentUser, resolve_session
from app.config import settings


def _is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


async def current_user_optional(request: Request) -> CurrentUser | None:
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    return resolve_session(token)


async def current_user(request: Request) -> CurrentUser:
    user = await current_user_optional(request)
    if not user:
        if _is_htmx(request):
            raise HTTPException(status_code=401, headers={"HX-Redirect": "/login"})
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/login"})
    return user


async def current_admin(request: Request) -> CurrentUser:
    user = await current_user(request)
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user
