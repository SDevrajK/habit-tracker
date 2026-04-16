# PRD: Habit Tracker App

**Project**: Habit Tracker App  
**Code**: HTRK  
**Author**: Sayeed Devraj-Kizuk  
**Date**: 2026-04-16  
**Status**: Draft

---

## 1. Problem Statement

Daily habits are easy to forget and hard to sustain without a lightweight system for logging, reminders, and progress visibility. The goal is a personal tool that removes friction from habit tracking — logging from a phone in seconds, automatic daily reminders, and a clear visual record of consistency over time.

---

## 2. Goals

- Log habit completion from a phone with minimal friction
- Receive targeted reminders at the right time for each habit
- Visualize habit history on a calendar (heatmap, streaks, monthly view)
- Manage the habit list (add, remove, rename, configure) without touching code

---

## 3. Non-Goals

- Social or collaborative features
- Integration with third-party health apps
- Native Android/iOS app
- Multi-user support

---

## 4. Users

Single user (personal tool). Dashboard is public (no authentication required).

---

## 5. Habit Inventory

| Habit | Type | Frequency | Threshold / Notes |
|---|---|---|---|
| Running | Numeric (minutes) | Daily | Configurable min thresholds (e.g. 20 min = ok, 40 min = good) |
| Fast food | Inverse boolean | Daily | "No" = success, "Yes" = failure |
| Brush teeth | Boolean | Daily | — |
| Take medicine | Boolean | Daily | — |
| Job applications | Numeric (count) | Daily | Configurable min thresholds |
| Exercise | Numeric (minutes) | Daily | Configurable min thresholds |
| Log hours | Boolean | Weekly (Friday) | Reminder at 4:45 PM Friday |
| Put out trash | Boolean | Specific days (Mon/Wed/Thu) | Reminder at 7:00 PM on those days only |

---

## 6. Architecture Overview

### Components

| Component | Technology | Purpose |
|---|---|---|
| Telegram Bot | Python, `python-telegram-bot` | Daily logging interface on phone |
| Web Dashboard | Python/Flask + HTML/CSS/JS | Calendar visualization, habit management |
| Database | SQLite | Persistent storage for habits and logs |
| Scheduler | APScheduler (within Flask process) | Per-habit reminder messages |
| Hosting | Railway (free tier) | Always-on deployment |
| Domain | Cloudflare-managed domain | Custom URL for dashboard (e.g. `habits.yourdomain.com`) |

### Data Flow

```
Phone (Telegram) → Bot command → Python backend → SQLite
                                                      ↓
Browser (any device) ← Flask dashboard ← SQLite query
```

The Telegram bot and Flask app run in the same Python process. SQLite is the single source of truth.

---

## 7. Features

### 7.1 Habit Types

**Boolean**: binary yes/no completion (brush teeth, take medicine, log hours, put out trash)

**Inverse Boolean**: binary yes/no where "no" is the successful outcome (fast food).
- Visualization and streaks treat "no" as `completed` and "yes" as `failed`
- Telegram prompt phrasing reflects this: "Did you eat fast food today? (Yes = bad)"

**Numeric**: user logs a quantity; completion is determined by configurable thresholds (running, exercise, job applications)
- `threshold_ok`: minimum value for partial/amber completion
- `threshold_good`: minimum value for full/green completion
- Below `threshold_ok` = red (failed), between thresholds = amber (partial), at or above `threshold_good` = green (completed)
- Logging: bot prompts for a number; quick-select preset buttons shown for common values

### 7.2 Habit Frequencies

**Daily**: appears in every day's log and global reminder

**Weekly (specific day)**: log hours appears in Friday's log and gets a dedicated reminder at 4:45 PM Friday; does not appear other days

**Specific days**: put out trash appears only on Monday, Wednesday, and Thursday; gets a dedicated reminder at 7:00 PM on those days only

### 7.3 Daily Logging via Telegram

Commands the bot responds to:

| Command | Description |
|---|---|
| `/log` | Show today's habits as a tap-through inline checklist |
| `/done <habit>` | Mark a specific habit complete for today |
| `/skip <habit>` | Mark a habit as intentionally skipped (neutral, does not break streak) |
| `/fail <habit>` | Explicitly mark a habit as failed for today |
| `/status` | Show today's completion summary for all applicable habits |
| `/habits` | List all active habits with their types and thresholds |
| `/add <name>` | Add a new habit (bot prompts for type and config) |
| `/remove <name>` | Deactivate a habit |
| `/setreminder HH:MM` | Update the global daily reminder time |

**`/log` inline flow:**
- Bot sends a message listing today's applicable habits
- Each boolean/inverse-boolean habit shows ✓ / ✗ / skip buttons
- Each numeric habit shows quick-select preset buttons (e.g. 0 / 15 / 30 / 45 / 60) plus a "custom" option that prompts for free-text number input
- Tapping a button logs immediately and updates the message to show the recorded value

**Logging states per habit per day:**
- `completed` — logged as done / above threshold / "no" for inverse boolean
- `partial` — numeric value between thresholds (amber)
- `failed` — logged as not done / below threshold / "yes" for inverse boolean / unlogged by end of day
- `skipped` — intentionally skipped (does not count against streak)
- `not_applicable` — habit does not apply on this day (e.g. trash on a Tuesday)

### 7.4 Reminder System

Multiple independent scheduled reminders:

| Reminder | Schedule | Content |
|---|---|---|
| Global daily reminder | Configurable time (default 9:00 PM), every day | Lists all daily habits not yet logged today |
| Trash reminder | 7:00 PM on Monday, Wednesday, Thursday | "Don't forget to put out the trash tonight" (only if unlogged) |
| Log hours reminder | 4:45 PM on Friday | "Log your hours for the week" (only if unlogged) |

