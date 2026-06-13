# PRD — WFSF (World's Fair San Francisco — AI Engineer World's Fair 2026 Schedule Builder)

| | |
|---|---|
| **Status** | Draft v1.1 |
| **Date** | 2026-06-13 |
| **Owner** | Gopi |
| **Type** | Web app (responsive, mobile-first PWA) |
| **v1 Scope** | Single event · Manual browse + filters · Solo planning · Day-of companion · User/Admin roles |
| **Stack** | Resend (OTP email) · SQLite on a persistent volume · Server-side sync · Deployed on Render.com |

---

## 1. Problem

The AI Engineer World's Fair 2026 has **554 sessions, ~300 speakers, and 9+ parallel tracks** across 4–5 days. Attendees cannot physically see everything, the official schedule is volatile (many sessions are `tentative`/`hold`), and there is no good tool to build a personal, conflict-free itinerary on a phone while walking the floor. Everyone attending has this problem.

## 2. Goals & Non-Goals

**Goals**
- Let an attendee go from zero to a saved, conflict-free 4-day itinerary in **under 10 minutes**.
- Make browsing 554 sessions feel effortless on a phone — filtering, scanning, and adding to "My Schedule" in one or two taps.
- Surface the things that break plans: **time conflicts, tentative sessions, and room-to-room travel**.
- Work reliably on flaky conference Wi-Fi (offline-capable).
- Be the attendee's **go-to companion on event days** — show what's on now, what's next, where to go, and what changed.

**Non-Goals (v1)**
- No AI/ML recommendations (manual browse + filters only).
- No social/collaboration features (solo only).
- No multi-conference support (this event only).
- No ticketing, payments, or check-in.

## 3. Target Users

| Persona | Need |
|---|---|
| **The Engineer (primary)** | Deep on 2–3 tracks (agents, evals, RAG, inference). Wants the best talk in each slot + backups. |
| **The Optimizer** | Wants zero schedule gaps/conflicts and minimal floor walking between rooms. |
| **The Explorer** | Browsing by interest, not sure yet; needs fast discovery and easy bookmarking. |

## 4. Success Metrics

- **Activation:** % of logged-in users who add ≥3 sessions to My Schedule.
- **Core value:** % of users with a saved itinerary covering ≥3 of the event days.
- **Speed:** median time from login → first session added (< 2 min).
- **Retention:** % returning during the event (Jun 28–Jul 2).
- **UX health:** conflict-resolution rate (users who hit a clash and resolve it vs. abandon).

## 5. Authentication

- **Email + OTP only.** No passwords. OTP email delivered via **Resend**; OTP generation/verification handled by our backend.
- **Flow:** user enters email → backend generates a 6-digit code, stores only its hash, sends via Resend → user enters code → server creates a session.
- **OTP rules:** valid ~10 min, single use, constant-time compare; max 5 requests/hour/email and lockout after repeated bad codes; "resend" with cooldown.
- **Session:** long-lived but expiring token in an httpOnly, Secure, SameSite cookie (stay logged in for the event); rotate on login; explicit logout invalidates server-side.
- **Graceful states:** invalid/expired code, resend, wrong email.
- **Disabled accounts:** a user disabled by an admin cannot request/verify an OTP, and any active session is invalidated; they see a clear "access disabled" message.
- Full security model and role/permission rules in **§9 Security & Data Isolation**.

## 6. Functional Requirements

### 6.1 Onboarding (lightweight, skippable)
- After first login: optional 1-screen interest picker (select tracks you care about) → pre-applies filters. Skippable; never blocks browsing.

### 6.2 Browse & Discover (the core)
- **Session list** grouped by day, sorted by time.
- **Filters:** day, track (36), type (keynote/session/workshop/sponsor), room/floor, status, free-text search (title, description, speaker).
- **Filter UX:** sticky filter bar on mobile; multi-select chips; active filters always visible; one-tap "clear all"; result count live-updates.
- **Speaker browse:** list/search speakers → tap to see their sessions.
- Each list item shows at a glance: time, title, track color, room, speaker, status badge (`confirmed`/`tentative`), and a one-tap **add/remove** control.

