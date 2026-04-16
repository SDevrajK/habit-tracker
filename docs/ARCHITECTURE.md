# Habit Tracker App - Architecture

## System Design

The app is a single-process Python application that hosts three concurrent subsystems:

1. **Flask WSGI server** — handles incoming HTTP requests: Telegram webhook updates and web dashboard page views/form posts.
2. **PTB asyncio event loop** — runs in a background daemon thread (`_bot_loop`). All Telegram API calls (sending messages, answering callbacks) are dispatched here.
3. **APScheduler BackgroundScheduler** — runs its own thread pool, firing cron jobs at configured times to send Telegram reminders and auto-fail unlogged habits.

All three subsystems share a single SQLite database file, accessed via short-lived per-call connections with WAL mode enabled.

### Webhook flow

```
Telegram servers
    │  POST /webhook/<TOKEN>
    ▼
Flask webhook handler (app.py:58)
    │  asyncio.run_coroutine_threadsafe(process_update, _bot_loop)
    ▼
PTB Application (bot_loop thread)
    │  dispatches to correct CommandHandler / CallbackQueryHandler
    ▼
Handler function (bot.py)
    │  calls models.py functions
    ▼
SQLite (habits.db)
```

The sync/async bridge (`asyncio.run_coroutine_threadsafe`) is used in two places:
- `app.py:65` — Flask → PTB for incoming updates
- `scheduler.py:29` — APScheduler job thread → PTB for outgoing reminder messages

### Startup sequence (`app.py`)

1. `init_db()` + `seed_habits()` — create tables and insert default habits if the DB is empty
2. `build_application()` — construct PTB Application with all handlers registered
3. Start `_bot_loop` daemon thread
4. `application.initialize()` + `application.start()` (blocking, timeout=30s) — PTB lifecycle
5. Register Flask blueprint (`dashboard_bp`)
6. `start_scheduler()` — create and start APScheduler with all six cron jobs
7. `app.run()` — start Flask WSGI server

---

## Data Model

Three tables in SQLite.

### `habits`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | Unique habit identifier |
| `name` | TEXT | NOT NULL UNIQUE | Display name (e.g. "Running") |
| `description` | TEXT | nullable | Optional longer description |
| `type` | TEXT | CHECK IN ('boolean','inverse_boolean','numeric') | Habit type |
| `frequency` | TEXT | CHECK IN ('daily','weekly','specific_days') | How often the habit applies |
| `frequency_days` | TEXT | nullable | JSON array of weekday ints (0=Mon…6=Sun); NULL if daily |
| `unit` | TEXT | nullable | Unit label for numeric habits (e.g. "min", "apps") |
| `threshold_ok` | REAL | nullable | Minimum value for `partial` status (numeric only) |
| `threshold_good` | REAL | nullable | Minimum value for `completed` status (numeric only) |
| `numeric_presets` | TEXT | nullable | JSON array of quick-select values (numeric only) |
| `reminder_time` | TEXT | nullable | Per-habit HH:MM override; NULL = use global_reminder_time |
| `active` | INTEGER | NOT NULL DEFAULT 1 CHECK IN (0,1) | Soft-delete flag |
| `created_at` | DATE | NOT NULL DEFAULT date('now') | Creation date; used as streak lower bound |

### `logs`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | Row identifier |
| `habit_id` | INTEGER | NOT NULL FK→habits(id) | Which habit was logged |
| `date` | DATE | NOT NULL | The date being logged (ISO 8601 string) |
| `status` | TEXT | CHECK IN ('completed','partial','failed','skipped','not_applicable') | Outcome for that day |
| `value` | REAL | nullable | Raw numeric value (numeric habits only) |
| `logged_at` | DATETIME | NOT NULL DEFAULT datetime('now') | UTC timestamp of last update |
| UNIQUE | — | (habit_id, date) | Enforces one log per habit per day; upsert updates existing row |

### `config`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `key` | TEXT | PRIMARY KEY | Config key name |
| `value` | TEXT | NOT NULL | Config value (string) |

Default config rows inserted at `init_db()`:
- `global_reminder_time` = `"21:00"`
- `timezone` = `"America/Toronto"`

---

## Architecture Layers

```
┌─────────────────────────────────────────────────────┐
│  Web Layer (Flask)                                  │
│  app.py — webhook endpoint                          │
│  dashboard.py — Blueprint: /, /heatmap,             │
│                 /calendar, /habits                  │
│  templates/ — Jinja2 HTML                           │
│  static/ — CSS + vanilla JS                         │
├─────────────────────────────────────────────────────┤
│  Bot Layer (python-telegram-bot v21)                │
│  bot.py — CommandHandlers, CallbackQueryHandler,    │
│            ConversationHandler (/add)               │
│  _bot_loop — dedicated asyncio event loop           │
├─────────────────────────────────────────────────────┤
│  Scheduler Layer (APScheduler)                      │
│  scheduler.py — 6 cron jobs (reminders, auto-fail)  │
│  BackgroundScheduler — own thread pool              │
├─────────────────────────────────────────────────────┤
│  Data Layer (SQLite)                                │
│  models.py — schema, CRUD, streak calc, seed data   │
│  habits.db — SQLite file (WAL mode)                 │
└─────────────────────────────────────────────────────┘
```

