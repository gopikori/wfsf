# PROJECT_UNDERSTANDING.md — WFSF

> A deep reference for the WFSF codebase as it stands today. Origin → architecture → every layer → operations. Useful as both an onboarding doc and a recovery doc if you come back to this in a year.

---

## Table of contents

1. [Executive summary](#1-executive-summary)
2. [Origin & scope](#2-origin--scope)
3. [Architecture at a glance](#3-architecture-at-a-glance)
4. [Tech stack](#4-tech-stack)
5. [Data model](#5-data-model)
6. [Domain logic](#6-domain-logic-day-times-conflicts-travel)
7. [Conference data sync pipeline](#7-conference-data-sync-pipeline)
8. [Authentication & sessions](#8-authentication--sessions)
9. [HTTP layer — routers, endpoints, middleware](#9-http-layer)
10. [Frontend architecture](#10-frontend-architecture)
11. [UI surfaces — page-by-page](#11-ui-surfaces--page-by-page)
12. [Configuration & environment](#12-configuration--environment)
13. [How to run, develop, and operate](#13-how-to-run-develop-and-operate)
14. [Security posture](#14-security-posture)
15. [Caching strategy](#15-caching-strategy)
16. [Performance & scale notes](#16-performance--scale-notes)
17. [Known gaps & tech debt](#17-known-gaps--tech-debt)
18. [File index](#18-file-index)

---

## 1. Executive summary

**WFSF** (World's Fair San Francisco) is a single-event, mobile-first web app that lets an attendee of the **AI Engineer World's Fair 2026** (San Francisco, Jun 29 – Jul 2) build, refine, and use a personal conference schedule from their phone. The conference has ~554 sessions across 9+ parallel tracks over 4 days; the official program is volatile (many sessions are `tentative`/`hold`); attendees can't see everything. WFSF is the planning + on-floor companion that solves that.

The app is a **server-rendered FastAPI app** with **HTMX-driven partial swaps**, **SQLite (WAL)** for storage, **Resend** for OTP email, and a **bottom-anchored, thumb-zone-first UI** with a drag-scrub timeline. There is no JS framework, no build step, no remote services beyond Resend. The whole thing is ~5,100 lines split roughly 1,500 Python / 1,500 CSS / 350 JS / 1,800 HTML.

The two distinguishing UX bets are:
- **Bottom-anchored "day chrome"** — date tiles, scrubber, and time-pill strip live in the thumb zone, sticky per day-block, replacing the more common top filter bar.
- **Per-slot state + drag-scrub scrubber** — every time slot in a day gets a state (`primary` / `backup` / `conflict` / `past` / `empty`) derived from the user's picks, surfaced as proportional colored segments in a 24px bar at the bottom you can drag to jump anywhere in the day.

---

## 2. Origin & scope

Original PRD lives in `PRD.md`. The condensed version:

### Problem
554 sessions, 300+ speakers, 9+ parallel tracks across 4 days. Attendees can't see everything, the schedule shifts daily, and no good mobile tool exists for solo itinerary planning.

### v1 goals
- Zero to a saved, conflict-free 4-day itinerary in **under 10 minutes**.
- Browsing 554 sessions feels effortless on a phone — one or two taps to add.
- Surface what breaks plans: **time conflicts**, **tentative sessions**, **room-to-room travel**.
- Reliable on flaky conference Wi-Fi (offline-capable via service worker).
- Day-of companion: what's on now, what's next, where to go, what changed.

### v1 explicit non-goals
- No AI/ML recommendations (manual browse + filters only).
- No social/collaboration (solo only).
- No multi-conference support.
- No ticketing, payments, or check-in.
- No calendar (`.ics`) export — intentional, so the app stays the single touchpoint.

### Personas
| Persona | Need |
|---|---|
| **Engineer** (primary) | Deep on 2–3 tracks (agents, evals, RAG, inference). Wants best talk in each slot + backups. |
| **Optimizer** | Zero schedule gaps/conflicts, minimal floor walking. |
| **Explorer** | Browsing by interest; fast discovery and easy bookmarking. |

### Success metrics
- % of logged-in users who add ≥3 sessions to My Schedule (activation).
- % with a saved itinerary covering ≥3 event days (core value).
- Median time login → first save (target < 2 min).
- % returning during the event window.
- Conflict-resolution rate (users who hit a clash and resolve vs. abandon).

---

## 3. Architecture at a glance

```
┌─────────────────────────────────────────────────────────────────┐
│                        Mobile browser                            │
│  ┌──────────┐  HTMX swaps  ┌──────────────┐  Pointer  ┌───────┐ │
│  │ Topbar   │ ───────────▶ │ session list │ ─────────▶│ app.js│ │
│  └──────────┘              │ slot bands   │            │ scrub │ │
│  ┌──────────────────┐      │ bottom chrome│◀───────────│ lens  │ │
│  │ Bottom-nav (PWA) │      └──────────────┘            └───────┘ │
│  └──────────────────┘                                            │
└────────────┬────────────────────────────────────────────────────┘
             │  HTTPS, httpOnly session cookie
             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI (uvicorn :10000)                    │
│  Middleware:  SecurityHeadersMiddleware → CacheControlMiddleware │
│  Mounts:      /static → StaticFiles                              │
│  Routers:     auth_routes · browse · my_schedule · speakers      │
│               profile · dayof · admin                            │
│  Helpers:     templating (Jinja env, filters, static_v)          │
│               deps (current_user, current_admin)                 │
│               auth (OTP issue/verify, session resolve)           │
│  Domain:      sched (DAY_INDEX, conflict, travel, normalize)     │
│               queries (read/write SQL, faceting)                 │
│               sync (httpx + MCP fallback)                        │
│  Background:  APScheduler — sync_all every 60m / 15m in event    │
│  Email:       Resend SDK                                         │
└────────────┬────────────────────────────────────────────────────┘
             │  sqlite3 (WAL, FK on)
             ▼
┌─────────────────────────────────────────────────────────────────┐
│                       SQLite — data/wfsf.db                      │
│  User-state: users · sessions · otp_codes · itinerary ·          │
│              user_prefs · admin_audit · rate_limit               │
│  Conf data:  conf_sessions · conf_speakers · session_changes     │
│  Ops:        sync_log                                            │
└─────────────────────────────────────────────────────────────────┘
             ▲
             │  daily fetch
             │
┌─────────────────────────────────────────────────────────────────┐
│  ai.engineer/worldsfair/2026   { sessions.json · speakers.json } │
│  + MCP JSON-RPC fallback for sessions                            │
└─────────────────────────────────────────────────────────────────┘
```

**Design constants**:
- **One writer**: SQLite WAL with `isolation_level=None` and explicit transactions via `app.db.tx()`. Reads use `app.db.db()`.
- **HTMX over JSON**: every route returns either a full HTML page or a partial template. There is no JSON API surface.
- **Server-rendered facets**: filter counts are computed per request from SQL (faceting rule: "all filters except this dimension"). No client-side filtering.
- **HTML lives in `templates/`; logic lives in routers**: templates have no business logic, only presentation + HTMX wiring.
- **Per-user data is scoped by cookie**: routes derive `user.id` from the session cookie via `Depends(current_user)`; no user-id ever travels from the client.

---

## 4. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Web framework | FastAPI 0.115+ on Starlette / uvicorn | Async lifespan, dependency-injected auth, fast iteration |
| Templates | Jinja2 3.1+ | Server-rendering, HTMX-friendly partials |
| Frontend | HTMX (vendored, no CDN) + minimal vanilla JS | Zero build step, hypermedia over JSON |
| DB | SQLite (stdlib) with WAL | Single-volume deploy, trivial backup, plenty of headroom |
| Email | Resend SDK | Simple OTP delivery |
| Hashing | argon2-cffi | Listed in deps but unused in current code; OTPs use HMAC-SHA256 against `SESSION_SECRET` |
| Scheduler | APScheduler (AsyncIOScheduler) | Periodic schedule sync |
| HTTP client | httpx | Sync client used in sync.py |
| Settings | pydantic-settings | `.env` loader with type coercion |
| Forms / files | python-multipart | Multipart parsing |
| Dep mgmt | uv via `pyproject.toml` | Fast install, modern lockfile |

**Not used**: AlpineJS (referenced in coding guidelines but not in the templates), service worker beyond a trivial cache shell, any JS bundler, any CSS preprocessor, any test framework (yet).

---

## 5. Data model

All 14 tables live in `app/db.py` (`_SCHEMA`). Bootstrap is idempotent: `init_schema()` runs at lifespan startup, then `_seed_admins()` upserts admin roles for emails in `ADMIN_EMAILS`.

### User-state tables

#### `users`
Identifies a person.
| Col | Type | Notes |
|---|---|---|
| `id` | INT PK | autoincrement |
| `email` | TEXT UNIQUE | normalized lowercase on insert |
| `role` | `'user'` \| `'admin'` | `CHECK` constraint enforced |
| `status` | `'active'` \| `'disabled'` | `CHECK` constraint enforced |
| `created_at`, `last_login_at` | TEXT (UTC ISO) | |

#### `sessions`
HTTP login sessions (cookie value `wfsf_session`).
| Col | Type | Notes |
|---|---|---|
| `id` | TEXT PK | 32-byte url-safe random (`secrets.token_urlsafe`) |
| `user_id` | FK → users | `ON DELETE CASCADE` |
| `expires_at` | TEXT | Default 30 days from issue |
| `user_agent`, `ip` | TEXT | Truncated to 300 / 64 chars |

#### `otp_codes`
Outstanding one-time codes.
| Col | Type | Notes |
|---|---|---|
| `email` | TEXT | Indexed for lookups |
| `code_hash` | TEXT | `HMAC-SHA256(SESSION_SECRET, "email|code")` hex |
| `expires_at` | TEXT | 10 min default |
| `consumed_at` | TEXT | Set on success, on max-bad-attempts, and when a newer code supersedes |
| `bad_attempts` | INT | Capped via `OTP_MAX_BAD_ATTEMPTS` |

#### `itinerary`
The user's saved picks. Composite PK `(user_id, session_id)` means each user can have a session at most once.
| Col | Type | Notes |
|---|---|---|
| `is_backup` | INT (0/1) | 0 = Attending (primary), 1 = Backup |
| `added_at` | TEXT | |

#### `user_prefs`
Per-user lightweight prefs.
| Col | Type | Notes |
|---|---|---|
| `interest_tracks_json` | TEXT JSON | List of track names — drives Day-Of gap suggestions |
| `reminders_enabled` | INT | Reserved for future push reminders |
| `onboarded` | INT | Set after first profile/onboarding submit |

#### `admin_audit`
Every admin action is logged here. Surfaced on the Admin page audit log table.
| Col | Type | Notes |
|---|---|---|
| `actor_user_id` | FK → users | The admin who acted |
| `target_user_id` | FK → users (nullable) | The user acted upon |
| `action` | TEXT | `disable_user`, `enable_user`, `promote_admin`, `demote_admin`, `create_user`, `update_user` |
| `detail` | TEXT | Free-text context (email + role) |

#### `rate_limit`
Generic time-windowed counter for abuse control. Buckets currently in use:
- `otp_req_email` — per-email OTP requests, max `OTP_MAX_PER_HOUR` per hour
- `otp_req_ip` — per-IP OTP requests, max `OTP_MAX_PER_HOUR * 3` per hour

Sweep happens lazily on every rate-limit check (`DELETE FROM rate_limit WHERE created_at < cutoff`).

### Conference data tables

#### `conf_sessions`
The source-of-truth session catalog, ~554 rows after sync.
| Col | Type | Notes |
|---|---|---|
| `natural_key` | TEXT UNIQUE | `lower("{day}|{time_label}|{room}|{title}")` — change-resistant identity |
| `title`, `description`, `day`, `day_index` | TEXT/INT | `day_index` maps to `DAY_INDEX` in `sched.py` |
| `start_time`, `end_time` | TEXT `HH:MM` 24h | Parsed from the source's `"9:00am-11:00am"` format |
| `time_label` | TEXT | The raw human label |
| `room`, `floor` | TEXT | Floor derived from `ROOM_FLOOR` map |
| `type` | TEXT | session / keynote / workshop / sponsor / etc. |
| `track` | TEXT | Free-form track name (~49 distinct values) |
| `status` | TEXT | `confirmed` / `tentative` / `hold` / `open` |
| `speakers_json` | TEXT JSON | List of speaker name strings |
| `last_seen_at`, `updated_at` | TEXT | |
| `deleted` | INT (0/1) | Soft-deleted when a session disappears from upstream sync |

Indexed on `(day_index, start_time)`, `track`, `room`, `type`, `status`.

#### `conf_speakers`
| Col | Type | Notes |
|---|---|---|
| `name` | TEXT UNIQUE | Used as the join key into `conf_sessions.speakers_json` |
| `role`, `company`, `twitter` | TEXT | |
| `sessions_count` | INT | Snapshot at last sync |

#### `session_changes`
Audit log for upstream schedule edits — drives the "live changes to your saved picks" banner on My Schedule and Day-Of.
| Col | Type | Notes |
|---|---|---|
| `change_type` | TEXT | `'updated'` or `'cancelled'` |
| `field` | TEXT (nullable) | Which column changed; null for cancellations and for body-only fields like `description` / `speakers_json` |
| `old_value`, `new_value` | TEXT (nullable) | |
| `detected_at` | TEXT | |

#### `sync_log`
One row per sync run for ops visibility.
| Col | Type | Notes |
|---|---|---|
| `source` | TEXT | `'sessions'` or `'speakers'` |
| `status` | TEXT | `running` / `ok` / `error` |
| `message`, `items_seen`, `items_changed` | | |
| `started_at`, `finished_at` | TEXT | |

### Connection model

`app/db.py` exposes two context managers:
- `db()` — read-only connection. `isolation_level=None` so reads are autocommit. Always closes.
- `tx()` — explicit transaction. `BEGIN` on enter, `COMMIT` on success, `ROLLBACK` on exception. Use for any write.

Pragmas applied per connection: `foreign_keys=ON`. Schema-level: `journal_mode=WAL`, `synchronous=NORMAL`.

---

## 6. Domain logic — day, times, conflicts, travel

`app/sched.py` is the small but load-bearing module that turns raw upstream data into the app's domain types.

### Day mapping (hard-coded)

```python
DAY_INDEX = {
  "Day 1 — Workshop Day": 0,
  "Day 2 — Session Day 1": 1,
  "Day 3 — Session Day 2": 2,
  "Day 4 — Session Day 3": 3,
}
DAY_DATE  = { 0: "2026-06-29", 1: "2026-06-30", 2: "2026-07-01", 3: "2026-07-02" }
DAY_SHORT = { 0: "Mon Jun 29", 1: "Tue Jun 30", 2: "Wed Jul 1", 3: "Thu Jul 2" }
```

The labels (`"Day 1 — Workshop Day"` etc.) come from the upstream JSON's `"day"` field verbatim. If upstream renames a day, sync silently buckets unrecognized labels to `day_index = 0`. Brittle by design — single event.

### Room → floor map

`ROOM_FLOOR` — a hand-curated dict from the venue floorplan (`llms.md`):
- Floor 1 = Expo / Registration (`Expo Stage 1..4`, `Expo Stage NE`)
- Floor 2 = Breakouts (`Track 1..9`, `Track M`)
- Floor 3 = Keynotes (`Main Stage`, `Leadership 1`, `Leadership 2`)

`floor_for(room)` returns `"1"|"2"|"3"|None`.

### Time parsing

`parse_time_range("9:00am-11:00am") → ("09:00", "11:00")` — splits on `-` or `–`, parses `[H:Mam|pm]`, returns 24h `HH:MM` strings. Returns `(None, None)` on malformed input. Both `am/pm` and noon/midnight edge cases handled.

### Normalization

`normalize_session(raw)` → `NormalizedSession` dataclass — strips, builds the `natural_key`, parses times, joins speakers into JSON, looks up the floor. Returns `None` if `title` or `day` is missing.

### Conflict detection

`conflicts(a_start, a_end, b_start, b_end)` — interval overlap on `HH:MM` strings. Treats missing times as non-conflict.

### Travel warnings

`travel_warning(end_a, room_a, start_b, room_b)` — returns a warning string if:
- Different floors AND ≤15 min gap → `"Tight: only X min and different floor (A → B)"`
- Same floor but ≤5 min gap → `"Tight: only X min between rooms (A → B)"`

Returns `None` if rooms are the same, gap is negative, floors unknown, or time math fails.

### Slot grouping (browse view)

In `app/routers/browse.py`:

`_group_by_day_slot(sessions, pick_map)` rolls flat sessions up to a `[day → [slot]]` tree. Each slot gets:
- `time`, `anchor` (e.g., `slot-1-0900`), `sessions[]`
- `count`, `primary_count`, `backup_count` (from `pick_map = {session_id: is_backup}`)
- `state` ∈ `{primary, backup, conflict, past, empty}` via `_slot_state()`:
  - `past` → date is past OR (today AND start < now)
  - `conflict` → 2+ primaries in the slot
  - `primary` → exactly 1 primary
  - `backup` → no primaries, 1+ backups
  - `empty` → otherwise
- `span_min` (duration to next slot's start, default 30) and `span_pct` (% of day used by this slot — drives the shape-bar segment widths)

This is the core data shape that feeds the bottom chrome and slot bands.

### Faceting

`app/queries.py:faceted_counts(active)` — for each dimension (`track`, `type`, `room`, `day`), runs one `GROUP BY` query with the "all filters except this dimension" WHERE clause. Returns options annotated with `count` and `selected`. ~4 queries on a 554-row table — trivial cost.

---

## 7. Conference data sync pipeline

`app/sync.py` orchestrates the upstream pull.

### Sources
- **Primary**: `SESSIONS_URL` = `https://www.ai.engineer/worldsfair/2026/sessions.json`
- **Fallback (sessions only)**: `MCP_URL` = `https://www.ai.engineer/worldsfair/2026/mcp` — a JSON-RPC 2.0 MCP server. `_fetch_sessions_via_mcp()` does the 2-step `initialize` → `tools/call list_sessions` handshake and extracts the `json`/`text` content blocks.
- **Speakers**: `SPEAKERS_URL` = `https://www.ai.engineer/worldsfair/2026/speakers.json` (no fallback).

### Flow

1. **Start a `sync_log` row** with `status='running'`.
2. **Fetch** via `httpx` (30s timeout, follow redirects). If sessions.json fails, fall through to MCP.
3. **Normalize** each row via `normalize_session()`. Skip rows missing title/day.
4. **Upsert** by `natural_key`:
   - New row → INSERT.
   - Existing row → compare every field, record diff into `session_changes` (with `change_type='updated'`), then UPDATE.
   - Body-only fields (`description`, `speakers_json`) are tracked but with `old/new = NULL` since they're long-form.
5. **Soft-delete** any existing rows whose `natural_key` was NOT in the fetch → `deleted=1` + `session_changes` row with `change_type='cancelled'`.
6. **Finish the `sync_log` row** with `items_seen`, `items_changed`, and a JSON `message` containing `{"deleted": N}`.

### Schedule

`current_interval_minutes()` returns:
- `SYNC_INTERVAL_EVENT_MINUTES` (default 15) if today is between `EVENT_START` and `EVENT_END`
- `SYNC_INTERVAL_NORMAL_MINUTES` (default 60) otherwise

APScheduler `IntervalTrigger` registered at lifespan start with `coalesce=True, max_instances=1` (no overlap). The job is `_run_sync_job()`, which wraps `sync_all()` and swallows exceptions into the logger (the scheduler must never crash on a network blip).

### Initial sync

`lifespan()` runs `sync_all()` synchronously on startup. If that fails, the app starts anyway (no data); the next interval will retry.

---

## 8. Authentication & sessions

All auth logic lives in `app/auth.py`. Passwords don't exist.

### OTP issue (`request_otp`)
1. Normalize + validate email.
2. Rate-limit per-email and per-IP (`_rate_limited()` checks against `rate_limit` table).
3. Check user isn't disabled.
4. Generate a 6-digit code via `secrets.randbelow(1_000_000)`.
5. Compute `code_hash = HMAC-SHA256(SESSION_SECRET, f"{email}|{code}").hex`.
6. Mark all previous outstanding codes for this email as consumed.
7. Insert new `otp_codes` row with `expires_at = now + OTP_TTL_MINUTES`.
8. Send via Resend (or log to stdout if `DEV_OTP_LOG=true`).

### OTP verify (`verify_otp`)
1. Look up the most recent unconsumed code for this email.
2. Bail if missing, expired, or `bad_attempts >= OTP_MAX_BAD_ATTEMPTS`.
3. `hmac.compare_digest(stored_hash, hash_of_attempt)` — constant time.
4. On mismatch: `bad_attempts += 1` and bail.
5. On match: consume the code; create the user if first login (role from `ADMIN_EMAILS` set; else `user`); refuse if disabled; update `last_login_at`.
6. Issue `secrets.token_urlsafe(32)` as the session token, insert into `sessions` with `expires_at = now + SESSION_TTL_DAYS`.

### Cookie
Set in `auth_routes.py:login_verify`:
- `httponly=True`, `samesite="lax"`, `path="/"`
- `secure=False` (TODO: flip to True behind TLS)
- `max_age = SESSION_TTL_DAYS * 86400`

### Resolution
`deps.py:current_user_optional` reads the cookie and calls `auth.resolve_session(token)`, which returns `CurrentUser` if the row exists, is unexpired, and the user is `active`.

`deps.current_user` is the protected variant — raises 302 to `/login` if no session, or for HTMX requests raises 401 with `HX-Redirect: /login` header (HTMX picks up the redirect cleanly without a hard nav).

`deps.current_admin` chains `current_user` and adds a 403 if `role != 'admin'`.

### Session invalidation
- `invalidate_session(token)` — single session, used on logout.
- `invalidate_user_sessions(user_id)` — all of a user's sessions, used when admin disables them (forces immediate logout everywhere).

---

## 9. HTTP layer

### Middleware (in order)

In FastAPI, `add_middleware` registers in stack order. Last-added runs **first** on request and **last** on response. The two app middlewares:

| Class | Adds |
|---|---|
| `SecurityHeadersMiddleware` (`main.py:27`) | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: camera=(), microphone=(), geolocation=()`, and a `Content-Security-Policy` that allows self + Google Fonts + inline styles/scripts. |
| `CacheControlMiddleware` (`main.py:50`) | Sets `Cache-Control` per response — see [§15 Caching](#15-caching-strategy). |

### Routers and endpoints

#### `auth_routes`
| Method | Path | Auth | Returns |
|---|---|---|---|
| GET | `/login` | anonymous | login.html (redirects to `/` if already signed in) |
| POST | `/login/request` | anonymous | partials/login_form.html (step=code on success) |
| POST | `/login/verify` | anonymous | empty HTML + `HX-Redirect: /` + Set-Cookie |
| POST | `/logout` | any | 302 → `/login`, deletes cookie |

#### `browse` (`/browse`)
| Method | Path | Returns |
|---|---|---|
| GET | `/browse` | full `browse.html` OR `partials/results_region.html` if HTMX |
| GET | `/browse/facets` | `partials/filter_sheet.html` — used to refresh the bottom-sheet body |
| GET | `/session/{id}` | `session_detail.html` |
| POST | `/session/{id}/save` | `partials/save_button.html` (button toggles to "✓ Attending") |
| POST | `/session/{id}/unsave` | `partials/save_button.html` (button toggles to "＋ Attending") |

#### `my_schedule` (`/my-schedule`)
| Method | Path | Returns |
|---|---|---|
| GET | `/my-schedule` | `my_schedule.html` (full) — itinerary timeline grouped by day, with conflict + travel warnings |
| POST | `/my-schedule/{id}/remove` | `partials/my_schedule_body.html` |
| POST | `/my-schedule/{id}/backup` | `partials/my_schedule_body.html` — toggles `is_backup` |

#### `dayof` (`/day-of`)
| Method | Path | Returns |
|---|---|---|
| GET | `/day-of` | `dayof.html` — now / next / upcoming-today; suggestions if you have a gap |

#### `speakers` (`/speakers`)
| Method | Path | Returns |
|---|---|---|
| GET | `/speakers` | `speakers.html` (or `partials/speakers_list.html` for HTMX search) |
| GET | `/speakers/{name}` | `speaker_detail.html` |

#### `profile` (`/profile`, `/onboarding`)
| Method | Path | Returns |
|---|---|---|
| GET | `/profile` | profile.html — track interests + reminders toggle |
| POST | `/profile` | profile.html (saved=True flag) |
| GET | `/onboarding` | onboarding.html — first-login interest picker |
| POST | `/onboarding` | empty + `HX-Redirect: /browse` |

#### `admin` (`/admin`, admin-only)
| Method | Path | Returns |
|---|---|---|
| GET | `/admin` | `admin.html` (or `partials/admin_user_list.html` for HTMX) |
| POST | `/admin/users/{id}/disable` | re-renders admin page |
| POST | `/admin/users/{id}/enable` | re-renders admin page |
| POST | `/admin/users/{id}/promote` | re-renders admin page |
| POST | `/admin/users/{id}/demote` | re-renders admin page |
| POST | `/admin/users/invite` | re-renders admin page |

All four mutate-user endpoints enforce "**cannot disable or demote the last remaining active admin**".

#### Misc (`main.py`)
| Method | Path | Returns |
|---|---|---|
| GET | `/` | 302 → `/login`, `/day-of`, or `/browse` depending on auth + date |
| GET | `/healthz` | `{"status": "ok"}` |
| GET | `/manifest.webmanifest` | PWA manifest JSON |
| GET | `/service-worker.js` | A ~15-line cache-first SW that caches the SHELL and falls back to `/browse` |

### HTMX patterns used

| Pattern | Example | Where |
|---|---|---|
| Auto-detect HTMX requests | `is_htmx(request)` → return partial; else return full page | `browse.py`, `speakers.py`, `admin.py` |
| Form-driven swaps | Filters form on `/browse` with `hx-trigger="change from:#filters delay:50ms, …"` | `browse.html` |
| Cross-form input borrowing | `hx-include="#filters input:not([name='day'])"` on day tiles | `partials/session_list.html` |
| Bottom sheet | `data-open-sheet="filter-sheet"` + `aria-hidden` toggle in `app.js:bindSheet` | `browse.html`, `partials/filter_sheet.html` |
| Out-of-band swaps | Not used currently |  |
| `HX-Redirect` for auth flows | Server sets `HX-Redirect: /` after OTP verify; HTMX nav-redirects | `auth_routes.py:login_verify` |
| Confirm modals | `hx-confirm="Remove this session…"` on My Schedule remove | `partials/my_schedule_body.html` |
| Scroll on swap | `hx-swap="outerHTML scroll:window:top"` on day-tile clicks | `partials/session_list.html` |

---

## 10. Frontend architecture

### Templating

`app/templating.py` provides:
- `templates` — a thin wrapper over `Jinja2Templates` with both the old (`name, ctx`) and new Starlette 1.x (`request, name, ctx`) calling conventions.
- Filters registered: `track_color`, `display_time`, `status_class`, `twitter_handle`.
- Global `static_v(path)` — content-hashed asset URL helper. See [§15 Caching](#15-caching-strategy).
- `is_htmx(request)` and `hx_target(request)` helpers used in routers to branch on partial vs. full response.

`track_color(track)` uses a small hand-curated palette for known track keywords ("agents" → orange, "evals" → cyan, "rag" → purple, …) and falls back to a deterministic hash bucket from a fixed 24-color palette. Returned color drives the left-edge stripe (`--track`) on session cards and the dot in track tags.

### CSS

Three stylesheets, no preprocessor.

| File | Lines | Concern |
|---|---:|---|
| `app.css` | 545 | Global tokens (CSS vars), topbar, bottom-nav, login chrome, generic session-card, toasts, day-band fallback (used by `my_schedule_body.html`) |
| `filters.css` | 333 | Search bar, filter chips, bottom sheet, "Attending" buttons, calendar-tile day-chips (legacy top-row + new bottom-row reuse) |
| `agenda.css` | 597 | Browse view: day-block layout, day-chrome (bottom-anchored), time-pill strip, shape-bar scrubber, shape-lens, slot-band dividers, compact session-card, day-tile day-switcher |

Key CSS vars in `app.css:root`:
```
--bottom-nav-h:   64px      (drives sticky-stack offsets)
--topbar-h:       60px → 52px@560px
--pad:            20px      (.page horizontal padding)
--accent:         orange family
--accent-2..3:    secondary / tertiary
--danger:         conflict red
```

The bottom day-chrome is positioned with `sticky bottom: calc(var(--bottom-nav-h) + env(safe-area-inset-bottom))` so it always sits just above the global Browse/Schedule nav. The chrome's own children (time-strip, shape-bar, day-tiles) flow normally inside.

### JavaScript

`app/static/js/app.js` (350 LOC, all in one IIFE — no module system).

Key functions:

| Function | Purpose |
|---|---|
| `bindClock()` | Updates `#liveclock` (top of Day-Of) every 30s |
| `bindCountdowns()` | `.countdown[data-start]` → "Starts in 14m" |
| `bindToasts()` | Listens to `htmx:afterSwap` for `.save-form` swaps, flashes a toast |
| `bindSheet()` | `data-open-sheet="ID"` opens the sheet (sets `aria-hidden=false`); `data-close-sheet` closes |
| `bindTypeahead()` | Filters `.opt-row[data-label]` in the bottom sheet by an input's value |
| `bindActiveChipRemove()` | Removes a filter chip by toggling the corresponding form input |
| `scrollToSlot()`, `markCurrentPill()`, `bindTimeStrip()`, `autoAnchorNow()` | Time-pill navigation + auto-jump to nearest slot when "today" |
| `bindSlotObserver()` | IntersectionObserver on `.slot-block[id]` — marks the current pill as you scroll |
| `bindShapeBarScrub()` | The big one: pointer-events-based drag scrubber on `.shape-bar` |
| `ensureShapeLens()`, `updateShapeLens()`, `hideShapeLens()` | Lazy lens DOM creation + position/content updates |

#### The shape-bar scrubber

The `.shape-bar` is `touch-action: none; user-select: none; cursor: ew-resize` and grows from 24px → 48px during scrub via the `.is-scrubbing` class. The JS:

1. `pointerdown` → `setPointerCapture` so events keep flowing if your finger leaves the bar; mark `.is-scrubbing`; find segment under finger via `elementFromPoint` (with a flex-segment fallback that uses `getBoundingClientRect()` math).
2. `pointermove` → throttled via `requestAnimationFrame`: update lens content + position, mark the active segment (`.is-active`, orange ring + glow), scroll the corresponding slot into view.
3. `pointerup`/`pointercancel` → smooth-scroll-settle to the final slot, hide lens, clear `.is-active`.

The **shape-lens** is a `position: fixed` bubble appended to `<body>` lazily. It shows:
- The time (`9:00 AM`)
- The state badge (`✓ ATTENDING`, `↻ BACKUP`, `⚠ CONFLICT`, `· PAST`, `FREE`) tinted to match
- A detail line (`2 of 4 picked` or `7 sessions`)
- A down-pointing arrow that stays glued to the active segment even when the lens itself is clamped to the viewport edge

State labels and glyphs live in `SHAPE_STATE_GLYPH` / `SHAPE_STATE_LABEL` JS constants. Per-segment data flows from the template via `data-time`, `data-display-time`, `data-state`, `data-count`, `data-picked`.

All bindings are re-attached on `htmx:afterSwap` of `#results-region` (the bindings guard via `dataset.bound === '1'` to avoid double-binding).

### Static asset cache busting

See [§15 Caching](#15-caching-strategy) for the full story. Every `<link>` and `<script>` in `base.html` uses `{{ static_v('…') }}` which appends `?v={sha1_10}`, allowing `Cache-Control: public, max-age=31536000, immutable` on the asset while HTML stays `no-cache, no-store`.

### Service worker

`/service-worker.js` is served inline from `main.py:156`. It's a ~15-line cache-first SW that:
- On `install`: caches `['/', '/browse', '/my-schedule', '/static/css/app.css', '/static/js/app.js']`
- On `fetch`: tries the network, caches the response on success, falls back to cache (and finally to `/browse`) on failure

This gives a usable shell on flaky Wi-Fi at the venue without any cache versioning ceremony — the asset URLs change on every content edit, so the SW naturally re-caches.

---

## 11. UI surfaces — page-by-page

### `/login` and OTP flow

Two-step inside one card:
1. **Email step** — input + "Send code". Submits to `/login/request` via HTMX, replaces only the form region with the code step.
2. **Code step** — masked 6-digit input + "Sign in". Submits to `/login/verify`; success returns empty body + `HX-Redirect: /`.

Errors come back in the same partial with `message` and `ok=false`.

### `/browse` (the centerpiece)

```
┌───────────────────────────────────────┐
│ topbar: WFSF · email · Sign out       │
├───────────────────────────────────────┤
│ ALL SESSIONS                          │
│ Browse the program · 558 matching     │
│                                       │
│ [ Search title, speaker, descr ] [≡]  │
│ [session 399][sponsor 115][keynote 24]│
│                                       │
│ ● 9:00am · 18 sessions      (inline)  │
│ ┌───────────────────────────────────┐ │
│ │ Arize 2hr        [+ Attending]    │ │
│ │   Track 1 · F2  SPONSOR  HOLD     │ │
│ └───────────────────────────────────┘ │
│ … more cards …                        │
│                                       │
│ ── slot 11:05am ──                    │
│ … more cards …                        │
│                                       │
│ ============== day chrome ============│ ← sticky bottom
│ 9:00am 11:05am 12:10pm 1:15pm 2:20pm  │ time pills
│ ▓▓▓░░▓▓░░░░▓▓▓░░░░░░▓▓░    scrub day │ shape-bar scrubber
│ [MON 29][TUE 30][WED 1][THU 2]       │ day tiles
├───────────────────────────────────────┤
│ Browse  My Schedule  Day-Of  Speakers │ ← global bottom-nav
└───────────────────────────────────────┘
```

- **Filters form** (`<form id="filters">`) collects: `q` (search), `type[]`, `track[]`, `room[]`, hidden `day[]`. Auto-submits on change with HTMX, swaps `#results-region`.
- **Bottom sheet**: tap "≡ Filters" → opens `partials/filter_sheet.html` with searchable Track (49) and Room (17) lists, faceted counts that respect "all filters except this dimension".
- **Active chip strip**: at the top of `results-region`, each active filter shows as a removable orange chip; clicking the ✕ toggles the corresponding form input and re-submits.
- **Day chrome** (per-day, sticky bottom): see `agenda.css` and §10 above. Time pills navigate; shape-bar drags; day-tiles switch the filter.
- **Cards** are `.session-card.compact` with track stripe + title + meta + "+ Attending" button + start→end time.

### `/session/{id}`

Full session detail: title, status badge, type/track/room/floor tags, speakers (linked to `/speakers/{name}`), full description, save button. Linked from cards.

### `/my-schedule`

Vertical timeline grouped by day. Each item shows track stripe, time, title, status, room+floor, tags. Conflict warnings (⚠) and travel warnings (↗) inline. Two buttons:
- "↻ Mark as Backup" / "↑ Make Attending" — toggles `is_backup`, re-renders the body
- "Remove" — `hx-confirm` modal

Top banner: "Heads up — changes to your saved sessions" pulled from `session_changes` (last 72h).

### `/day-of`

Date-aware view:
- **Pre-event**: shows a band saying the event runs Jun 28 – Jul 2, links to Browse.
- **In-event**: derives `day_index` from today's date.
  - "Happening now" card(s) — your primary picks where `start ≤ now < end`.
  - "Up next" card — earliest upcoming primary today, with a `setInterval`-driven countdown.
  - "Later today" list — next ~5 upcoming.
  - **Gap guidance** — if you have nothing happening now, surfaces ≤5 sessions starting in the next 90 min from your interest tracks (`user_prefs.interest_tracks_json`).
  - "Live changes to your saved picks" — last 72h of `session_changes` for your itinerary.

### `/speakers`, `/speakers/{name}`

Searchable list (live HTMX filter), detail page shows their sessions with attending buttons.

### `/profile`, `/onboarding`

Interest tracks (multi-select checkboxes against `distinct_facets()['tracks']`), reminders toggle (UI-only for now). Onboarding is a one-pager; redirects to `/browse` on submit.

### `/admin` (admin-only)

| Section | What |
|---|---|
| Stats strip | total / active / disabled / admins |
| User table | email, role, status, created/last-login; per-row Promote/Demote, Enable/Disable buttons (HTMX POSTs). Search input. |
| Invite form | Add a user by email + role (creates a `users` row directly; that user can sign in via OTP) |
| Audit log | Last 50 admin actions with actor/target emails |

Admin can never view a user's `itinerary` rows. The only fields exposed in the table are identity + status.

---

## 12. Configuration & environment

Defined in `app/config.py` via `pydantic_settings.BaseSettings`. All values are environment-variable overridable; defaults shown.

| Setting | Default | Purpose |
|---|---|---|
| `APP_NAME` | `"WFSF"` | Display name |
| `APP_BASE_URL` | `http://localhost:10000` | Used in email link text (not currently linked) |
| `APP_PORT` | `10000` | Default port for `python -m app` runner |
| `APP_HOST` | `0.0.0.0` | Default bind |
| `DATABASE_PATH` | `data/wfsf.db` | SQLite file location; parent dir auto-created |
| `SESSION_SECRET` | `change-me-in-prod-please` | HMAC key for OTP hashing (rotate → invalidates outstanding OTPs) |
| `SESSION_COOKIE_NAME` | `wfsf_session` | |
| `SESSION_TTL_DAYS` | `30` | |
| `RESEND_API_KEY` | `""` | Resend SDK key. If empty, sends fall back to log-only. |
| `RESEND_FROM` | `WFSF <onboarding@resend.dev>` | Sender |
| `ADMIN_EMAILS` | `""` | Comma-separated; seeded on startup AND on first OTP verify |
| `OTP_TTL_MINUTES` | `10` | |
| `OTP_MAX_PER_HOUR` | `5` | Per-email cap; per-IP cap is 3× this |
| `OTP_MAX_BAD_ATTEMPTS` | `5` | After hitting, the code is auto-consumed |
| `OTP_RESEND_COOLDOWN_SECONDS` | `30` | (Currently advisory — not enforced server-side) |
| `SYNC_SOURCES_FILE` | `sources.txt` | Unused — historical |
| `SYNC_INTERVAL_NORMAL_MINUTES` | `60` | |
| `SYNC_INTERVAL_EVENT_MINUTES` | `15` | |
| `EVENT_START` | `2026-06-28` | Drives `/` routing and sync interval |
| `EVENT_END` | `2026-07-02` | |
| `SESSIONS_URL` | `https://www.ai.engineer/worldsfair/2026/sessions.json` | Primary sessions source |
| `SPEAKERS_URL` | `https://www.ai.engineer/worldsfair/2026/speakers.json` | Speakers source |
| `MCP_URL` | `https://www.ai.engineer/worldsfair/2026/mcp` | MCP fallback for sessions |
| `DEV_OTP_LOG` | `True` | Prints OTPs to stdout; required when `RESEND_API_KEY` is empty |

`.env.example` ships in the repo as a template. `.env` is gitignored.

### Runner

`app/__main__.py` is the canonical entrypoint. `python -m app` → `uvicorn.run("app.main:app", host=APP_HOST, port=APP_PORT, reload=True)`. Reload can be disabled with `APP_RELOAD=0`.

---

## 13. How to run, develop, and operate

### Install

```bash
git clone https://github.com/gopikori/wfsf
cd wfsf
python -m venv .venv
source .venv/bin/activate
uv pip install -e .
cp .env.example .env
# edit .env: set SESSION_SECRET (random long string), ADMIN_EMAILS=you@..., RESEND_API_KEY (or leave empty + keep DEV_OTP_LOG=true)
```

### Run

```bash
python -m app
# → http://localhost:10000  (reload enabled)
# → http://<your-LAN-IP>:10000 from another device on the same network
```

The dev OTP appears in stdout as `DEV OTP for you@example.com: 123456` when `DEV_OTP_LOG=true`.

### First login

1. Open `/login`, enter your email → submit.
2. Grab the OTP from the server log (or your inbox if Resend is configured).
3. Paste → submit. You're in.
4. If your email was in `ADMIN_EMAILS`, you're an admin; the Admin tab appears in the bottom nav.

### Useful endpoints

| URL | Notes |
|---|---|
| `/healthz` | Liveness check |
| `/browse` | Main view |
| `/admin` | Admin only |
| `/manifest.webmanifest` | PWA manifest |
| `/service-worker.js` | Inline SW |
| `/static/...` | Static files (served by `StaticFiles` mount) |

### Hot iteration

- Python edits → uvicorn `reload=True` picks up in ~1s.
- Template edits → Jinja reads per request; no reload needed.
- CSS / JS edits → `static_v()` recomputes the hash on next request; browser fetches the new URL → no manual refresh.

### Database operations

- DB lives at `data/wfsf.db` (WAL files alongside).
- Schema is idempotent; just delete the file to start fresh.
- Backups: copy the file (or use `sqlite3 .backup`). WAL means online copy is safe but `.dump` is the cleanest.
- Inspect: `sqlite3 data/wfsf.db ".tables"`, `".schema users"`, etc.

### Manual sync

```python
# in a venv-activated shell:
python -c "from app.sync import sync_all; print(sync_all())"
```

Returns `{'sessions': {'seen': N, 'changed': K, 'deleted': D}, 'speakers': {'seen': M}}`.

---

## 14. Security posture

| Concern | Mitigation |
|---|---|
| Passwords | None — OTP only |
| OTP brute force | 6-digit code, 10-min TTL, 5 bad attempts per code, 5 issues per email per hour, 15 per IP per hour |
| OTP at rest | `HMAC-SHA256(SESSION_SECRET, "email|code")` — never stored plaintext |
| OTP delivery | Out-of-band email; if Resend fails and dev-log is off, the OTP is dropped (no fallback path) |
| Constant-time compare | `hmac.compare_digest` for code verification |
| Session hijack | `httpOnly` + `SameSite=lax` cookie; server-side token store; revocable on logout, on admin disable, and per-user via `invalidate_user_sessions` |
| TLS | Cookie is `secure=False` — set behind TLS, flip the flag before going public |
| User-id forgery | `user_id` never read from client input; always derived from cookie via `Depends(current_user)` |
| Cross-user data leak | Every itinerary query is `WHERE user_id = :session_user`; admin endpoints never SELECT from `itinerary` |
| Admin lockout | Last-active-admin guard on disable + demote |
| Audit trail | Every admin action logged to `admin_audit` with actor + target |
| Headers | `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, CSP (`script-src 'self' 'unsafe-inline'` to allow the small inline SW registration) |
| CSRF | Cookies are `SameSite=lax`. No anti-CSRF token on POSTs — relies on SameSite. Workable for the threat model (no money, no irreversible writes, single-event) but worth adding before any broader use. |
| Secret rotation | Rotating `SESSION_SECRET` invalidates all outstanding OTPs (their hash changes) but **not** existing sessions (token is random, not derived). Acceptable. |
| Email enumeration | OTP request returns identical UX for known and unknown emails ("Code sent. Check your email."). Disabled accounts get an explicit "this account has been disabled" — small leak, acceptable trade for UX. |

---

## 15. Caching strategy

Two-layer: HTML never caches, static assets cache forever because their URL changes with content.

### Asset URL hashing (`static_v`)

`app/templating.py:static_v(rel_path)`:
- Looks up `app/static/{rel_path}`.
- Reads `mtime_ns`; checks in-process cache `_static_hash_cache` keyed by `(path, mtime_ns)`.
- On miss, streams the file through SHA1 (`hashlib.sha1`), takes first 10 hex chars.
- Returns `/static/{rel_path}?v={hash10}`.

Properties:
- `touch foo.css` (mtime change, content same) → cache misses, re-hashes, gets the **same hash** → URL unchanged → no spurious cache bust.
- Real content edit → mtime changes → cache miss → new hash → new URL → browser fetches fresh.
- Hash is per-process — restarts re-warm on first request to each asset.

### `CacheControlMiddleware` (`main.py:50`)

```
Request                                       → Response Cache-Control
/static/foo.css?v=abc                         → public, max-age=31536000, immutable
/static/foo.css   (legacy, no version)        → no-cache
/browse, /, /api/anything                     → no-cache, no-store, must-revalidate
                                                + Pragma: no-cache
```

Skips if a route already set `cache-control` itself.

### Net effect

- Phone always re-fetches HTML on every nav (small).
- HTML embeds the latest asset URL.
- If an asset URL is new, phone fetches and caches it forever.
- If unchanged, phone uses its local cache — zero round-trip.

This makes UI iteration ship instantly without users having to hard-refresh.

---

## 16. Performance & scale notes

### Data sizes
- ~554 sessions × ~30 cols, full table fits comfortably in memory.
- ~300 speakers, trivial.
- `list_sessions` returns up to 800 rows per call; current full count is ~554 so no pagination needed for v1.

### Hot path cost
- `/browse` does: list (1 query), `itinerary_map` (1 query), `itinerary_ids` (1 query, subset of map but used as set), `faceted_counts` (4 queries). ~7 trivial SQL hits, <5ms total against a 554-row table.
- HTMX swaps replace `#results-region` only; the topbar, bottom-nav, and outer chrome don't re-render.

### Concurrency
- Single SQLite writer; concurrent writes serialize through WAL. Read traffic is fine in parallel.
- APScheduler runs sync in the same process (asyncio worker thread); transactions are short.

### Mobile UX
- Initial HTML ~1MB (browse page with all 554 sessions inlined as cards). Future optimization: virtualize the list or paginate per day.
- All filtering is server-side via HTMX — no client-side data store.

---

## 17. Known gaps & tech debt

| Area | Status |
|---|---|
| **Tests** | None yet. CLAUDE.md mandates "real-system tests, no mocks" — fixture story for SQLite isn't built. |
| **Type checker** | `uvx ty` is required by guidelines but no `ty.toml`; types are mostly inferred. |
| **Cookie `secure=True`** | Currently False — must be flipped before TLS deployment. |
| **CSRF tokens** | Not implemented; relying on SameSite=lax + httpOnly. Add anti-CSRF before broader use. |
| **Reminders** | `user_prefs.reminders_enabled` is wired to UI but no notification path. Browser `Notification.permission` is requested in `app.js:bindReminders` but no actual scheduled notifications fire. |
| **Push notifications** | Not implemented. |
| **CSP `'unsafe-inline'`** | Required by the inline SW-registration script in `base.html`. Could be removed by moving that to an external JS file. |
| **`argon2-cffi` dep** | Declared in `pyproject.toml` but not imported. Leftover from earlier password design. |
| **Per-room floor map** | Hard-coded in `sched.py:ROOM_FLOOR`. New venue rooms won't have floors. |
| **Speaker → session join** | Uses `LIKE '%{name}%'` against `speakers_json`. Brittle for substring collisions; works because conference speaker names are distinctive. |
| **Onboarding flow** | The `/onboarding` route exists but `current_user` doesn't redirect to it on first login. Onboarding is only reachable directly. |
| **Initial page size** | All sessions render inline; no day-paginated initial render. Fine for 554 rows. |
| **No deletion of empty `sync_log` rows** | They accumulate at 1/hour. Not a problem for a 4-day event. |
| **Service worker version** | Hardcoded `CACHE='wfsf-v1'`. Bump if you change the SW. Asset URLs are content-hashed so cache busting works regardless, but the SW's `SHELL` list won't update without a version bump. |

---

## 18. File index

### Python (app/, ~1,500 LOC)
| File | LOC | Role |
|---|---:|---|
| `__main__.py` | 18 | Uvicorn runner — `python -m app` |
| `config.py` | 50 | Pydantic settings + `.env` loader |
| `db.py` | 204 | Schema, `db()` and `tx()` context managers, admin seeding |
| `auth.py` | 183 | OTP issue/verify, session resolve/invalidate, rate limit |
| `deps.py` | 32 | FastAPI dependencies — `current_user`, `current_admin` |
| `email.py` | 47 | Resend wrapper + HTML/text OTP rendering |
| `main.py` | 178 | FastAPI app, middleware, lifespan, `/`, `/healthz`, `/manifest.webmanifest`, `/service-worker.js`, 404 |
| `queries.py` | 307 | All SQL — list/get sessions, facets, itinerary, conflicts, speakers, changes |
| `sched.py` | 187 | DAY/ROOM constants, time parsing, normalization, conflict + travel logic |
| `sync.py` | 275 | Fetch (httpx + MCP fallback), upsert, soft-delete, sync_log |
| `templating.py` | 117 | Jinja env, filters, `static_v()` hash helper |
| `routers/auth_routes.py` | 65 | `/login`, `/login/request`, `/login/verify`, `/logout` |
| `routers/browse.py` | 226 | `/browse`, `/browse/facets`, `/session/{id}`, save/unsave |
| `routers/my_schedule.py` | 67 | `/my-schedule` + remove + backup-toggle |
| `routers/dayof.py` | 117 | `/day-of` — now/next/upcoming/gap-suggest |
| `routers/speakers.py` | 31 | `/speakers`, `/speakers/{name}` |
| `routers/profile.py` | 89 | `/profile`, `/onboarding` |
| `routers/admin.py` | 148 | `/admin`, user CRUD + audit |

### Templates (app/templates/, ~700 LOC)
| File | Role |
|---|---|
| `base.html` | Layout, topbar, bottom-nav, asset links via `static_v`, SW registration |
| `browse.html` | Browse view shell — search bar, type chips, hidden day filter state, results region, filter sheet shell |
| `login.html` | Sign-in card with two-step form |
| `my_schedule.html` | Wraps `partials/my_schedule_body.html` |
| `dayof.html` | Now / next / upcoming / changes / gap suggestions |
| `speakers.html` | Search input + list |
| `speaker_detail.html` | Speaker bio + their sessions |
| `session_detail.html` | Single session detail |
| `profile.html` | Interest tracks + reminders toggle |
| `onboarding.html` | First-login interest picker |
| `admin.html` | Stats, user table, invite form, audit log |
| `404.html` | Friendly not-found page |
| `partials/session_list.html` | The core: day-blocks → slot-blocks → cards → bottom day-chrome (time pills, scrubber, day tiles) |
| `partials/results_region.html` | Wraps `session_list.html` + active chips strip |
| `partials/filter_sheet.html` | Searchable Track + Room lists with faceted counts |
| `partials/save_button.html` | "+ Attending" / "✓ Attending" toggle |
| `partials/my_schedule_body.html` | The itinerary timeline (HTMX-swappable) |
| `partials/login_form.html` | Two-step OTP form |
| `partials/admin_user_list.html` | User table partial for HTMX search |
| `partials/speakers_list.html` | Speakers list partial |

### Static (app/static/, ~1,800 LOC + vendored htmx)
| File | Role |
|---|---|
| `css/app.css` | Global tokens, topbar, bottom-nav, login chrome, generic cards, toasts |
| `css/filters.css` | Filter chips, bottom sheet, day-chip calendar tiles, Attending button |
| `css/agenda.css` | Day-block, day-chrome (sticky bottom), time-strip, shape-bar scrubber + lens, slot-band, compact card, day-tiles |
| `js/app.js` | All UI behavior — clock, countdowns, toasts, sheet, typeahead, time-strip nav, scrubber, lens, slot observer |
| `js/htmx.min.js` | Vendored HTMX |
| `icons/icon-192.svg`, `icons/icon-512.svg` | PWA icons |

### Root
| File | Role |
|---|---|
| `pyproject.toml` | Deps + setuptools package = `["app"]` |
| `README.md` | Public-facing project intro with screenshots |
| `LICENSE` | MIT |
| `.env.example` | Configuration template |
| `.gitignore` | DB, data/, snapshot YAMLs, editor dirs, etc. |
| `PRD.md` | Original product requirements (1,000+ lines, more detailed than what's been built) |
| `AGENTS.md` / `CLAUDE.md` | Coding-standards instructions for AI assistants (file size limits, no-mock testing, ast-grep, etc.) |
| `technical-guidance.md` | Tech-decision context |
| `docs/coding-guidelines/frontend-asthetics.md` | Frontend design guidelines (typography, color, motion) |
| `docs/coding-guidelines/HTMX_GUIDELINES.md` | HTMX best-practice rubric |
| `docs/images/` | README screenshots |
| `data/` (gitignored) | `wfsf.db`, `sessions.json`, `speakers.json`, `llms.md` |
| `br.yml`, `br-snap.yml`, `login-snap.yaml` (gitignored) | Rodney/Playwright dev snapshots |

---

## Appendix A — Reading order for a new contributor

If you're picking this up cold, read in this order:
1. `README.md` — what it is
2. This file (you're here)
3. `app/sched.py` — day/time/conflict primitives (small, foundational)
4. `app/db.py` — the data model
5. `app/queries.py` — the queries you'll edit most often
6. `app/routers/browse.py` — the centerpiece route
7. `app/templates/partials/session_list.html` — the centerpiece template
8. `app/static/js/app.js` — the only meaningful JS file
9. `app/static/css/agenda.css` — the visual centerpiece

Skip on first pass: `app/sync.py` (only needed when upstream data shape changes), `app/routers/admin.py` (only for user management features).

## Appendix B — Glossary

| Term | Meaning |
|---|---|
| **Slot** | A `(day, start_time)` bucket. All sessions starting at the same time on the same day belong to the same slot. |
| **Primary** | Itinerary entry with `is_backup = 0`. The session you actually plan to attend. |
| **Backup** | Itinerary entry with `is_backup = 1`. A "in case the primary falls through" pick. Counts for the slot's visual but doesn't trigger conflicts. |
| **Conflict** | A slot with 2+ primaries — visually red, pulses in the pill row. |
| **Day chrome** | The bottom-anchored sticky panel containing time pills, scrubber, and day tiles. One per day-block; only the current one is visible. |
| **Shape bar** | The 24px-tall horizontal bar of proportional colored segments inside the day chrome — the drag scrubber. |
| **Shape lens** | The floating tooltip that follows your finger during a scrub, showing time + state + count. |
| **Natural key** | The stable identity for a session across syncs: `"{day}|{time}|{room}|{title}"` lowercased. |
| **HTMX partial** | A response that's a fragment of HTML (not a full document), swapped into a target element by HTMX. Distinguished from full-page responses by the `HX-Request: true` header. |

---
*Last reviewed: 2026-06-14. Generated from a deep code survey by Claude (Opus 4.7). If you've made structural changes, regenerate.*
