"""Venue map data loader. Reads app/static/venue/venue.json once at import
and exposes lookup helpers for joining session.room → floor + x/y centroid."""
from __future__ import annotations

import json
import pathlib
from functools import lru_cache
from typing import Any

_VENUE_JSON = pathlib.Path(__file__).resolve().parent / "static" / "venue" / "venue.json"


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    with _VENUE_JSON.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def venue_info() -> dict[str, Any]:
    return _data().get("venue", {})


def floors() -> dict[str, dict[str, Any]]:
    return _data().get("floors", {})


def floor(level: int | str) -> dict[str, Any] | None:
    return floors().get(str(level))


def rooms() -> dict[str, dict[str, Any]]:
    return _data().get("rooms", {})


def room(name: str | None) -> dict[str, Any] | None:
    if not name:
        return None
    return rooms().get(name)


def locate(session_room: str | None) -> dict[str, Any] | None:
    """Return {floor, x_pct, y_pct, label_on_plan?} for a session's room, or
    None if the room isn't mapped (off-venue, missing data, etc.)."""
    r = room(session_room)
    if not r:
        return None
    return {
        "floor": r["floor"],
        "x_pct": r["x_pct"],
        "y_pct": r["y_pct"],
        "label_on_plan": r.get("label_on_plan"),
    }