### 6.3 Session Detail
- Full description, speakers (with role/company/social links), time, room + floor, track, status.
- Primary action: **Add to My Schedule** / Remove.
- If adding creates a conflict → inline warning with the clashing session and a quick "keep both / swap / cancel" choice.

### 6.4 My Schedule (the payoff)
- **Agenda/timeline view** per day showing chosen sessions in order.
- **Conflict detection:** overlapping sessions flagged visually; user can mark one as "backup."
- **Gaps & travel:** show empty slots; flag tight back-to-back picks in different rooms/floors (travel-time warning).
- **Backups:** allow a primary + backup pick for the same time slot.
- Empty state nudges user into Browse.

### 6.5 Reminders (v1-light)
- Local/browser notifications for upcoming saved sessions (e.g., 15 min before). Opt-in.

### 6.6 Data Freshness
- Schedule is volatile → backend **server-side sync** pulls the source on a schedule (decision: **hourly normally, every 15 min during event days Jun 28–Jul 2**); clients fetch from our API and can pull-to-refresh anytime.
- Sync **diffs** against stored data so changes can be detected and surfaced.
- Status badges reflect `confirmed`/`tentative`/`hold`/`open`.
- If a saved session changes time/room or is cancelled → flag it in My Schedule and in the Day-Of view.

### 6.7 Day-Of Companion (the in-event go-to)
The app must be the attendee's primary tool *during* the event, not just a pre-planning tool.
- **"Now & Next" home:** on event days, the app opens to a live view — the session happening **now** from your schedule, plus your **next** one with a countdown.
- **Auto "Today":** defaults to the current day with a current-time indicator on the timeline.
- **Where to go:** each current/next item shows **room + floor** prominently ("Track 3 · Floor 2"); flags when your next pick is on a different floor (leave-now nudge).
- **Gap guidance:** during an empty slot, suggest what's **happening now/next** across the tracks you follow, so there's always a next step.
- **Live change alerts:** if a saved session moved room/time or was cancelled, banner it on the Day-Of view.
- **Pre-session reminders:** opt-in notification ~15 min before each saved session (ties to §6.5).
- **Backup fallback:** if your primary for a slot is cancelled, surface your marked backup.
- Fully usable **offline** (cached) so it works on the floor with bad Wi-Fi.

### 6.8 Admin Console (role-gated)
Two roles exist: **user** (default — every attendee) and **admin**. The console is visible only to admins.
- **User registry:** total registered-user count + a searchable list showing email, registration date, role, and status (active/disabled).
- **Enable / disable access:** toggle any user's access; disabling immediately blocks login and kills active sessions (§5).
- **Manage admins:** promote a user to admin or demote back to user — this is how you "add a few more admins when you need help." The system prevents removing/disabling the **last remaining admin**.
- **Privacy boundary:** admins see **account metadata only** — never another user's saved itinerary/preferences (preserves the §9 data-isolation rule).
- **Audit:** every admin action (enable/disable, promote/demote) is recorded with who / what / when.
- Designed to extend later with more administrative tools.

## 7. UX / UI Requirements *(primary requirement)*

**Principles**
- **Mobile-first, thumb-reachable.** Most use happens standing on the expo floor. Primary actions in the bottom half of the screen.
- **Two taps to value.** Browse → add. Never bury the add action.
- **Glanceable.** Track color-coding, clear status badges, time always visible.
- **Forgiving.** Every add/remove is reversible (undo toast); conflicts are surfaced, never silent.
- **Fast.** Instant filtering, no full-page reloads, optimistic UI on add/remove.

**Core navigation (bottom tab bar):**
`Browse` · `My Schedule` · `Speakers` · `Profile`  *(admins also see an `Admin` entry)*

**Key screens**
1. **Login** — single email field → OTP entry. Minimal, no clutter.
2. **Browse** — sticky search + filter chips; day switcher (segmented control); scrollable session cards with inline add.
3. **Session Detail** — hero (title/time/room/track), description, speakers, sticky bottom "Add" button.
4. **My Schedule** — per-day vertical timeline; conflicts and travel warnings inline; tap to view/remove.
5. **Speakers** — searchable grid/list → speaker → their talks.
6. **Admin (admins only)** — user count + searchable user table with enable/disable and promote/demote controls; confirm dialogs on destructive actions.

