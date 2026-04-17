"""
APScheduler reminder jobs.

Three jobs:
1. Global daily reminder  — fires at `global_reminder_time` from config every day;
                            lists unlogged daily habits; suppressed if all logged.
2. Trash reminder         — fires at 19:00 Mon/Wed/Thu; suppressed if trash logged.
3. Log-hours reminder     — fires at 16:45 Friday; suppressed if log-hours logged.

All times are interpreted in the timezone from config (default America/Toronto).
Jobs that call Telegram must bridge to the bot's asyncio event loop via
asyncio.run_coroutine_threadsafe.
"""
import asyncio
import random
from datetime import date, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger

import models


def _today(timezone_name: str) -> date:
    """Return the current local date in the configured timezone (not UTC)."""
    return datetime.now(ZoneInfo(timezone_name)).date()

# Weekday constants (APScheduler uses 0=Mon … 6=Sun for day_of_week)
MON, WED, THU, FRI = "mon", "wed", "thu", "fri"


def _send_message_sync(bot_app, bot_loop: asyncio.AbstractEventLoop, chat_id: str, text: str) -> None:
    """Bridge: send a Telegram message from a sync scheduler job to the async bot loop."""
    future = asyncio.run_coroutine_threadsafe(
        bot_app.bot.send_message(chat_id=chat_id, text=text),
        bot_loop,
    )
    try:
        future.result(timeout=15)
    except Exception as exc:
        logger.error("Failed to send Telegram reminder: {}", exc)


_MORNING_ENCOURAGEMENT = [
    "Let's make today count. 💪",
    "One day at a time. You've got this.",
    "Small steps, big results. 📈",
    "Show up today and the rest takes care of itself.",
    "Another day, another chance to build the habit.",
    "Consistency beats perfection. Get it done.",
    "Today's effort is tomorrow's streak. 🔥",
    "Make it a good one.",
    "You know what to do. Go do it.",
    "Every day you show up, it gets easier.",
]

WEEKDAY_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ---------------------------------------------------------------------------
# Job functions
# ---------------------------------------------------------------------------

def morning_briefing_job(db_path: str, bot_app, bot_loop: asyncio.AbstractEventLoop, chat_id: str, timezone_name: str) -> None:
    """Send a 7 AM morning briefing listing today's habits with encouragement."""
    today = _today(timezone_name)
    habits = models.get_habits_for_day(db_path, today)
    if not habits:
        return
    day_name = WEEKDAY_FULL[today.weekday()]
    habit_list = "\n".join(f"• {h['name']}" for h in habits)
    encouragement = random.choice(_MORNING_ENCOURAGEMENT)
    text = f"☀️ Good morning! Here's your {day_name}:\n\n{habit_list}\n\n{encouragement}"
    _send_message_sync(bot_app, bot_loop, chat_id, text)
    logger.info("Morning briefing sent: {} habits for {}", len(habits), today)


def global_reminder_job(db_path: str, bot_app, bot_loop: asyncio.AbstractEventLoop, chat_id: str, timezone_name: str) -> None:
    """Send reminder listing all unlogged daily habits for today."""
    today = _today(timezone_name)
    habits = models.get_habits_for_day(db_path, today)
    unlogged = []
    for h in habits:
        log_row = models.get_log(db_path, h["id"], today)
        if log_row is None:
            unlogged.append(h["name"])
    if not unlogged:
        logger.debug("Global reminder suppressed — all habits logged for {}", today)
        return
    habit_list = "\n".join(f"• {name}" for name in unlogged)
    text = f"📋 Daily reminder — still unlogged:\n{habit_list}"
    _send_message_sync(bot_app, bot_loop, chat_id, text)
    logger.info("Global reminder sent: {} unlogged habits", len(unlogged))


def trash_reminder_job(db_path: str, bot_app, bot_loop: asyncio.AbstractEventLoop, chat_id: str, timezone_name: str) -> None:
    """Send trash reminder if not yet logged today."""
    today = _today(timezone_name)
    # Find the Put out trash habit by name (case-insensitive match)
    habits = models.get_all_active_habits(db_path)
    trash = next((h for h in habits if "trash" in h["name"].lower()), None)
    if trash is None:
        logger.warning("Trash reminder job: 'Put out trash' habit not found.")
        return
    log_row = models.get_log(db_path, trash["id"], today)
    if log_row is not None:
        logger.debug("Trash reminder suppressed — already logged for {}", today)
        return
    _send_message_sync(bot_app, bot_loop, chat_id, "🗑 Don't forget to put out the trash tonight!")
    logger.info("Trash reminder sent for {}", today)


def log_hours_reminder_job(db_path: str, bot_app, bot_loop: asyncio.AbstractEventLoop, chat_id: str, timezone_name: str) -> None:
    """Send log-hours reminder if not yet logged this Friday."""
    today = _today(timezone_name)
    habits = models.get_all_active_habits(db_path)
    log_hours = next((h for h in habits if "log hours" in h["name"].lower()), None)
    if log_hours is None:
        logger.warning("Log-hours reminder job: 'Log hours' habit not found.")
        return
    log_row = models.get_log(db_path, log_hours["id"], today)
    if log_row is not None:
        logger.debug("Log-hours reminder suppressed — already logged for {}", today)
        return
    _send_message_sync(bot_app, bot_loop, chat_id, "⏱ Don't forget to log your hours for the week!")
    logger.info("Log-hours reminder sent for {}", today)


