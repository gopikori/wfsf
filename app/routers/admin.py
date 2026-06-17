from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.auth import CurrentUser, invalidate_user_sessions
from app.db import db, tx
from app.deps import current_admin
from app.templating import is_htmx, templates

router = APIRouter()


def _audit(conn, actor_id: int, target_id: int | None, action: str, detail: str | None = None) -> None:
    conn.execute(
        "INSERT INTO admin_audit(actor_user_id, target_user_id, action, detail) VALUES(?, ?, ?, ?)",
        (actor_id, target_id, action, detail),
    )


def _active_admin_count(conn) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM users WHERE role='admin' AND status='active'"
    ).fetchone()
    return int(row["c"])


def _list_users(conn, search: str | None = None) -> list[dict]:
    sql = """
        SELECT u.id, u.email, u.role, u.status, u.created_at, u.last_login_at,
               COALESCE(slot_counts.booked_timeslots, 0) AS booked_timeslots
        FROM users u
        LEFT JOIN (
            SELECT it.user_id,
                   COUNT(DISTINCT cs.day_index || '|' || COALESCE(cs.start_time, '') || '|' || COALESCE(cs.end_time, '')) AS booked_timeslots
            FROM itinerary it
            JOIN conf_sessions cs ON cs.id = it.session_id
            WHERE cs.deleted = 0
            GROUP BY it.user_id
        ) slot_counts ON slot_counts.user_id = u.id
    """
    params: list = []
    if search:
        sql += " WHERE lower(u.email) LIKE ?"
        params.append(f"%{search.strip().lower()}%")
    sql += " ORDER BY u.created_at DESC LIMIT 500"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _stats(conn) -> dict:
    total = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    active = conn.execute("SELECT COUNT(*) AS c FROM users WHERE status='active'").fetchone()["c"]
    disabled = conn.execute("SELECT COUNT(*) AS c FROM users WHERE status='disabled'").fetchone()["c"]
    admins = conn.execute("SELECT COUNT(*) AS c FROM users WHERE role='admin'").fetchone()["c"]
    return {"total": total, "active": active, "disabled": disabled, "admins": admins}


def _audit_log(conn, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT a.id, a.action, a.detail, a.created_at, "
        "ac.email AS actor_email, tg.email AS target_email "
        "FROM admin_audit a "
        "JOIN users ac ON ac.id = a.actor_user_id "
        "LEFT JOIN users tg ON tg.id = a.target_user_id "
        "ORDER BY a.id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/admin", response_class=HTMLResponse)
async def admin_home(request: Request, admin: CurrentUser = Depends(current_admin)):
    search = (request.query_params.get("q") or "").strip() or None
    with db() as conn:
        users = _list_users(conn, search)
        stats = _stats(conn)
        log = _audit_log(conn)
    ctx = {"request": request, "user": admin, "users": users, "stats": stats, "audit": log, "q": search or ""}
    if is_htmx(request) and request.headers.get("hx-target") == "user-list":
        return templates.TemplateResponse("partials/admin_user_list.html", ctx)
    return templates.TemplateResponse("admin.html", ctx)


def _load_target(conn, user_id: int) -> dict:
    row = conn.execute("SELECT id, email, role, status FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404)
    return dict(row)


@router.post("/admin/users/{user_id}/disable", response_class=HTMLResponse)
async def disable_user(user_id: int, request: Request, admin: CurrentUser = Depends(current_admin)):
    with tx() as conn:
        target = _load_target(conn, user_id)
        if target["role"] == "admin" and _active_admin_count(conn) <= 1 and target["status"] == "active":
            raise HTTPException(status_code=400, detail="Cannot disable the last remaining active admin.")
        conn.execute("UPDATE users SET status='disabled' WHERE id = ?", (user_id,))
        _audit(conn, admin.id, user_id, "disable_user", f"{target['email']}")
    invalidate_user_sessions(user_id)
    return await admin_home(request, admin)


@router.post("/admin/users/{user_id}/enable", response_class=HTMLResponse)
async def enable_user(user_id: int, request: Request, admin: CurrentUser = Depends(current_admin)):
    with tx() as conn:
        target = _load_target(conn, user_id)
        conn.execute("UPDATE users SET status='active' WHERE id = ?", (user_id,))
        _audit(conn, admin.id, user_id, "enable_user", f"{target['email']}")
    return await admin_home(request, admin)


@router.post("/admin/users/{user_id}/promote", response_class=HTMLResponse)
async def promote_user(user_id: int, request: Request, admin: CurrentUser = Depends(current_admin)):
    with tx() as conn:
        target = _load_target(conn, user_id)
        if target["status"] != "active":
            raise HTTPException(status_code=400, detail="Cannot promote a disabled user.")
        conn.execute("UPDATE users SET role='admin' WHERE id = ?", (user_id,))
        _audit(conn, admin.id, user_id, "promote_admin", f"{target['email']}")
    return await admin_home(request, admin)


@router.post("/admin/users/{user_id}/demote", response_class=HTMLResponse)
async def demote_user(user_id: int, request: Request, admin: CurrentUser = Depends(current_admin)):
    with tx() as conn:
        target = _load_target(conn, user_id)
        if target["role"] == "admin" and _active_admin_count(conn) <= 1 and target["status"] == "active":
            raise HTTPException(status_code=400, detail="Cannot demote the last remaining active admin.")
        conn.execute("UPDATE users SET role='user' WHERE id = ?", (user_id,))
        _audit(conn, admin.id, user_id, "demote_admin", f"{target['email']}")
    return await admin_home(request, admin)


@router.post("/admin/users/invite", response_class=HTMLResponse)
async def invite_user(
    request: Request,
    email: str = Form(...),
    role: str = Form("user"),
    admin: CurrentUser = Depends(current_admin),
):
    email = email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email")
    if role not in ("user", "admin"):
        role = "user"
    with tx() as conn:
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if row:
            conn.execute("UPDATE users SET role = ?, status='active' WHERE id = ?", (role, row["id"]))
            target_id = row["id"]
            action = "update_user"
        else:
            cur = conn.execute(
                "INSERT INTO users(email, role, status) VALUES(?, ?, 'active') RETURNING id", (email, role)
            )
            target_id = cur.fetchone()["id"]
            action = "create_user"
        _audit(conn, admin.id, target_id, action, f"{email} as {role}")
    return await admin_home(request, admin)
