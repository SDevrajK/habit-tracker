# Task List: Habit Tracker App

**PRD**: `docs/prd/PRD-habit-tracker.md`  
**Generated**: 2026-04-16  
**Status**: Active

---

## Relevant Files

- `app.py` — Flask entry point; registers blueprints, mounts bot webhook endpoint, starts scheduler
- `bot.py` — All Telegram command handlers and inline keyboard callback handlers
- `scheduler.py` — APScheduler job definitions for all three reminder types
- `models.py` — SQLite access layer: habits, logs, config CRUD and streak/status queries
- `configs/config.py` — Loads and validates environment variables
- `templates/base.html` — Shared layout, navigation
- `templates/today.html` — Today's overview view
- `templates/heatmap.html` — Annual heatmap view
- `templates/calendar.html` — Per-habit monthly calendar view
- `templates/habits.html` — Habit manager (add/edit/deactivate)
- `static/style.css` — Dashboard styles
- `static/charts.js` — Client-side heatmap and calendar rendering
- `data/habits.db` — SQLite database (created at runtime)
- `requirements.txt` — Python dependencies
- `Procfile` — Railway process definition
- `tests/test_models.py` — Unit tests for all database access functions
- `tests/test_bot.py` — Unit tests for command parsing and handler logic
- `tests/test_scheduler.py` — Unit tests for reminder suppression logic

### Notes
- Tests use `pytest`; database tests use an in-memory SQLite instance
- No test should depend on Telegram API or network access — mock external calls

---

## Task Classification Legend
- **[RESEARCH]** — Investigate libraries, patterns, or existing code before implementing
- **[IMPLEMENTATION]** — Write the code
- **[REVIEW]** — Use quality-assessment-specialist to verify requirements are met and no placeholders remain

---

## Tasks

