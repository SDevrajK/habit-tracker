"""
Flask entry point.

Architecture:
- A persistent asyncio event loop runs in a background daemon thread (bot_loop).
- Flask's webhook endpoint receives Telegram updates and hands them to the bot
  via asyncio.run_coroutine_threadsafe, bridging sync Flask with async PTB v20.
- APScheduler BackgroundScheduler runs its own thread pool alongside Flask.
- SQLite uses check_same_thread=False with one connection per call.
"""
import asyncio
import json
import threading
from datetime import date

from flask import Flask, jsonify, request
from loguru import logger
from telegram import Update

from configs.config import Config
from models import get_habits_for_day, get_log, get_streak, init_db, seed_habits

# Initialise database and seed on every startup (idempotent operations).
init_db(Config.DATABASE_URL)
seed_habits(Config.DATABASE_URL)

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Telegram bot initialisation (deferred import to avoid circular deps)
# ---------------------------------------------------------------------------

from bot import build_application  # noqa: E402 — must come after app creation

_bot_application = build_application(Config.TELEGRAM_TOKEN)

# Run the bot's asyncio event loop in a dedicated daemon thread.
_bot_loop = asyncio.new_event_loop()

def _run_bot_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()

_bot_thread = threading.Thread(target=_run_bot_loop, args=(_bot_loop,), daemon=True)
_bot_thread.start()

# Initialise and start the Application on the bot loop.
# Both initialize() and start() are required before process_update() will work.
asyncio.run_coroutine_threadsafe(_bot_application.initialize(), _bot_loop).result(timeout=30)
asyncio.run_coroutine_threadsafe(_bot_application.start(), _bot_loop).result(timeout=30)
logger.info("Telegram bot application initialised and started.")


# ---------------------------------------------------------------------------
# Telegram webhook endpoint
# ---------------------------------------------------------------------------

@app.post(f"/webhook/{Config.TELEGRAM_TOKEN}")
def telegram_webhook():
    data = request.get_json(force=True, silent=True)
    if not data:
        return "", 400
    try:
        update = Update.de_json(data, _bot_application.bot)
        asyncio.run_coroutine_threadsafe(
            _bot_application.process_update(update), _bot_loop
        ).result(timeout=10)
    except Exception as exc:
        logger.error("Webhook processing error: {}", exc)
        return "", 500
    return "", 200


# ---------------------------------------------------------------------------
# Dashboard blueprint registration
# ---------------------------------------------------------------------------

from dashboard import dashboard_bp  # noqa: E402
from fitness import fitness_bp  # noqa: E402

app.register_blueprint(dashboard_bp)
app.register_blueprint(fitness_bp)


# ---------------------------------------------------------------------------
# Scheduler startup
# ---------------------------------------------------------------------------

from scheduler import start_scheduler  # noqa: E402

start_scheduler(Config.DATABASE_URL, _bot_application, _bot_loop, Config.TIMEZONE)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=Config.PORT, threaded=True)
