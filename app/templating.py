from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

_jinja = Jinja2Templates(directory=str(TEMPLATE_DIR))


_static_hash_cache: dict[str, str] = {}


def static_v(rel_path: str) -> str:
    """Return a versioned URL for a file under app/static/.

    The version is the first 10 chars of the file's SHA1 hash, computed once
    per process per (path, mtime) pair, and cached. Any edit changes mtime →
    cache miss → new hash → new URL. The Cache-Control middleware can then
    mark the response as immutable.

    Usage in templates: {{ static_v('css/app.css') }}
    """
    clean = rel_path.lstrip("/").removeprefix("static/")
    fs_path = STATIC_DIR / clean
    try:
        mtime_ns = fs_path.stat().st_mtime_ns
    except OSError:
        return f"/static/{clean}"
    key = f"{clean}|{mtime_ns}"
    digest = _static_hash_cache.get(key)
    if digest is None:
        h = hashlib.sha1()
        with fs_path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        digest = h.hexdigest()[:10]
        _static_hash_cache[key] = digest
    return f"/static/{clean}?v={digest}"


class _Templates:
    def __init__(self, j):
        self._j = j

    @property
    def env(self):
        return self._j.env

    def TemplateResponse(self, name_or_request, context_or_name=None, status_code: int = 200):
        if isinstance(name_or_request, str):
            name = name_or_request
            context = context_or_name or {}
            request = context.get("request")
        else:
            request = name_or_request
            name = context_or_name
            context = {}
        return self._j.TemplateResponse(request=request, name=name, context=context, status_code=status_code)


templates = _Templates(_jinja)


_TRACK_PALETTE = [
    ("agents", "#ff7d3b"),
    ("evals", "#22d3ee"),
    ("rag", "#a78bfa"),
    ("search", "#f472b6"),
    ("voice", "#34d399"),
    ("vision", "#60a5fa"),
    ("security", "#f87171"),
    ("graphs", "#fbbf24"),
    ("design", "#f472b6"),
]

_STATIC_COLORS = [
    "#ff5d29", "#3ab0ff", "#9d6dff", "#21c389", "#f5b400", "#ec4899",
    "#0ea5e9", "#84cc16", "#f97316", "#14b8a6", "#a855f7", "#f43f5e",
    "#22c55e", "#0d9488", "#f59e0b", "#8b5cf6", "#06b6d4", "#fb7185",
    "#10b981", "#eab308", "#6366f1", "#d946ef", "#0284c7", "#65a30d",
]


def track_color(track: str | None) -> str:
    if not track:
        return "#7a7a7a"
    key = track.lower()
    for needle, color in _TRACK_PALETTE:
        if needle in key:
            return color
    bucket = sum(ord(c) for c in key) % len(_STATIC_COLORS)
    return _STATIC_COLORS[bucket]


_HHMM_RE = re.compile(r"^(\d{2}):(\d{2})$")


def display_time(hhmm: str | None) -> str:
    if not hhmm:
        return ""
    m = _HHMM_RE.match(hhmm)
    if not m:
        return hhmm
    h, mi = int(m.group(1)), int(m.group(2))
    suffix = "am" if h < 12 else "pm"
    hh = h % 12
    if hh == 0:
        hh = 12
    return f"{hh}:{mi:02d}{suffix}"


def status_class(status: str | None) -> str:
    mapping = {
        "confirmed": "status-confirmed",
        "tentative": "status-tentative",
        "hold": "status-hold",
        "open": "status-open",
    }
    return mapping.get((status or "").lower(), "status-other")


def is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


def hx_target(request: Request) -> str | None:
    return request.headers.get("hx-target")


def twitter_handle(value: str | None) -> str:
    if not value:
        return ""
    v = value.strip().lstrip("@")
    if v.startswith("http"):
        v = v.rstrip("/").rsplit("/", 1)[-1]
    return v[:40]


templates.env.filters["track_color"] = track_color
templates.env.filters["display_time"] = display_time
templates.env.filters["status_class"] = status_class
templates.env.filters["twitter_handle"] = twitter_handle

def last_sync_label() -> str | None:
    """Return a short label like 'Updated 12 min ago' for the last sessions sync, or None."""
    from app.queries import last_sessions_sync_at

    raw = last_sessions_sync_at()
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw.replace(" ", "T"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None
    delta = datetime.now(timezone.utc) - ts
    secs = int(delta.total_seconds())
    if secs < 60:
        return "Updated just now"
    mins = secs // 60
    if mins < 60:
        return f"Updated {mins} min ago"
    hrs = mins // 60
    if hrs < 24:
        return f"Updated {hrs}h ago"
    days = hrs // 24
    return f"Updated {days}d ago"


def app_base_url() -> str:
    """Return the deployed base URL (no trailing slash) for absolute meta tag URLs."""
    from app.config import settings

    return (settings.APP_BASE_URL or "").rstrip("/")


templates.env.globals["static_v"] = static_v
templates.env.globals["last_sync_label"] = last_sync_label
templates.env.globals["app_base_url"] = app_base_url