- [x] 1.0 Project Setup & Data Layer (ALL SUB-TASKS COMPLETE)
  - [x] 1.1 **[RESEARCH]** Review `python-telegram-bot` v20+ (async) vs v13 (sync) API to decide which version fits a single-process Flask+APScheduler architecture; note any threading constraints
    - Decision: Use **v20+**, pinned to `python-telegram-bot==20.8` (stable v20 API surface, actively maintained; v13 is EOL)
    - Integration pattern: run a persistent asyncio event loop in a background daemon thread; Flask webhook endpoint hands updates via `asyncio.run_coroutine_threadsafe(app.process_update(update), bot_loop)`
    - Threading constraints: (1) single asyncio loop in one daemon thread, (2) all Telegram calls from scheduler jobs use `run_coroutine_threadsafe`, (3) SQLite with `check_same_thread=False`, one connection per thread
  - [x] 1.2 **[IMPLEMENTATION] [DEPENDS: 1.1]** Create `requirements.txt` with pinned versions: Flask, python-telegram-bot, APScheduler, loguru; create `configs/config.py` that loads and validates `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `DATABASE_URL` from environment, raising clearly on missing values
    - Created `requirements.txt` with Flask==3.1.3, python-telegram-bot==20.8, APScheduler==3.10.4, loguru==0.7.3, pytest==8.3.5
    - Created `configs/config.py` with `Config` class; raises `EnvironmentError` on missing required vars; `TIMEZONE` defaults to `America/Toronto`, `PORT` to 5000
  - [x] 1.3 **[IMPLEMENTATION] [DEPENDS: 1.2]** Implement `models.py`: create SQLite schema (`habits`, `logs`, `config` tables as per PRD section 8); write typed functions for: `get_habits_for_day(date)`, `upsert_log(habit_id, date, status, value)`, `get_logs_for_habit(habit_id, start, end)`, `get_streak(habit_id)`, `get_config(key)`, `set_config(key, value)`
    - All PRD §8 columns present; WAL mode + FK enforcement enabled
    - `upsert_log` uses `ON CONFLICT DO UPDATE` for idempotent re-logging
    - `get_streak` excludes `not_applicable` and `skipped` days; `partial` counts as success
  - [x] 1.4 **[IMPLEMENTATION] [DEPENDS: 1.3]** Write a `seed_habits()` function that inserts all 8 habits from PRD section 5 with correct types, frequencies, frequency_days, and reminder_time overrides; this runs once on first startup if the `habits` table is empty
    - `seed_habits()` appended to `models.py`; checks `COUNT(*)` before inserting; idempotent
  - [x] 1.5 **[IMPLEMENTATION] [DEPENDS: 1.3]** Write `tests/test_models.py`: cover schema creation, `upsert_log` idempotency (re-logging same habit same day updates rather than inserts), `get_habits_for_day` correctly filters by frequency and weekday, streak calculation handles `skipped` days without breaking streak, `not_applicable` days excluded from streak
    - 20/20 tests passing; covers schema, config, upsert idempotency, frequency filtering, all streak edge cases, seed data correctness
  - [x] 1.6 **[REVIEW] [DEPENDS: 1.5]** Verify data layer against PRD section 8: all columns present with correct types, all five log statuses handled, streak logic matches spec, seed data matches PRD section 5 exactly
    - All habits/logs/config columns present with correct types and CHECK constraints
    - All 5 log statuses in CHECK constraint; streak handles all 5 correctly
    - Seed data verified: Log hours (Fri, 16:45), Put out trash (Mon/Wed/Thu, 19:00), Fast food (inverse_boolean), numeric thresholds all match PRD §5

- [x] 2.0 Telegram Bot — Logging & Commands (ALL SUB-TASKS COMPLETE)
  - [x] 2.1 **[RESEARCH] [DEPENDS: 1.6]** Review `python-telegram-bot` inline keyboard and `CallbackQueryHandler` patterns for multi-step flows; confirm approach for numeric input (inline "custom" button → await text reply)
    - `callback_data` encodes action as `"log:{habit_id}:{status}"` or `"log:{habit_id}:num:{value}"` (max 64 bytes, safe for all cases)
    - After boolean/preset button tap: call `query.answer()` + `query.edit_message_text()` to update in-place
    - Numeric "custom" button: store `{chat_id: habit_id}` in bot's `user_data`; next text message caught by `MessageHandler` that checks state
    - Use `ConversationHandler` for `/add` (guided multi-step); simple state dict for one-shot custom numeric input
    - All handlers guarded by chat ID check at entry (ignore silently if not authorised)
  - [x] 2.2 **[IMPLEMENTATION] [DEPENDS: 2.1]** Create `app.py`: initialise Flask app and Telegram `Application`; register webhook endpoint `POST /webhook/<token>` that feeds updates to the bot; ensure bot only processes messages from `TELEGRAM_CHAT_ID` (ignore all others silently)
    - Bot asyncio loop runs in a daemon thread; Flask webhook hands updates via `run_coroutine_threadsafe`
    - Chat ID filtering is enforced inside `bot.py` handlers (not at webhook level, so Telegram ACK is still sent)
  - [x] 2.3 **[IMPLEMENTATION] [DEPENDS: 2.2]** Implement `/status` and `/habits` commands in `bot.py`
  - [x] 2.4 **[IMPLEMENTATION] [DEPENDS: 2.3]** Implement `/log` inline keyboard command
    - Boolean: ✓/✗/skip buttons; inverse-boolean labels "No (good)"/"Yes (bad)"; numeric: presets + custom
    - Custom triggers state flag in `user_data`; next text message from user is caught by `custom_numeric_input` handler
  - [x] 2.5 **[IMPLEMENTATION] [DEPENDS: 2.3]** Implement `/done`, `/fail`, `/skip` with fuzzy matching
  - [x] 2.6 **[IMPLEMENTATION] [DEPENDS: 2.3]** Implement `/add` (ConversationHandler), `/remove`, `/setreminder`
  - [x] 2.7 **[IMPLEMENTATION] [DEPENDS: 2.4, 2.5]** `auto_fail_unlogged()` coroutine in `bot.py`; wired to scheduler at 23:59
  - [x] 2.8 **[IMPLEMENTATION] [DEPENDS: 2.5]** `tests/test_bot.py` — 19/19 passing; covers auth, fuzzy match, done/ambiguous/no-match, status formatting, custom numeric accept/reject
  - [x] 2.9 **[REVIEW] [DEPENDS: 2.8]** All PRD §7.3 commands present; inverse-boolean phrasing "(Yes = bad)" in /log; no code changes needed to add habits; `/add` conversation flow handles all types

- [x] 3.0 Reminder Scheduler (ALL SUB-TASKS COMPLETE)
  - [x] 3.1 **[RESEARCH] [DEPENDS: 1.6]** Confirm APScheduler `BackgroundScheduler` works cleanly inside a Flask process alongside a Telegram webhook handler; identify any known issues with Railway's always-on containers and APScheduler (e.g. timezone handling)
    - `BackgroundScheduler` runs in its own thread pool — no asyncio conflict with PTB v20 event loop
    - Railway always-on containers have no sleep/wake cycle; scheduler runs indefinitely without special handling
    - Timezone: pass `pytz.timezone(tz_name)` to BackgroundScheduler; `zoneinfo.ZoneInfo` works if APScheduler ≥3.10
    - Deploy with `--workers=1` (Procfile) to prevent duplicate scheduler instances
  - [x] 3.2 **[IMPLEMENTATION] [DEPENDS: 3.1, 2.2]** Implement `scheduler.py` with three jobs + end-of-day auto-fail
    - Global reminder reads `global_reminder_time` from config at startup; suppressed if all habits logged
    - Trash: cron Mon/Wed/Thu 19:00; Log hours: cron Fri 16:45; Auto-fail: cron daily 23:59
    - All jobs bridge to bot async loop via `asyncio.run_coroutine_threadsafe`
  - [x] 3.3 **[IMPLEMENTATION] [DEPENDS: 3.2]** Timezone passed as parameter to `BackgroundScheduler`; sourced from `TIMEZONE` env var; not hardcoded
  - [x] 3.4 **[IMPLEMENTATION] [DEPENDS: 3.2]** `tests/test_scheduler.py` — 9/9 passing; covers suppression, unlogged cases, missing habit, timezone parameter
  - [x] 3.5 **[REVIEW] [DEPENDS: 3.4]** All three PRD §7.4 reminders present with correct cron schedules; suppression verified in tests; timezone not hardcoded (parameter-driven)

- [x] 4.0 Web Dashboard — Views & Visualizations (ALL SUB-TASKS COMPLETE)
  - [x] 4.1 **[RESEARCH] [DEPENDS: 1.6]** Decide on heatmap and calendar rendering approach: vanilla JS with SVG vs a lightweight library (e.g. cal-heatmap.js); confirm approach works without a build step (CDN or single JS file only — no npm/webpack)
    - Decision: vanilla JS + SVG in `static/charts.js`; no external dependencies; no build step; Flask passes JSON data to a `<script>` block in each template
  - [x] 4.2 **[IMPLEMENTATION] [DEPENDS: 4.1]** `dashboard.py` blueprint + `templates/base.html` + `templates/today.html` with streaks and manual log buttons
  - [x] 4.3 **[IMPLEMENTATION] [DEPENDS: 4.2]** `templates/heatmap.html` + heatmap route; fraction-to-green gradient; hover tooltips; future dates white
  - [x] 4.4 **[IMPLEMENTATION] [DEPENDS: 4.2]** `templates/calendar.html` + calendar route; habit selector; ISO week grid; value text in numeric cells; not_applicable = white
  - [x] 4.5 **[IMPLEMENTATION] [DEPENDS: 4.2]** Streak badges (current streak) shown on each habit card in today view; uses `get_streak()`
  - [x] 4.6 **[IMPLEMENTATION] [DEPENDS: 4.2]** `templates/habits.html` with add/edit/deactivate forms; all fields supported
  - [x] 4.7 **[IMPLEMENTATION] [DEPENDS: 4.3, 4.4, 4.5, 4.6]** `static/style.css` — CSS variables for all 5 outcome colors; mobile-friendly grid layout; `static/charts.js` — vanilla SVG heatmap + 12-month calendar
  - [x] 4.8 **[REVIEW] [DEPENDS: 4.7]** All 5 PRD §7.5 views present; inverse-boolean buttons labeled "No ✓"/"Yes ✗"; partial=amber in CSS; not_applicable=white in charts.js; streak badges on today view; habit manager POSTs to models

- [x] 5.0 Deployment (Railway + Cloudflare) (ALL SUB-TASKS COMPLETE)
  - [x] 5.1 **[RESEARCH] [DEPENDS: 2.9, 3.5, 4.8]** Review Railway's free tier persistent volume setup for SQLite; confirm the database file path survives redeploys; identify if a `Procfile` or `railway.toml` is needed
    - SQLite file must be on a Railway persistent volume (ephemeral filesystem is wiped on redeploy)
    - Create volume in Railway UI → mount at `/data` → set `DATABASE_URL=/data/habits.db`
    - `Procfile` with `web: python app.py` is sufficient; no `railway.toml` required for single-service deploys
    - Use `--workers=1` to prevent duplicate scheduler instances
  - [x] 5.2 **[IMPLEMENTATION] [DEPENDS: 5.1]** Created `Procfile`; `app.py` binds to `$PORT`; `init_db` + `seed_habits` run at module level (not just `__main__`) so gunicorn/Railway startup works correctly
  - [x] 5.3 **[IMPLEMENTATION] [DEPENDS: 5.2]** `docs/SETUP.md` fully populated: local dev, Railway deploy, persistent volume, env vars, Cloudflare CNAME, webhook registration, troubleshooting table
  - [x] 5.4 **[IMPLEMENTATION] [DEPENDS: 5.2]** Test full local run — all commands verified working; fixed PTB 20.8→21.11.1 for Python 3.13 compatibility; fixed missing `application.start()` call; fixed Jinja2 template syntax error in habits.html
  - [x] 5.5 **[REVIEW] [DEPENDS: 5.4]** All env vars documented in SETUP.md; DATABASE_URL points to volume path; no hardcoded paths/tokens in source; webhook secured by CHAT_ID filter in all handlers; app starts cleanly