Each upper layer imports and calls `models.py` directly; no shared state passes between the web layer and the bot layer except through the database.

---

## Data Flow

### Logging a habit via Telegram

1. User sends `/log` → Flask webhook receives POST → bridges to `_bot_loop`
2. `log_command()` in `bot.py:199` queries `models.get_habits_for_day()` and sends one inline keyboard per habit
3. User taps a button → Telegram sends callback_query → `log_callback()` at `bot.py:219`
4. For boolean: calls `models.upsert_log(DB, habit_id, today, status)`
5. For numeric preset: calls `models.upsert_numeric_log(DB, habit_id, today, value)` which derives status via `_derive_status()` then upserts
6. For "Custom": sets `context.user_data["awaiting_custom_habit"]` and waits for a text message; handled by `custom_numeric_input()` at `bot.py:256`
7. Bot edits the inline message to show the updated status line + congratulation message

### Logging a habit via web dashboard

1. User visits `/` → `today_view()` in `dashboard.py:24` → queries `get_habits_for_day()` + `get_log()` + `get_streak()` per habit
2. User submits a log form → `POST /log_habit` → `log_habit()` at `dashboard.py:45`
3. Calls `upsert_numeric_log()` or `upsert_log()` based on habit type
4. Redirects back to `/`

### Scheduler reminder flow

1. APScheduler fires job in its thread at cron time
2. Job function queries models for unlogged habits
3. If suppression condition met (all logged), job returns silently
4. Otherwise calls `_send_message_sync()` at `scheduler.py:27`
5. `_send_message_sync()` calls `asyncio.run_coroutine_threadsafe(bot.send_message(...), _bot_loop).result(timeout=15)`

### Heatmap data build

`heatmap_view()` in `dashboard.py:70` iterates over the past 365 days. For each day it calls `get_habits_for_day()` (frequency-filtered) and `get_logs_for_day()`, computes `fraction = completed_count / applicable_count`, and builds a `{date_str: fraction}` JSON dict passed to the Jinja2 template for rendering by `static/charts.js`.

---

## Key Algorithms

### Streak calculation (`models.get_streak`, line 307)

Two passes over the date range `[min(created_at, earliest_log) … today]`:

**Current streak** — walk backward from today:
- `not_applicable` or day doesn't exist in schedule → skip (continue walking back)
- `skipped` → neutral, continue walking back
- `completed` or `partial` → increment streak counter
- `failed` or unlogged past day → stop

**Best (all-time) streak** — walk forward from lower bound:
- Same skip logic for `not_applicable` / `skipped`
- `completed` or `partial` → increment running counter; update best if larger
- `failed` → reset running counter to 0

The key design decision: `skipped` passes through the streak (doesn't break it, doesn't count toward it). `not_applicable` is completely invisible — the habit didn't apply that day at all. Unlogged past days count as `failed`.

### Numeric status derivation (`models._derive_status`, line 218)

```
value >= threshold_good  →  "completed"
value >= threshold_ok    →  "partial"
otherwise                →  "failed"
```

This logic is centralised in `_derive_status()` and called only by `upsert_numeric_log()`. Direct calls to `upsert_log()` with a numeric habit bypass this (used for "skipped" and "not_applicable").

### Habit frequency filtering (`models._habit_applies_on`, line 110)

```
frequency == "daily"                          →  always True
frequency in ("weekly", "specific_days")      →  date.weekday() in JSON.parse(frequency_days)
```

Both `weekly` and `specific_days` use the same `frequency_days` JSON array. The semantic difference (one day vs multiple days) is enforced at insert time via the UI/bot, not the DB.

### Fuzzy habit name matching (`bot._fuzzy_find`, line 107)

Case-insensitive substring match: `query.lower() in habit_name.lower()`. Returns all matching habits. If exactly one match, proceeds; if zero, reports not found; if multiple, lists them and asks for clarification.

---

## File Organization

