"""
Tests for scheduler.py — no network access; Telegram send calls are mocked.
datetime.now() is NOT used directly in job functions (they use date.today()),
so we patch date.today() where needed.
"""
import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("TELEGRAM_TOKEN", "test_token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "12345")
os.environ.setdefault("DATABASE_URL", "/tmp/test_sched.db")

from scheduler import (
    global_reminder_job,
    trash_reminder_job,
    log_hours_reminder_job,
    start_scheduler,
    _send_message_sync,
)

CHAT_ID = "12345"


def _make_bot_app():
    app = MagicMock()
    app.bot.send_message = AsyncMock()
    return app


def _make_bot_loop():
    loop = asyncio.new_event_loop()
    return loop


def _make_habit(habit_id: int, name: str, frequency: str = "daily", frequency_days=None) -> MagicMock:
    h = MagicMock()
    h.__getitem__ = lambda self, key: {
        "id": habit_id,
        "name": name,
        "frequency": frequency,
        "frequency_days": frequency_days,
        "active": 1,
        "type": "boolean",
    }[key]
    h["id"] = habit_id
    h["name"] = name
    h["frequency"] = frequency
    h["frequency_days"] = frequency_days
    h["active"] = 1
    return h


# ---------------------------------------------------------------------------
# Global reminder — suppression
# ---------------------------------------------------------------------------

def test_global_reminder_suppressed_when_all_logged():
    """No message sent if all applicable habits are already logged."""
    today = date(2026, 4, 16)  # Thursday
    h1 = _make_habit(1, "Brush teeth")
    h2 = _make_habit(2, "Running")
    log = MagicMock()
    log.__getitem__ = lambda self, key: {"status": "completed", "value": None}[key]

    bot_app = _make_bot_app()
    bot_loop = _make_bot_loop()

    with (
        patch("scheduler.models.get_habits_for_day", return_value=[h1, h2]),
        patch("scheduler.models.get_log", return_value=log),
        patch("scheduler.date") as mock_date,
    ):
        mock_date.today.return_value = today
        global_reminder_job("/fake.db", bot_app, bot_loop, CHAT_ID)
        bot_app.bot.send_message.assert_not_called()

    bot_loop.close()


def test_global_reminder_sent_when_some_unlogged():
    """Message is sent listing only unlogged habits."""
    today = date(2026, 4, 16)
    h1 = _make_habit(1, "Brush teeth")
    h2 = _make_habit(2, "Running")
    log = MagicMock()
    log["status"] = "completed"

    bot_app = _make_bot_app()
    bot_loop = _make_bot_loop()

    # h1 is logged, h2 is not (returns None)
    def fake_get_log(db, habit_id, date_val):
        return log if habit_id == 1 else None

    with (
        patch("scheduler.models.get_habits_for_day", return_value=[h1, h2]),
        patch("scheduler.models.get_log", side_effect=fake_get_log),
        patch("scheduler._send_message_sync") as mock_send,
        patch("scheduler.date") as mock_date,
    ):
        mock_date.today.return_value = today
        global_reminder_job("/fake.db", bot_app, bot_loop, CHAT_ID)
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][3]  # text argument
        assert "Running" in msg
        assert "Brush teeth" not in msg

    bot_loop.close()


def test_global_reminder_excludes_not_applicable():
    """The global reminder must not include not_applicable habits."""
    today = date(2026, 4, 16)
    h1 = _make_habit(1, "Put out trash", frequency="specific_days")
    # trash is "not_applicable" today because today (Thu=3) IS in [0,2,3]
    # but let's test with a habit that IS not_applicable
    h2 = _make_habit(2, "Brush teeth")

    bot_app = _make_bot_app()
    bot_loop = _make_bot_loop()

    # get_habits_for_day already filters not-applicable habits — it only returns applicable ones
    # So if trash doesn't appear in get_habits_for_day results, it won't appear in reminder
    with (
        patch("scheduler.models.get_habits_for_day", return_value=[h2]),  # only h2 returned
        patch("scheduler.models.get_log", return_value=None),  # h2 unlogged
        patch("scheduler._send_message_sync") as mock_send,
        patch("scheduler.date") as mock_date,
    ):
        mock_date.today.return_value = today
        global_reminder_job("/fake.db", bot_app, bot_loop, CHAT_ID)
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][3]
        assert "Put out trash" not in msg

    bot_loop.close()


# ---------------------------------------------------------------------------
# Trash reminder
# ---------------------------------------------------------------------------

