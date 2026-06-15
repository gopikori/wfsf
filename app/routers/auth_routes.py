from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import turnstile
from app.auth import invalidate_session, request_otp, verify_otp
from app.config import settings
from app.deps import current_user_optional
from app.templating import templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user = await current_user_optional(request)
    if user:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "user": None, "step": "email", "email": "", "message": None},
    )


@router.post("/login/request", response_class=HTMLResponse)
async def login_request(
    request: Request,
    email: str = Form(...),
    cf_turnstile_response: str = Form("", alias="cf-turnstile-response"),
):
    ip = request.client.host if request.client else ""
    if not await turnstile.verify(cf_turnstile_response, ip=ip):
        return templates.TemplateResponse(
            "partials/login_form.html",
            {
                "request": request,
                "step": "email",
                "email": email.strip().lower(),
                "message": "Please complete the verification and try again.",
                "ok": False,
            },
        )
    ok, msg, _dev = request_otp(email, ip=ip)
    step = "code" if ok else "email"
    return templates.TemplateResponse(
        "partials/login_form.html",
        {"request": request, "step": step, "email": email.strip().lower(), "message": msg, "ok": ok},
    )


@router.post("/login/verify", response_class=HTMLResponse)
async def login_verify(request: Request, email: str = Form(...), code: str = Form(...)):
    ok, msg, user, token = verify_otp(email, code, request=request)
    if not ok or not user or not token:
        return templates.TemplateResponse(
            "partials/login_form.html",
            {"request": request, "step": "code", "email": email, "message": msg, "ok": False},
        )
    response = HTMLResponse("")
    response.headers["HX-Redirect"] = "/"
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        token,
        max_age=60 * 60 * 24 * settings.SESSION_TTL_DAYS,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout")
async def logout(request: Request):
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    invalidate_session(token)
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
    return resp