```
habit-tracker/
├── app.py              Entry point: Flask app, bot loop, webhook, blueprint + scheduler startup
├── bot.py              Telegram handlers: all commands, callback handling, /add conversation
├── scheduler.py        APScheduler cron jobs: reminders, last-chance, auto-fail
├── models.py           Data layer: SQLite schema, CRUD, streak calc, seed data
├── dashboard.py        Flask Blueprint: web dashboard routes and form handlers
├── configs/
│   └── config.py       Env var loading; fails fast if required vars missing
├── templates/
│   ├── base.html       Shared nav, layout, head (Bootstrap-free, custom CSS)
│   ├── today.html      Today's habits: cards with status, streak, log form
│   ├── heatmap.html    Annual heatmap: passes JSON data to charts.js
│   ├── calendar.html   Per-habit monthly calendar: passes JSON data to charts.js
│   └── habits.html     Habit manager: table with edit/deactivate + add-new form
├── static/
│   ├── style.css       CSS custom properties + layout styles
│   └── charts.js       Vanilla JS for SVG heatmap and calendar grid rendering
├── tests/
│   ├── __init__.py     Empty; marks tests/ as package
│   ├── test_models.py  19 tests: schema, CRUD, frequency filtering, streaks, seed
│   ├── test_bot.py     20 tests: auth, fuzzy find, status formatting, commands
│   └── test_scheduler.py  9 tests: reminder suppression, scheduling timezone
├── data/               Local dev SQLite DB (gitignored; Railway uses /data volume)
├── docs/
│   ├── ARCHITECTURE.md This file
│   ├── PROJECT_STATUS.md Feature status, known issues, next steps
│   ├── SETUP.md        Install, run, deploy, troubleshoot
│   ├── prd/            PRD-habit-tracker.md
│   └── tasks/          tasks-PRD-habit-tracker.md
├── requirements.txt    Five runtime + test dependencies
└── Procfile            Railway start command: `web: python app.py`
```

---

## Configuration

All configuration is via environment variables, loaded in `configs/config.py`.

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_TOKEN` | Yes | — | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | — | Your personal Telegram chat ID; all other chat IDs are silently ignored |
| `DATABASE_URL` | Yes | — | Absolute path to SQLite file (e.g. `/data/habits.db` on Railway, `/tmp/habits.db` locally) |
| `TIMEZONE` | No | `America/Toronto` | Timezone for APScheduler cron jobs and reminder times |
| `PORT` | No | `5000` | Port Flask listens on; Railway injects this automatically |

Additionally, two keys live in the `config` DB table and can be changed at runtime:

| Key | Default | Changed via |
|---|---|---|
| `global_reminder_time` | `21:00` | `/setreminder HH:MM` Telegram command |
| `timezone` | `America/Toronto` | Direct DB edit (not exposed via UI) |

Note: changing `global_reminder_time` via `/setreminder` updates the DB but does not reschedule the already-registered APScheduler job. The new time takes effect on the next app restart.

---

## Error Handling

**Startup failures**: `configs/config.py` raises `EnvironmentError` immediately if `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, or `DATABASE_URL` are missing. This prevents silent misconfiguration.

**Webhook handler** (`app.py:63`): Wrapped in `try/except Exception`; any error logs via `logger.error()` and returns HTTP 500. Telegram will retry the update.

**Scheduler jobs** (`scheduler.py:35`): `_send_message_sync()` wraps `future.result()` in `try/except`; logs the error and returns without crashing. Individual reminder jobs also guard against missing habits (`trash_reminder_job` at `scheduler.py:98`).

**Bot handlers**: No explicit try/except; PTB catches handler exceptions internally and logs them. The auth guard (`_authorised()`) silently returns early for unauthorised chat IDs — no error is raised or logged.

**Database**: All `upsert_log` calls validate `status` against `VALID_STATUSES` and raise `ValueError` on invalid input (`models.py:239`). `update_habit()` validates column names against an allowlist (`models.py:194`) to prevent SQL injection via field names.

**Logging**: All modules use `loguru` logger. Log level defaults are `DEBUG` for config load and DB operations; `INFO` for startup events, seeding, reminder sends; `ERROR` for failures. No log file is configured — logs go to stdout/stderr (visible in Railway dashboard).

---

## Performance Considerations

**Database**: One connection per call (no connection pool). Connections use WAL journal mode, which allows concurrent readers alongside the single writer. For a single-user app with low write frequency, this is sufficient. No connection pooling or ORM overhead.

**Heatmap query** (`dashboard.py:76`): Iterates 365 days, calling `get_habits_for_day()` and `get_logs_for_day()` per day (two DB round-trips × 365 = ~730 queries per page load). Acceptable for the current scale; would need caching or a single aggregating SQL query if habits grow large.

**Streak calculation** (`models.get_streak`): Two linear passes over all dates from `created_at` to today. For habits tracked for months/years, this is O(n) in days. Currently re-computed on every dashboard load; no caching.

**APScheduler thread pool**: Default single-thread executor. All reminder jobs are short (one DB query + one Telegram API call), so no queue buildup expected.

**Flask threading**: `app.run(threaded=True)` enables Flask's built-in threaded mode, allowing concurrent requests. The bot loop runs in its own daemon thread; scheduler in its own pool — all safe for concurrent use given SQLite WAL and per-call connections.
