# Habit Tracker App - Session Context

## Quick Reference

**Project**: Habit Tracker App
**Code**: HTRK
**Location**: `/home/sdevrajk/projects/habit-tracker/`
**Purpose**: Python-based tracker for daily habits
**Tech Stack**: Python, HTML

## Codebase Map

**`app.py`** — Flask application factory and entry point. Initialises the database (idempotent), creates a background asyncio event loop (`_bot_loop`) in a daemon thread to host the PTB Application, registers the Telegram webhook endpoint at `POST /webhook/<TOKEN>`, registers the dashboard blueprint, and starts the APScheduler. All three long-running subsystems (bot loop, Flask WSGI, APScheduler) co-exist in the same process. See `app.py:58` for webhook bridging via `asyncio.run_coroutine_threadsafe`.

**`bot.py`** — All Telegram bot logic. Defines command handlers (`/status`, `/log`, `/done`, `/fail`, `/skip`, `/habits`, `/add`, `/remove`, `/setreminder`), the `log_callback` handler for inline button taps, the `custom_numeric_input` handler for free-text numeric values, and the multi-step `ConversationHandler` for `/add`. Auth guard `_authorised()` at `bot.py:53` silently drops messages from any chat ID other than `Config.TELEGRAM_CHAT_ID`. `build_application()` at `bot.py:530` wires all handlers into a PTB `Application` instance returned to `app.py`.

**`scheduler.py`** — APScheduler `BackgroundScheduler` jobs. Defines six cron jobs: morning briefing (07:00 daily), global reminder (configurable time, default 21:00), trash reminder (19:00 Mon/Wed/Thu), log-hours reminder (16:45 Friday), last-chance reminder (22:00 daily), and end-of-day auto-fail (23:59 daily). All jobs bridge to the bot's asyncio loop via `asyncio.run_coroutine_threadsafe` (see `scheduler.py:27`). Reminder jobs are suppressed if the relevant habit is already logged for that day.

**`models.py`** — Pure SQLite data access layer with no Flask or Telegram dependencies. Defines the three-table schema (`habits`, `logs`, `config`), all CRUD functions, `get_streak()` streak calculation logic (see `models.py:307`), and `seed_habits()` which inserts the 8 default habits on first startup. Uses WAL mode and `check_same_thread=False`; opens and closes a connection per call. `upsert_log` and `upsert_numeric_log` are idempotent via `ON CONFLICT ... DO UPDATE`.

**`dashboard.py`** — Flask `Blueprint("dashboard")` with five route groups: today view (`/`), habit logging form handler (`POST /log_habit`), annual heatmap (`/heatmap`), per-habit monthly calendar (`/calendar`), and the habit manager CRUD (`/habits`, `/habits/add`, `/habits/<id>/edit`, `/habits/<id>/deactivate`). Queries models directly; passes data to Jinja2 templates. The heatmap view computes a `{date: fraction_completed}` dict for the past 365 days at `dashboard.py:76`.