Rules:
- A reminder for a habit is suppressed if that habit is already logged for the day
- The global reminder does not include `not_applicable` habits

### 7.5 Web Dashboard

Accessible at `habits.yourdomain.com`. No authentication (public URL, personal data only).

**Views:**

1. **Today's Overview** — current status of each applicable habit for today; manual toggle/input as a fallback to Telegram
2. **Annual Heatmap** — GitHub-style 52-week grid; each cell = one day; color = fraction of applicable habits completed that day (green gradient); hovering shows the date and breakdown
3. **Per-Habit Monthly Calendar** — 12-month grid view for a selected habit; each day colored by outcome (green / amber / red / grey / white)
4. **Streaks Panel** — current streak and all-time best streak per habit
5. **Habit Manager** — add, rename, configure thresholds, deactivate habits via form

### 7.6 Visualization Color Scheme

| Outcome | Color | Applies to |
|---|---|---|
| Completed / above good threshold | Green | All types |
| Partial / between thresholds | Amber | Numeric only |
| Failed / below ok threshold / unlogged | Red | All types |
| Skipped | Grey | All types |
| Not applicable | White / empty | Frequency-gated habits |
| Future date | White / empty | All |

Inverse boolean uses the same color scheme, but maps "no" → green and "yes" → red.

---

## 8. Data Model

### `habits` table

| Column | Type | Description |
|---|---|---|
| id | INTEGER PK | |
| name | TEXT | Display name |
| description | TEXT | Optional notes |
| type | TEXT | `boolean`, `inverse_boolean`, `numeric` |
| frequency | TEXT | `daily`, `weekly`, `specific_days` |
| frequency_days | TEXT | JSON array of weekday ints (0=Mon); null if daily |
| unit | TEXT | Unit label for numeric habits (e.g. "min", "apps"); null for boolean |
| threshold_ok | REAL | Minimum for partial/amber; null for boolean |
| threshold_good | REAL | Minimum for completed/green; null for boolean |
| numeric_presets | TEXT | JSON array of quick-select values for Telegram; null for boolean |
| reminder_time | TEXT | Override reminder time HH:MM for this habit; null = use global |
| active | BOOLEAN | Whether habit is currently tracked |
| created_at | DATE | |

### `logs` table

| Column | Type | Description |
|---|---|---|
| id | INTEGER PK | |
| habit_id | INTEGER FK | References `habits.id` |
| date | DATE | Log date (YYYY-MM-DD) |
| status | TEXT | `completed`, `partial`, `failed`, `skipped`, `not_applicable` |
| value | REAL | Raw value for numeric habits; null for boolean |
| logged_at | DATETIME | Timestamp of when the entry was made |

### `config` table

| Column | Type | Description |
|---|---|---|
| key | TEXT PK | Config key |
| value | TEXT | Config value |

Stored config keys: `global_reminder_time`, `telegram_chat_id`

---

## 9. Deployment

### Hosting
- **Platform**: Railway (free tier, ~$5/month credit — sufficient for this app)
- Single Python process: Flask + Telegram webhook handler + APScheduler

### Domain
- Add a CNAME record in Cloudflare DNS: `habits.yourdomain.com` → Railway app URL
- Enable Cloudflare proxy (orange cloud) for free SSL and CDN

### Environment Variables (set in Railway dashboard)
```
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ID=...    # Your personal Telegram chat ID; bot ignores all other senders
DATABASE_URL=...        # Path to SQLite file or Railway-provided volume path
```

### Telegram Webhook Setup
- Bot uses webhook mode (Telegram pushes messages to Flask endpoint)
- Endpoint: `POST /webhook/<TELEGRAM_TOKEN>`
- Register once after deploy:
  `https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://habits.yourdomain.com/webhook/<TOKEN>`

---

## 10. Project Structure

```
habit-tracker/
├── app.py                  # Flask app entry point, registers blueprints and bot webhook
├── bot.py                  # Telegram command handlers and inline keyboard callbacks
├── scheduler.py            # APScheduler jobs for all reminders
├── models.py               # SQLite database access layer (habits, logs, config)
├── templates/
│   ├── base.html
│   ├── today.html          # Today's overview
│   ├── heatmap.html        # Annual heatmap view
│   ├── calendar.html       # Per-habit monthly calendar view
│   └── habits.html         # Habit manager
├── static/
│   ├── style.css
│   └── charts.js           # Heatmap and calendar rendering (vanilla JS)
├── data/
│   └── habits.db           # SQLite database
├── configs/
│   └── config.py           # App configuration and env var loading
├── tests/
│   ├── test_models.py
│   ├── test_bot.py
│   └── test_scheduler.py
└── requirements.txt
```

---

## 11. Out of Scope (Future Considerations)

- Habit notes / journal entries per log
- Data export (CSV)
- Habit categories or grouping
- Weekly summary report
- Numeric habit graphing over time (line chart)

---

## 12. Success Criteria

- Can log all habits in under 60 seconds from phone via Telegram
- Trash reminder arrives at 7:00 PM on Mon/Wed/Thu and is suppressed if already logged
- Log hours reminder arrives at 4:45 PM on Friday and is suppressed if already logged
- Global reminder at configured time lists only unlogged daily habits
- Dashboard correctly renders annual heatmap, per-habit monthly calendar, and streaks
- Numeric habits display amber/green/red based on configured thresholds
- Inverse boolean (fast food) displays correct color polarity
- Adding or reconfiguring a habit requires no code changes
- System remains available for at least 30 consecutive days without manual intervention