**Accessibility:** WCAG AA contrast, scalable text, screen-reader labels, color never the sole signal (pair track color with text).

## 8. Non-Functional Requirements

- **Offline / PWA:** installable; cached schedule + My Schedule readable offline; sync on reconnect.
- **Performance:** first meaningful paint < 2s on 4G; list of 554 items virtualized for smooth scroll.
- **Reliability:** itinerary stored server-side (tied to email) so it survives device/browser changes.
- **Security & Privacy:** strict per-user data isolation; store only email + itinerary; no third-party tracking of session choices. Full model in **§9**.
- **Responsive:** phone-first, scales cleanly to tablet/desktop.

## 9. Security & Data Isolation

Multi-user app → strict isolation is a hard requirement: **no user can ever read or modify another user's data.**

**Authentication & sessions**
- Email + OTP (§5); session tokens in httpOnly, Secure, SameSite cookies; server-side session store with expiry + rotation; logout invalidates server-side.
- OTP codes stored hashed, single-use, short-lived, rate-limited, constant-time compared.

**Authorization & data isolation**
- Every user-data row (itinerary, preferences) is keyed to a `user_id`.
- Every request derives `user_id` from the authenticated session **only** — never from client input. No endpoint accepts a user id from the client.
- All queries are scoped `WHERE user_id = :session_user`; authorization checked on every read/write (default-deny).

**Roles & access control (RBAC)**
- Two roles: **user** (default) and **admin**. Role is stored on the user record and resolved from the session — never from client input.
- Admin-only endpoints enforce the admin role server-side (default-deny); a normal user calling an admin route is rejected.
- **First admin** is seeded out-of-band (env-configured admin email / seed script); further admins are promoted only by an existing admin.
- Admins manage account state/roles but **cannot access users' itineraries** — data isolation applies to admins too.
- Safeguards: cannot disable or demote the last remaining admin; all admin actions are audit-logged.

**Web security baseline (standard practices)**
- HTTPS/TLS everywhere; HSTS.
- Parameterized SQL only (no string-built queries) → SQL injection safe.
- Output encoding / framework auto-escaping → XSS safe; strict **Content-Security-Policy**.
- CSRF protection (SameSite cookies + anti-CSRF tokens on state-changing requests).
- Security headers: CSP, HSTS, X-Content-Type-Options, X-Frame-Options/frame-ancestors, Referrer-Policy.
- Input validation + payload size limits on all endpoints.
- Per-IP and per-account rate limiting (esp. OTP request/verify) + brute-force lockout.
- Secrets (Resend API key, session secret) in env vars / Render secrets — never in the repo.
- Dependencies kept patched; automated vulnerability scanning.
- Security events logged without storing OTPs or PII beyond email.

**Privacy / data minimization**
- Store only what's needed: email + the user's itinerary/preferences.
- Account + data deletion on request.

## 10. Technical Architecture & Deployment

**Shape:** responsive PWA frontend + backend API (auth, OTP, itinerary, schedule sync) + SQLite database. Single deployable service on **Render.com**.

**Database — SQLite**
- SQLite is the system of record for users (incl. `role` and `status` fields), auth/sessions, itineraries, and an admin audit log.
- **First admin** seeded via env (e.g., `ADMIN_EMAILS`) on startup; subsequent admins promoted in-app.
- DB file at a **configurable path via env var** (e.g., `DATABASE_PATH=/var/data/wfsf.db`).
- On Render, that path is a mounted **persistent disk** so data survives deploys/restarts.
- Enable **WAL mode** for read/write concurrency; enforce foreign keys.
- **Single-instance** deployment (a Render persistent disk attaches to one instance) — acceptable for v1 scale; documented as a scaling constraint.
- Periodic DB backups (snapshot/copy the volume file).

