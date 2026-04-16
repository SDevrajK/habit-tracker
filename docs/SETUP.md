# Habit Tracker — Setup & Deployment Guide

## Prerequisites

- Python 3.11+
- A Telegram bot token (create via @BotFather)
- Your personal Telegram chat ID (send `/start` to @userinfobot)
- A Railway account (railway.app) with billing enabled for persistent volumes
- A Cloudflare-managed domain (for custom subdomain)
- `ngrok` for local end-to-end testing

---

## Local Development

### 1. Install dependencies

```bash
cd /home/sdevrajk/projects/habit-tracker
pip install -r requirements.txt
```

### 2. Set environment variables

```bash
export TELEGRAM_TOKEN=your_bot_token_here
export TELEGRAM_CHAT_ID=your_telegram_chat_id_here
export DATABASE_URL=/tmp/habits.db
export TIMEZONE=America/Toronto   # optional, this is the default
export PORT=5000                  # optional, this is the default
```

### 3. Run locally

```bash
python app.py
```

### 4. Expose localhost with ngrok (for Telegram webhook)

```bash
ngrok http 5000
```

Copy the `https://xxxx.ngrok.io` URL, then register it as your Telegram webhook:

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://xxxx.ngrok.io/webhook/<TOKEN>"
```

### 5. Verify

Send `/status` to your bot. You should see today's habits.

### 6. Run tests

```bash
pytest tests/ -v
```

---

## Railway Deployment

### Step 1 — Create Railway project

1. Go to railway.app → New Project → Deploy from GitHub repo
2. Connect your `habit-tracker` repository

### Step 2 — Add a persistent volume

1. In Railway dashboard → your service → Settings → Add Volume
2. Mount path: `/data`
3. This path survives redeploys; the SQLite file will live at `/data/habits.db`

### Step 3 — Set environment variables

In Railway dashboard → Variables, add:

```
TELEGRAM_TOKEN      = your_bot_token
TELEGRAM_CHAT_ID    = your_telegram_chat_id
DATABASE_URL        = /data/habits.db
TIMEZONE            = America/Toronto
```

Railway automatically injects `PORT`.

### Step 4 — Deploy

Push to your main branch. Railway will build and deploy automatically.
The `Procfile` runs: `python app.py`

### Step 5 — Register Telegram webhook

After first deploy, register the webhook once:

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://your-railway-app.up.railway.app/webhook/<TOKEN>"
```

Or with your custom domain (after Step 6):

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://habits.yourdomain.com/webhook/<TOKEN>"
```

### Step 6 — Cloudflare CNAME (custom domain)

1. In Cloudflare DNS for your domain, add a CNAME record:
   - Name: `habits`
   - Target: `your-railway-app.up.railway.app`
   - Proxy: enabled (orange cloud)
2. In Railway → your service → Settings → Domains → Add Custom Domain
   - Enter `habits.yourdomain.com`
3. Wait for SSL to provision (usually <5 minutes with Cloudflare)

---

## Project Structure

```
habit-tracker/
├── app.py           — Flask entry point; bot init; webhook endpoint; blueprint registration
├── bot.py           — Telegram handlers (all commands + /add ConversationHandler)
├── scheduler.py     — APScheduler jobs (global reminder, trash, log-hours, auto-fail)
├── models.py        — SQLite access layer; schema; CRUD; streak calculation; seed data
├── dashboard.py     — Flask blueprint for web dashboard routes
├── configs/
│   └── config.py    — Environment variable loading; raises on missing required vars
├── templates/       — Jinja2 HTML templates (base, today, heatmap, calendar, habits)
├── static/
│   ├── style.css    — CSS variables + layout
│   └── charts.js    — Vanilla JS/SVG heatmap and calendar rendering
├── tests/
│   ├── test_models.py
│   ├── test_bot.py
│   └── test_scheduler.py
├── data/            — SQLite DB file (local dev only; Railway uses /data volume)
├── requirements.txt
└── Procfile
```

---

## Common Commands

```bash
# Run tests
pytest tests/ -v

# Run locally (after setting env vars)
python app.py

# Check registered Telegram webhook
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"

# Remove webhook (switch to polling for debugging)
curl "https://api.telegram.org/bot<TOKEN>/deleteWebhook"
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Bot doesn't respond | Webhook not registered | Re-run `setWebhook` curl |
| DB lost after redeploy | DB file not on volume | Ensure `DATABASE_URL=/data/habits.db` and volume mounted at `/data` |
| `EnvironmentError: TELEGRAM_TOKEN not set` | Env var missing | Add var in Railway dashboard |
| Scheduler jobs not firing | Multiple workers running | Ensure `Procfile` uses `python app.py`, not gunicorn with multiple workers |
| Reminders at wrong time | Timezone misconfigured | Set `TIMEZONE=America/Toronto` (or your timezone) in Railway env vars |