def end_of_day_auto_fail_job(db_path: str, bot_app, bot_loop: asyncio.AbstractEventLoop, timezone_name: str) -> None:
    """At 23:59, mark all unlogged applicable habits as failed."""
    future = asyncio.run_coroutine_threadsafe(
        _auto_fail_coroutine(db_path, timezone_name),
        bot_loop,
    )
    try:
        future.result(timeout=30)
    except Exception as exc:
        logger.error("Auto-fail job error: {}", exc)


def last_chance_reminder_job(db_path: str, bot_app, bot_loop: asyncio.AbstractEventLoop, chat_id: str, timezone_name: str) -> None:
    """Send a 10 PM last-chance warning listing all still-unlogged habits."""
    today = _today(timezone_name)
    habits = models.get_habits_for_day(db_path, today)
    unlogged = [h["name"] for h in habits if models.get_log(db_path, h["id"], today) is None]
    if not unlogged:
        logger.debug("Last-chance reminder suppressed — all habits logged for {}", today)
        return
    habit_list = "\n".join(f"• {name}" for name in unlogged)
    text = f"⚠️ Last chance — still unlogged tonight:\n{habit_list}"
    _send_message_sync(bot_app, bot_loop, chat_id, text)
    logger.info("Last-chance reminder sent: {} unlogged habits", len(unlogged))


async def _auto_fail_coroutine(db_path: str, timezone_name: str) -> None:
    from bot import auto_fail_unlogged  # local import to avoid circular dep at module load
    # auto_fail_unlogged needs the app object only for potential notifications;
    # we call models directly here to avoid coupling.
    today = _today(timezone_name)
    habits = models.get_habits_for_day(db_path, today)
    count = 0
    for h in habits:
        log_row = models.get_log(db_path, h["id"], today)
        if log_row is None:
            models.upsert_log(db_path, h["id"], today, "failed")
            count += 1
    logger.info("Auto-fail: {} habits marked failed for {}", count, today)


# ---------------------------------------------------------------------------
# Scheduler startup
# ---------------------------------------------------------------------------

def start_scheduler(
    db_path: str,
    bot_app,
    bot_loop: asyncio.AbstractEventLoop,
    timezone_name: str,
) -> BackgroundScheduler:
    from configs.config import Config

    chat_id = Config.TELEGRAM_CHAT_ID

    # Resolve reminder time from config (may be updated at runtime via /setreminder)
    def _get_reminder_hour_minute() -> tuple[int, int]:
        t = models.get_config(db_path, "global_reminder_time") or "21:00"
        h, m = t.split(":")
        return int(h), int(m)

    scheduler = BackgroundScheduler(timezone=timezone_name)

    # --- Morning briefing: 07:00 every day ---
    scheduler.add_job(
        morning_briefing_job,
        trigger="cron",
        hour=7,
        minute=0,
        id="morning_briefing",
        args=[db_path, bot_app, bot_loop, chat_id, timezone_name],
        replace_existing=True,
    )

    # --- Global daily reminder (time loaded at schedule time; reschedule if changed) ---
    reminder_hour, reminder_minute = _get_reminder_hour_minute()
    scheduler.add_job(
        global_reminder_job,
        trigger="cron",
        hour=reminder_hour,
        minute=reminder_minute,
        id="global_reminder",
        args=[db_path, bot_app, bot_loop, chat_id, timezone_name],
        replace_existing=True,
    )

    # --- Trash reminder: 20:00 Mon/Wed/Thu ---
    scheduler.add_job(
        trash_reminder_job,
        trigger="cron",
        day_of_week=f"{MON},{WED},{THU}",
        hour=20,
        minute=0,
        id="trash_reminder",
        args=[db_path, bot_app, bot_loop, chat_id, timezone_name],
        replace_existing=True,
    )

    # --- Log hours reminder: 16:45 Friday ---
    scheduler.add_job(
        log_hours_reminder_job,
        trigger="cron",
        day_of_week=FRI,
        hour=16,
        minute=45,
        id="log_hours_reminder",
        args=[db_path, bot_app, bot_loop, chat_id, timezone_name],
        replace_existing=True,
    )

    # --- Last-chance warning: 22:00 every day ---
    scheduler.add_job(
        last_chance_reminder_job,
        trigger="cron",
        hour=22,
        minute=0,
        id="last_chance_reminder",
        args=[db_path, bot_app, bot_loop, chat_id, timezone_name],
        replace_existing=True,
    )

    # --- End-of-day auto-fail: 23:59 every day ---
    scheduler.add_job(
        end_of_day_auto_fail_job,
        trigger="cron",
        hour=23,
        minute=59,
        id="auto_fail",
        args=[db_path, bot_app, bot_loop, timezone_name],
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "Scheduler started. Global reminder at {}:{:02d} {}",
        reminder_hour, reminder_minute, timezone_name,
    )
    return scheduler