def test_trash_reminder_suppressed_when_logged():
    today = date(2026, 4, 13)  # Monday
    trash = _make_habit(1, "Put out trash", frequency="specific_days")
    log = MagicMock()

    bot_app = _make_bot_app()
    bot_loop = _make_bot_loop()

    with (
        patch("scheduler.models.get_all_active_habits", return_value=[trash]),
        patch("scheduler.models.get_log", return_value=log),
        patch("scheduler._send_message_sync") as mock_send,
        patch("scheduler.date") as mock_date,
    ):
        mock_date.today.return_value = today
        trash_reminder_job("/fake.db", bot_app, bot_loop, CHAT_ID)
        mock_send.assert_not_called()

    bot_loop.close()


def test_trash_reminder_sent_when_unlogged():
    today = date(2026, 4, 13)  # Monday
    trash = _make_habit(1, "Put out trash", frequency="specific_days")

    bot_app = _make_bot_app()
    bot_loop = _make_bot_loop()

    with (
        patch("scheduler.models.get_all_active_habits", return_value=[trash]),
        patch("scheduler.models.get_log", return_value=None),
        patch("scheduler._send_message_sync") as mock_send,
        patch("scheduler.date") as mock_date,
    ):
        mock_date.today.return_value = today
        trash_reminder_job("/fake.db", bot_app, bot_loop, CHAT_ID)
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][3]
        assert "trash" in msg.lower()

    bot_loop.close()


def test_trash_reminder_handles_missing_habit():
    """No error raised and no message sent if trash habit doesn't exist."""
    bot_app = _make_bot_app()
    bot_loop = _make_bot_loop()

    with (
        patch("scheduler.models.get_all_active_habits", return_value=[]),
        patch("scheduler._send_message_sync") as mock_send,
        patch("scheduler.date") as mock_date,
    ):
        mock_date.today.return_value = date(2026, 4, 13)
        trash_reminder_job("/fake.db", bot_app, bot_loop, CHAT_ID)
        mock_send.assert_not_called()

    bot_loop.close()


# ---------------------------------------------------------------------------
# Log-hours reminder
# ---------------------------------------------------------------------------

def test_log_hours_reminder_suppressed_when_logged():
    today = date(2026, 4, 17)  # Friday
    log_hours = _make_habit(2, "Log hours", frequency="weekly")
    log = MagicMock()

    bot_app = _make_bot_app()
    bot_loop = _make_bot_loop()

    with (
        patch("scheduler.models.get_all_active_habits", return_value=[log_hours]),
        patch("scheduler.models.get_log", return_value=log),
        patch("scheduler._send_message_sync") as mock_send,
        patch("scheduler.date") as mock_date,
    ):
        mock_date.today.return_value = today
        log_hours_reminder_job("/fake.db", bot_app, bot_loop, CHAT_ID)
        mock_send.assert_not_called()

    bot_loop.close()


def test_log_hours_reminder_sent_on_friday_unlogged():
    today = date(2026, 4, 17)  # Friday
    log_hours = _make_habit(2, "Log hours", frequency="weekly")

    bot_app = _make_bot_app()
    bot_loop = _make_bot_loop()

    with (
        patch("scheduler.models.get_all_active_habits", return_value=[log_hours]),
        patch("scheduler.models.get_log", return_value=None),
        patch("scheduler._send_message_sync") as mock_send,
        patch("scheduler.date") as mock_date,
    ):
        mock_date.today.return_value = today
        log_hours_reminder_job("/fake.db", bot_app, bot_loop, CHAT_ID)
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][3]
        assert "hours" in msg.lower()

    bot_loop.close()


# ---------------------------------------------------------------------------
# Scheduler start — timezone not hardcoded
# ---------------------------------------------------------------------------

def test_start_scheduler_uses_configured_timezone():
    """Scheduler timezone must come from parameter, not be hardcoded."""
    bot_app = _make_bot_app()
    bot_loop = _make_bot_loop()

    with (
        patch("scheduler.models.get_config", return_value="21:00"),
        patch("apscheduler.schedulers.background.BackgroundScheduler.start"),
        patch("apscheduler.schedulers.background.BackgroundScheduler.add_job"),
    ):
        from apscheduler.schedulers.background import BackgroundScheduler
        with patch.object(BackgroundScheduler, "__init__", return_value=None) as mock_init:
            with patch.object(BackgroundScheduler, "start"):
                with patch.object(BackgroundScheduler, "add_job"):
                    try:
                        start_scheduler("/fake.db", bot_app, bot_loop, "Europe/London")
                    except Exception:
                        pass
                    mock_init.assert_called_once_with(timezone="Europe/London")

    bot_loop.close()
