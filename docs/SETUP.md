# Habit Tracker — Setup & Deployment Guide

## Prerequisites

- Python 3.11+ (3.13 tested; required for `python-telegram-bot==21.11.1`)
- A Telegram bot token — create via [@BotFather](https://t.me/BotFather) (`/newbot`)
- Your personal Telegram chat ID — send any message to [@userinfobot](https://t.me/userinfobot) to get it
- A Railway account ([railway.app](https://railway.app)) with billing enabled for persistent volumes
- A Cloudflare-managed domain (for the custom `habits.` subdomain)
- `ngrok` for local end-to-end testing (webhook requires a public HTTPS URL)

---

## Installation (local)

### 1. Clone and create a virtual environment

```bash
cd /home/sdevrajk/projects/habit-tracker
python -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Create a `.env` file (gitignored)

```bash
# .env — DO NOT commit this file
TELEGRAM_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
DATABASE_URL=/tmp/habits.db
TIMEZONE=America/Toronto   # optional, this is the default
PORT=5000                  # optional, this is the default
```

Load it before running:

```bash
export $(grep -v '^#' .env | xargs)
```

Or use [python-dotenv](https://pypi.org/project/python-dotenv/) if you add it as a dev dependency.

---

## Configuration

All configuration is loaded by `configs/config.py` at import time. The app fails fast (`EnvironmentError`) if required variables are missing.

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_TOKEN` | Yes | — | Bot API token from @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | — | Your Telegram chat ID; any other ID is silently ignored |
| `DATABASE_URL` | Yes | — | Absolute path to SQLite file (e.g. `/data/habits.db`) |
| `TIMEZONE` | No | `America/Toronto` | Timezone for cron scheduling (IANA format) |
| `PORT` | No | `5000` | Port Flask listens on |

Two keys are also stored in the database `config` table and can be changed at runtime:

| Key | Default | How to change |
|---|---|---|
| `global_reminder_time` | `21:00` | Send `/setreminder HH:MM` to the bot (requires app restart to take effect on scheduler) |
| `timezone` | `America/Toronto` | Direct DB edit |

---

## Development Workflow

### Run locally

```bash
# Ensure env vars are set
python app.py
```

The app starts on `http://localhost:5000`. The web dashboard is at `http://localhost:5000/`.

### Expose localhost for Telegram webhook testing

```bash
ngrok http 5000
```

Copy the `https://xxxx.ngrok.io` URL, then register it as the Telegram webhook:

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://xxxx.ngrok.io/webhook/<TOKEN>"
```

Verify the webhook is registered:

```bash
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
```

Send `/status` to your bot — you should see today's habits listed.

### Run tests

```bash
pytest tests/ -v
```

All 48 tests run without any network access or env vars (test files set dummy vars themselves). Expected output: `48 passed`.

### Adding a new habit via Telegram

Use `/add <name>` in the bot chat and follow the guided conversation. Alternatively, use the web dashboard at `/habits`.

### Changing the global reminder time

Send `/setreminder 20:00` to the bot. This updates the DB. Restart the app (trigger a Railway redeploy) for the new time to be picked up by the scheduler.

---

## Railway Deployment

### Step 1 — Create Railway project

1. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub repo
2. Connect your `habit-tracker` repository
3. Railway detects `Procfile` automatically: `web: python app.py`

### Step 2 — Add a persistent volume

1. Railway dashboard → your service → Settings → Volumes → Add Volume
2. Mount path: `/data`
3. This path persists across redeploys; set `DATABASE_URL=/data/habits.db`

### Step 3 — Set environment variables

In Railway dashboard → Variables:

```
TELEGRAM_TOKEN      = your_bot_token
TELEGRAM_CHAT_ID    = your_telegram_chat_id
DATABASE_URL        = /data/habits.db
TIMEZONE            = America/Toronto
```

Railway injects `PORT` automatically; do not set it manually.

### Step 4 — Deploy

Push to `main`. Railway builds and deploys automatically. Watch logs in the Railway dashboard for:

```
Database initialised at /data/habits.db
Seeded 8 default habits.            ← only on first deploy
Telegram bot application initialised and started.
Scheduler started. Global reminder at 21:00 America/Toronto
```

### Step 5 — Register Telegram webhook

Run once after first deploy (or after changing domain):

```bash
# With Railway-generated domain
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://your-app.up.railway.app/webhook/<TOKEN>"

# With custom domain (after Step 6)
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://habits.sayeeddevrajkizuk.com/webhook/<TOKEN>"
```

### Step 6 — Cloudflare CNAME (custom domain)

1. In Cloudflare DNS for your domain, add a CNAME:
   - Name: `habits`
   - Target: `your-railway-app.up.railway.app`
   - Proxy: **disabled** (grey cloud) initially — Railway needs unproxied DNS for verification
2. In Railway → service → Settings → Domains → Add Custom Domain → enter `habits.yourdomain.com`
3. Wait for Railway SSL provisioning (usually < 5 minutes)
4. Re-enable Cloudflare proxy (orange cloud) — this adds DDoS protection and hides Railway's IP

---

## Common Commands

```bash
# Run tests
pytest tests/ -v

# Run locally (after setting env vars)
python app.py

# Check registered Telegram webhook
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"

# Remove webhook (switch to polling for local debugging without ngrok)
curl "https://api.telegram.org/bot<TOKEN>/deleteWebhook"

# Inspect the SQLite database directly (local)
sqlite3 /tmp/habits.db ".tables"
sqlite3 /tmp/habits.db "SELECT * FROM habits;"
sqlite3 /tmp/habits.db "SELECT * FROM logs ORDER BY date DESC LIMIT 20;"

# Run a single test file
pytest tests/test_models.py -v

# Run a single test
pytest tests/test_models.py::test_streak_skipped_does_not_break -v
```

---

## Debugging

### Local debugging in VSCode

1. Set a breakpoint in any module
2. In `.vscode/launch.json`, add:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Run app.py",
      "type": "python",
      "request": "launch",
      "program": "${workspaceFolder}/app.py",
      "envFile": "${workspaceFolder}/.env",
      "console": "integratedTerminal"
    }
  ]
}
```

3. Note: the bot loop runs in a daemon thread. Breakpoints in async handler functions work normally; just ensure the webhook is registered pointing to your ngrok URL.

### Debugging on Railway

- View live logs: Railway dashboard → your service → Deployments → View Logs
- All modules use `loguru` with DEBUG-level logging for DB operations, INFO for job fires
- To increase log verbosity, add `LOGURU_LEVEL=DEBUG` as a Railway env var (loguru reads this automatically)

### Isolating components for debugging

- **Test models without Flask/bot**: `python -c "from models import init_db, seed_habits; init_db('/tmp/t.db'); seed_habits('/tmp/t.db')"`
- **Test bot handlers without Telegram API**: run `pytest tests/test_bot.py -v` — all handlers are tested with mocked updates
- **Test scheduler logic**: run `pytest tests/test_scheduler.py -v` — all jobs tested with mocked date.today() and mocked send_message

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Bot doesn't respond to messages | Webhook not registered or pointing to wrong URL | Re-run `setWebhook` curl with current domain |
| Bot responds to `/status` but not `/log` buttons | `_bot_loop` not running; PTB `start()` not called | Check startup logs for "Telegram bot application initialised and started" |
| DB data lost after redeploy | SQLite file not on persistent volume | Ensure `DATABASE_URL=/data/habits.db` and Railway volume is mounted at `/data` |
| `EnvironmentError: TELEGRAM_TOKEN not set` | Env var missing | Add var in Railway dashboard → Variables |
| Scheduler reminders firing at wrong clock time | Timezone misconfigured | Set `TIMEZONE=America/Toronto` (or your IANA timezone) in Railway env vars |
| Multiple reminders sent | Multiple Railway replicas running | Use `Procfile` with single `python app.py` process; ensure Railway service is not scaled to multiple instances |
| `ImportError: cannot import name 'PTBObject'` or similar | Wrong PTB version | Ensure `python-telegram-bot==21.11.1` in `requirements.txt`; PTB 20.x has a `__slots__` incompatibility with Python 3.13 |
| `/setreminder` appears to have no effect | Scheduler job not rescheduled at runtime | Trigger a Railway redeploy after calling `/setreminder`; the new time is read from DB at startup |
| Cloudflare SSL error after adding custom domain | Cloudflare proxy enabled before Railway SSL provisioned | Temporarily disable Cloudflare proxy (grey cloud) until Railway shows SSL as active, then re-enable |

---

## Project Structure Reference

```
habit-tracker/
├── app.py           Flask entry point; bot init; webhook endpoint; blueprint + scheduler startup
├── bot.py           Telegram handlers (all commands + /add ConversationHandler)
├── scheduler.py     APScheduler jobs (morning briefing, global reminder, trash, log-hours, last-chance, auto-fail)
├── models.py        SQLite data layer: schema, CRUD, streak calculation, seed data
├── dashboard.py     Flask Blueprint: web dashboard routes and form handlers
├── configs/
│   └── config.py    Environment variable loading; raises EnvironmentError on missing required vars
├── templates/       Jinja2 HTML templates (base, today, heatmap, calendar, habits)
├── static/
│   ├── style.css    CSS variables and layout
│   └── charts.js    Vanilla JS/SVG heatmap and calendar rendering
├── tests/
│   ├── test_models.py      19 tests for data layer
│   ├── test_bot.py         20 tests for bot handlers
│   └── test_scheduler.py   9 tests for scheduler jobs
├── data/            SQLite DB for local dev (gitignored; Railway uses /data volume)
├── docs/            Architecture, status, setup, PRD, tasks
├── requirements.txt 5 packages
└── Procfile         Railway: `web: python app.py`
```
