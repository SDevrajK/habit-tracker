# Habit Tracker

A personal habit-tracking app that combines a Telegram bot with a web dashboard.
Habits are logged via Telegram (or the dashboard), reminders are scheduled
automatically, and progress is visualised as streaks, heatmaps, and calendars.

## Features

- **Telegram bot** — log habits with `/log`, mark them `/done`/`/fail`/`/skip`,
  manage habits (`/add`, `/remove`, `/habits`), and set reminders
- **Web dashboard** (Flask) — today view, annual heatmap, per-habit calendar, and
  a habit manager; protected by optional basic-auth credentials
- **Scheduled reminders** — morning briefing, daily reminders, and end-of-day
  auto-fail via APScheduler cron jobs
- **Fitness & meals** — weight/measurement tracking and meal logging with nutrition
  lookup
- **Streaks** — per-habit streak calculation with a heatmap of completion

## Architecture

A single process (`app.py`) hosts three subsystems:

- **Flask** WSGI server (dashboard + webhook endpoint)
- **python-telegram-bot** application (bot handlers)
- **APScheduler** background scheduler (cron jobs)

Storage is SQLite via a small data-access layer (`models.py`); the bot, dashboard,
and scheduler all share the same connection.

## Setup

### 1. Install

```bash
pip install -r requirements.txt
```

### 2. Configure environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_TOKEN` | yes | Telegram bot token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | yes | Authorised chat ID (messages from other chats are ignored) |
| `DATABASE_URL` | yes | SQLite path (e.g. `sqlite:///habit-tracker.db`) |
| `TIMEZONE` | no | IANA timezone (default `America/Toronto`) |
| `PORT` | no | Flask port (default `5000`) |
| `DASHBOARD_USER` | no | Basic-auth username for the dashboard |
| `DASHBOARD_PASS` | no | Basic-auth password for the dashboard |
| `API_NINJAS_KEY` | no | Key for meal nutrition lookup (optional) |

### 3. Run

```bash
python app.py
```

The dashboard is served at `http://localhost:5000`; the Telegram bot registers its
webhook against `<base_url>/webhook/<TOKEN>`.

## Testing

```bash
pytest
```

The test suite (48 tests) uses a temp-file SQLite database and mocks all Telegram
API calls, so no network access is required.

## Project Structure

```
habit-tracker/
├── app.py            # Flask app factory, bot loop, and scheduler entry point
├── bot.py            # Telegram command and callback handlers
├── scheduler.py      # APScheduler cron jobs (reminders, auto-fail)
├── dashboard.py      # Flask dashboard blueprint
├── fitness.py        # Fitness tracking blueprint
├── meals.py          # Meals blueprint
├── nutrition.py      # Nutrition parsing / API Ninjas lookup
├── models.py         # SQLite data-access layer
├── configs/config.py # Environment-variable configuration
├── templates/        # Jinja2 HTML templates
├── static/           # CSS / JS (heatmap chart)
├── tests/            # Test suite
└── docs/             # Architecture, setup, and project status
```

## License

[MIT](LICENSE)
