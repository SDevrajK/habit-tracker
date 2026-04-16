# Habit Tracker App - Project Status

## Current Phase

**Deployed and operational.** The app is live at [habits.sayeeddevrajkizuk.com](https://habits.sayeeddevrajkizuk.com), hosted on Railway with a persistent volume at `/data`. The Telegram bot is active, the web dashboard is accessible, and all scheduled reminders are running. No active development tasks; in maintenance/monitoring mode.

---

## Recent Changes

From git log (oldest → newest):

1. **`3f3e62f` Initial implementation** — Full initial build: Flask app, PTB bot, APScheduler, SQLite models, web dashboard, deployment config, 48 tests.
2. **`d6875f2` Add 10 PM last-chance reminder and fix habits template** — Added `last_chance_reminder_job` firing at 22:00 daily; fixed HTML rendering bug in the habits management table template.
3. **`b2f917f` Add congratulation messages on habit logging** — Added `_CONGRATS` and `_PARTIAL_CONGRATS` message lists in `bot.py`; `_congrats()` function returns a random message after `completed` or `partial` logs.
4. **`2c92c55` Add 7 AM morning briefing** — Added `morning_briefing_job` firing at 07:00 daily; lists today's applicable habits with a random encouragement message.
5. **`7e0e0d4` Allow editing habit frequency and frequency_days from habit manager** — Extended `dashboard.edit_habit()` and `habits.html` to include `frequency` and `frequency_days` fields in the edit form; extended `models.update_habit()` allowlist to include these fields.

---

## Feature Completeness

| Feature | Status | Notes |
|---|---|---|
| SQLite data layer (habits, logs, config tables) | Complete | WAL mode, foreign keys, CHECK constraints |
| 8 default seed habits | Complete | Idempotent; only runs if habits table is empty |
| `/status` command | Complete | Shows today's habits with current log status |
| `/log` command (inline keyboard) | Complete | Boolean, inverse_boolean, numeric with presets + custom input |
| `/done`, `/fail`, `/skip` commands | Complete | Fuzzy name matching; ambiguity resolution |
| `/add` command (ConversationHandler) | Complete | 7-step guided flow; supports all habit types |
| `/remove` command | Complete | Soft-deactivate by fuzzy name match |
| `/habits` command | Complete | Lists all active habits with frequency and thresholds |
| `/setreminder` command | Complete | Updates `global_reminder_time` in config table |
| Congratulation messages on logging | Complete | Random from 15 full / 5 partial phrases |
| Auth guard (chat ID whitelist) | Complete | All handlers silently ignore unauthorised IDs |
| 7 AM morning briefing | Complete | Lists today's habits + random encouragement |
| 9 PM global reminder | Complete | Configurable time; suppressed if all logged |
| Specific reminders (trash 19:00, log-hours 16:45) | Complete | Suppressed if already logged |
| 10 PM last-chance reminder | Complete | Lists all still-unlogged habits |
| 23:59 auto-fail for unlogged habits | Complete | Marks all unlogged applicable habits as `failed` |
| Web dashboard: today view | Complete | Habit cards with status, streak, log form |
| Web dashboard: annual heatmap | Complete | 365-day fraction-completed heatmap |
| Web dashboard: per-habit monthly calendar | Complete | Status colour per day for selected habit |
| Web dashboard: habit manager | Complete | Add, edit (name/frequency/thresholds), deactivate |
| Streak calculation | Complete | Handles skipped (neutral), not_applicable (excluded), failed (breaks) |
| Numeric status auto-derivation from thresholds | Complete | threshold_ok → partial; threshold_good → completed |
| Railway deployment | Complete | Persistent volume at `/data`; custom domain via Cloudflare CNAME |
| Telegram webhook | Complete | Registered and verified at habits.sayeeddevrajkizuk.com |
| `/setreminder` live reschedule | Partial | Updates DB but does not reschedule the APScheduler job; requires app restart to take effect |
| Per-habit reminder_time override | Partial | DB column exists and seed data sets it (16:45 for Log hours, 19:00 for Put out trash), but it is not used by the scheduler — individual habits use hardcoded jobs, not the `reminder_time` column |
| Notification on auto-fail | Missing | No Telegram message is sent when habits are auto-failed at 23:59 |
| Dashboard auth | Missing | The web dashboard has no login/auth — anyone who knows the URL can view and log habits |

---

## Test Status

**48 tests, all passing** as of 2026-04-16. Run time: ~1.3 seconds.

| File | Tests | Coverage |
|---|---|---|
| `tests/test_models.py` | 19 | Schema creation; default config; config set/get; `upsert_log` idempotency; numeric status derivation; invalid status raises; daily/weekly/specific_days frequency filtering; inactive habit filtering; streak (basic, skip-neutral, fail-reset, not_applicable-excluded, partial-counts); seed idempotency; seed PRD verification; `get_logs_for_habit` range query |
| `tests/test_bot.py` | 20 | `_authorised` correct/wrong chat; `_fuzzy_find` exact/partial/case-insensitive/no-match/ambiguous; `_habit_status_line` formatting for all statuses; `/done` exact/partial/ambiguous/no-match; unauthorised chat ignored; custom numeric rejects non-numeric, accepts valid number, ignores missing state |
| `tests/test_scheduler.py` | 9 | Global reminder suppressed when all logged; sent with correct habit list; excludes not-applicable habits; trash suppressed/sent/handles-missing-habit; log-hours suppressed/sent; scheduler timezone from parameter |

No tests for: `dashboard.py` routes, `app.py` startup, Procfile/deployment, the annual heatmap aggregation query.

---

## Known Issues

1. **`/setreminder` requires restart**: Calling `/setreminder HH:MM` writes the new time to the DB `config` table, but the APScheduler job was already scheduled with the old time at startup. The new reminder time only takes effect after the next Railway redeploy or app restart.

2. **`reminder_time` column not wired to scheduler**: The `habits.reminder_time` column (populated for "Log hours" at 16:45 and "Put out trash" at 19:00) is not dynamically used by the scheduler. The scheduler has hardcoded jobs for these two habits. Adding a new habit with a custom `reminder_time` via `/add` or the dashboard will not automatically schedule a reminder for it.

3. **Dashboard is unauthenticated**: The web dashboard at `habits.sayeeddevrajkizuk.com` has no login. All routes return data and accept form posts from any visitor. Must be resolved before fitness/body measurement data is added — see PRD-fitness-tracking.md §1 for the spec (HTTP Basic Auth via `DASHBOARD_USER` / `DASHBOARD_PASS` env vars).

4. **Heatmap page is slow on first load**: `heatmap_view()` runs ~730 DB queries (two per day × 365 days) on every page load with no caching. On Railway with a networked filesystem, this could take a noticeable fraction of a second.

5. **No auto-fail notification**: Habits are silently marked `failed` at 23:59 by `end_of_day_auto_fail_job`. There is no Telegram message sent to inform the user which habits were auto-failed.

6. **Streak recalculated on every dashboard load**: `get_streak()` is called once per applicable habit in `today_view()`, each re-scanning the full date range. With many habits and long history, this accumulates.

---

## Dependencies Status

From `requirements.txt`:

| Package | Version | Role |
|---|---|---|
| `Flask` | 3.1.3 | WSGI web framework; blueprint routing; Jinja2 templating |
| `python-telegram-bot` | 21.11.1 | Telegram bot SDK; Application, handlers, ConversationHandler |
| `APScheduler` | 3.10.4 | Background cron scheduling for reminders and auto-fail |
| `loguru` | 0.7.3 | Structured logging throughout all modules |
| `pytest` | 8.3.5 | Test runner |

Note: `python-telegram-bot==21.11.1` is required for Python 3.13 compatibility. Version 20.8 has a `__slots__` bug that causes crashes on Python 3.13. Do not downgrade.

Python stdlib used: `sqlite3`, `asyncio`, `threading`, `json`, `re`, `random`, `datetime`.

---

## Next Steps

Reasonable improvements in priority order:

1. **Live reminder reschedule**: When `/setreminder` is called, reschedule the `global_reminder` APScheduler job immediately using `scheduler.reschedule_job()` rather than requiring a restart.
2. **Dashboard authentication**: Add a simple password or token-based auth to the Flask dashboard, at minimum using HTTP basic auth or a hardcoded secret in an env var.
3. **Auto-fail notification**: Send a Telegram message at 23:59 listing which habits were auto-failed, so the user is aware.
4. **Heatmap query optimisation**: Replace the per-day loop in `heatmap_view()` with a single SQL query aggregating logs grouped by date, to reduce 730 queries to one.
5. **Dynamic per-habit reminders**: Read `habit.reminder_time` at scheduler startup and schedule individual cron jobs for habits that have a non-null `reminder_time`, rather than hardcoding the trash and log-hours jobs.
6. **Streak display on calendar view**: The calendar page shows per-day status but not the current streak. Adding it would make the calendar more useful.
7. **Database backup cron job**: The SQLite file at `/data/habits.db` on Railway's persistent volume is the only copy of all habit and fitness data. Set up a scheduled job to copy it to an off-platform destination (e.g. a private GitHub repo, Dropbox, or S3) on a daily or weekly basis. Loss of the Railway volume = permanent data loss.

---

## Deployment Status

- **Host**: Railway (railway.app)
- **URL**: [habits.sayeeddevrajkizuk.com](https://habits.sayeeddevrajkizuk.com) (Cloudflare CNAME → Railway)
- **Database**: SQLite at `/data/habits.db` on Railway persistent volume
- **Start command** (`Procfile`): `web: python app.py`
- **Telegram webhook**: Registered at `https://habits.sayeeddevrajkizuk.com/webhook/<TOKEN>`
- **Environment variables set in Railway**: `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `DATABASE_URL=/data/habits.db`, `TIMEZONE=America/Toronto`

Redeploys are triggered automatically on push to the `main` branch. The SQLite volume persists across redeploys; only the application code is replaced.

---

## Contact & Ownership

**Owner**: Sayeed Devraj-Kizuk  
**GitHub**: [SDevrajK](https://github.com/SDevrajK)  
**Project code**: HTRK
