from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.db import init_schema
from app.deps import current_user_optional
from app.routers import admin, auth_routes, browse, dayof, my_schedule, profile, speakers
from app.sync import current_interval_minutes, sync_all
from app.templating import templates

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("wfsf")

scheduler: AsyncIOScheduler | None = None


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=()",
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "img-src 'self' data: https:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'",
        )
        return response


class CacheControlMiddleware(BaseHTTPMiddleware):
    """Static assets are content-hashed (?v=…) so they're safe to cache forever.
    Everything else (HTML, JSON, partials) must revalidate so UI changes ship instantly."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if "cache-control" in response.headers:
            return response
        path = request.url.path
        if path.startswith("/static/") and request.url.query and "v=" in request.url.query:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        else:
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response


def _run_sync_job():
    try:
        result = sync_all()
        logger.info("sync_all result=%s", result)
    except Exception:  # noqa: BLE001 - log but never crash the scheduler
        logger.exception("Scheduled sync failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_schema()
    try:
        result = sync_all()
        logger.info("initial sync result=%s", result)
    except Exception:  # noqa: BLE001
        logger.exception("Initial sync failed (continuing without data)")
    global scheduler
    scheduler = AsyncIOScheduler()
    interval = current_interval_minutes()
    scheduler.add_job(
        _run_sync_job,
        trigger=IntervalTrigger(minutes=interval),
        id="schedule_sync",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info("Scheduler started (interval=%dm)", interval)
    try:
        yield
    finally:
        if scheduler:
            scheduler.shutdown(wait=False)


app = FastAPI(title="WFSF — AI Engineer World's Fair 2026", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CacheControlMiddleware)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth_routes.router)
app.include_router(browse.router)
app.include_router(my_schedule.router)
app.include_router(speakers.router)
app.include_router(profile.router)
app.include_router(dayof.router)
app.include_router(admin.router)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    user = await current_user_optional(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    today = date.today()
    try:
        start = date.fromisoformat(settings.EVENT_START)
        end = date.fromisoformat(settings.EVENT_END)
        if start <= today <= end:
            return RedirectResponse("/day-of", status_code=302)
    except ValueError:
        pass
    return RedirectResponse("/browse", status_code=302)


@app.get("/healthz")
async def health():
    return {"status": "ok"}


@app.get("/manifest.webmanifest")
async def manifest():
    return {
        "name": "WFSF — AI Engineer World's Fair 2026",
        "short_name": "WFSF",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0b0b10",
        "theme_color": "#ff5d29",
        "icons": [
            {"src": "/static/icons/icon-192.svg", "sizes": "192x192", "type": "image/svg+xml"},
            {"src": "/static/icons/icon-512.svg", "sizes": "512x512", "type": "image/svg+xml"},
        ],
    }


@app.get("/service-worker.js")
async def service_worker():
    sw = (
        "const CACHE='wfsf-v1';\n"
        "const SHELL=['/', '/browse', '/my-schedule', '/static/css/app.css', '/static/js/app.js'];\n"
        "self.addEventListener('install', e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL).catch(()=>{}))); self.skipWaiting(); });\n"
        "self.addEventListener('activate', e => { e.waitUntil(self.clients.claim()); });\n"
        "self.addEventListener('fetch', e => {\n"
        "  const req = e.request;\n"
        "  if (req.method !== 'GET') return;\n"
        "  e.respondWith(\n"
        "    fetch(req).then(res => { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy).catch(()=>{})); return res; })\n"
        "      .catch(() => caches.match(req).then(m => m || caches.match('/browse')))\n"
        "  );\n"
        "});\n"
    )
    return Response(content=sw, media_type="application/javascript")


@app.exception_handler(404)
async def not_found(request: Request, exc):
    return templates.TemplateResponse("404.html", {"request": request, "user": await current_user_optional(request)}, status_code=404)