**Schedule sync**
- Backend job pulls the public source → upserts into SQLite → diffs to flag changes. Cadence per §6.6.

**MCP usage (backend-only)**
- The MCP server (`get_conference_info`, `list_speakers`, `list_sessions`, `get_schedule`) is an **ingestion source for the sync job — never client-facing.**
- **Primary source** is the static JSON (`sessions.json` / `speakers.json`) via plain HTTP GET; **MCP is the fallback/cross-check** when the JSON is stale, unreachable, or missing fields.
- The browser only ever talks to **our** API (with our auth, rate limiting, and per-user data isolation in front) — never directly to MCP. SQLite caching means all attendees hit our cache, not the upstream server.
- MCP is JSON-RPC 2.0 (requires an `initialize` handshake, protocol version `2025-03-26`), so it's better suited to a server job than to mobile clients.

**Email**
- **Resend** for OTP delivery; backend owns code generation/verification.

**Deployment notes**
- Env-driven config (DB path, Resend key, session secret, sync cadence).
- HTTPS via Render; health-check endpoint; structured logging.

## 11. Data Sources

All source URLs are catalogued in **`sources.txt`** (repo root), the canonical list the sync job reads from:

| Source | URL | Use |
|---|---|---|
| Sessions | `https://www.ai.engineer/worldsfair/2026/sessions.json` | Sessions: title, description, day, time, room, type, track, status, speakers |
| Speakers | `https://www.ai.engineer/worldsfair/2026/speakers.json` | Speaker profiles: role, company, socials, talks |
| Event info | `https://www.ai.engineer/worldsfair/2026/llms.md` | Static event info (dates, venue, floors) |
| MCP server | `https://www.ai.engineer/worldsfair/2026/mcp` | Fallback/cross-check via `list_sessions`, `list_speakers`, `get_schedule`, `get_conference_info` (backend-only, §10) |
| Speaker embeddings | `https://www.ai.engineer/worldsfair/speakers-embeddings.json` | **Not used in v1** (reserved for future AI recommendations) |

**Data notes:** 18+ rooms (Main Stage, Leadership 1–2, Tracks 1–9, M, Expo Stages 1–4) across 3 floors; speaker arrays are often empty; many statuses are tentative — UI must handle missing/changing fields gracefully.

## 12. Out of Scope (v1) → Future

- AI-powered "build my schedule for me" (use embeddings).
- Social: share itinerary, see what colleagues attend, group coordination.
- Multi-conference / organizer self-serve.
- In-app maps/wayfinding (v1 gives room + floor text and leave-now nudges, not a map).
- Background web-push notifications (v1 uses in-app/local reminders only).
- Ratings/notes.
- Calendar (.ics) export — intentionally excluded so the app stays the single go-to during the event.

## 13. Milestones

1. **M1 — Foundation:** SQLite + persistent volume, schedule ingestion/sync, email+OTP via Resend, secure sessions, role model + first-admin seeding, data-isolation model.
2. **M2 — Browse:** list, filters, search, session detail.
3. **M3 — My Schedule:** add/remove, conflict detection, timeline view, backups.
4. **M4 — Day-Of Companion:** Now & Next, live change alerts, reminders, gap guidance.
5. **M5 — Admin Console:** RBAC enforcement, user registry, enable/disable, promote/demote, audit log.
6. **M6 — Polish & Hardening:** PWA/offline, travel warnings, accessibility pass, security review.

## 14. Decisions Log

- **OTP email:** Resend (backend owns code generation/verification).
- **Schedule sync:** server-side, hourly / 15-min during event days.
- **Database:** SQLite on a persistent volume (env-configurable path) on Render.com.
- **ICS export:** excluded by design — app is the single in-event go-to.
- **Security:** strict per-user data isolation + standard web security baseline (§9).
- **Roles:** `user` (default) + `admin`; first admin seeded via env, more promoted in-app; admins manage accounts/roles, not itineraries.

## 15. Open Questions

- Confirm the 4 specific days each user attends (drives default day filter).
- Backend language/framework choice (e.g., Node/TS) — finalize before M1.
- DB backup cadence/retention for the Render persistent disk.