**`configs/config.py`** — `Config` class that reads environment variables at import time. `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, and `DATABASE_URL` are required and raise `EnvironmentError` immediately if absent (fail-fast). `TIMEZONE` defaults to `America/Toronto`; `PORT` defaults to `5000`.

**`templates/`** — Jinja2 HTML templates: `base.html` (shared nav/layout), `today.html` (habit cards with inline log forms and streak badges), `heatmap.html` (annual heatmap rendered via `static/charts.js`), `calendar.html` (per-habit monthly calendar), `habits.html` (habit manager with add form and per-row edit/deactivate).

**`tests/`** — Three test modules totalling 48 tests. `test_models.py` uses a temp-file SQLite DB for full isolation. `test_bot.py` and `test_scheduler.py` mock all Telegram API calls and database access. All tests pass with no network access required.

## Key Concepts

**Webhook vs polling**: The app uses Telegram's webhook mode — Telegram pushes updates via HTTP POST to `/webhook/<TOKEN>`. This is required for Railway (no public IP for polling). Webhooks must be registered once with `setWebhook`; re-registering after redeploys is safe and idempotent.

**Sync/async bridge (PTB + Flask)**: Flask is synchronous WSGI; `python-telegram-bot` v21 is async. The solution: a dedicated `asyncio` event loop runs in a background daemon thread (`_bot_loop`). The webhook handler calls `asyncio.run_coroutine_threadsafe(process_update(...), _bot_loop).result(timeout=10)` to hand updates from Flask's sync context to PTB's async context. The same bridge is used in scheduler jobs (`scheduler.py:27`).

**PTB Application lifecycle**: PTB v21 requires both `application.initialize()` and `application.start()` to be called (in that order) before `process_update()` will work. `initialize()` sets up internal state; `start()` starts the updater dispatcher. Both are called synchronously at startup via `.result()` (`app.py:49–50`).

**Habit frequency filtering**: `models.get_habits_for_day()` filters active habits by their `frequency` field: `daily` always applies; `weekly` and `specific_days` check whether `date.weekday()` is in the `frequency_days` JSON array. This filtering is applied in both the bot (for `/log`, `/status`) and the scheduler (for reminders and auto-fail).

**Streak calculation rules (PRD §7.3)**: `get_streak()` at `models.py:307` walks backward from today for current streak, and forward from `created_at` for best streak. `completed` and `partial` extend the streak; `skipped` is neutral (passes through); `not_applicable` is excluded entirely; `failed` and unlogged past days break the streak. `not_applicable` differs from `skipped` in that it is completely invisible to streak counting.

**Numeric habit status derivation**: For numeric habits, the raw value is compared to `threshold_ok` and `threshold_good` to derive status automatically: `value >= threshold_good` → `completed`; `value >= threshold_ok` → `partial`; otherwise `failed`. This logic lives in `models._derive_status()` at `models.py:218` and is called by `upsert_numeric_log`.

**Idempotent upserts**: Both `upsert_log` and `init_db` use SQLite `ON CONFLICT ... DO UPDATE` (upsert) semantics. This means re-calling them with new values updates the existing row; calling `seed_habits()` twice is safe. The database is opened per call (no shared connection pool), which is safe for single-process use with `check_same_thread=False`.

**APScheduler timezone handling**: All scheduler jobs fire in the timezone specified by `Config.TIMEZONE` (default `America/Toronto`). The global reminder time is read from the `config` table in the DB at scheduler start, so changing it via `/setreminder` takes effect on the next app restart (not live). All other job times are hardcoded in `scheduler.py`.

## Current Session Context
<!-- Auto-managed by /save-context -->

**Last Updated**: 2026-04-16
**Session Focus**: Full implementation, deployment, and live testing
**Active PRD**: `docs/prd/PRD-habit-tracker.md`
**Active Tasks**: `docs/tasks/tasks-PRD-habit-tracker.md`

### Next Tasks
- Set up database backup cron job — `/data/habits.db` on Railway has no off-platform copy; daily/weekly backup to GitHub private repo, Dropbox, or S3 needed before data accumulates
- Add HTTP Basic Auth to the dashboard — habits and fitness pages must be private before fitness data is logged; credentials via `DASHBOARD_USER` / `DASHBOARD_PASS` env vars (see PRD-fitness-tracking.md §1)
- Generate tasks from `docs/prd/PRD-fitness-tracking.md` and begin fitness tracking implementation

### Recent Completions
- [x] All 5 task groups complete (data layer, bot, scheduler, dashboard, deployment)
- [x] Deployed to Railway at `habits.sayeeddevrajkizuk.com`
- [x] Telegram webhook registered and verified working
- [x] Fixed PTB 20.8 → 21.11.1 for Python 3.13 compatibility
- [x] Added 7 AM morning briefing, 10 PM last-chance reminder, congratulation messages
- [x] Added frequency editing to habit manager

### Key Session Notes
- `python-telegram-bot==21.11.1` required for Python 3.13 (20.8 has `__slots__` bug)
- `application.start()` must be called in addition to `initialize()` before `process_update()`
- Railway persistent volume mounted at `/data`; `DATABASE_URL=/data/habits.db`
- Custom domain via Cloudflare CNAME; must disable proxy (grey cloud) for Railway DNS verification, then re-enable
- `.env` file at project root for local dev (excluded by `.gitignore`)

### Quick Reference
- Entry point: `app.py`
- Bot handlers: `bot.py`
- Scheduler jobs: `scheduler.py`
- Database layer: `models.py`
- Dashboard blueprint: `dashboard.py`
- Templates: `templates/`
- Static assets: `static/`
- Tests: `tests/` (48 tests)
- Deployment guide: `docs/SETUP.md`
