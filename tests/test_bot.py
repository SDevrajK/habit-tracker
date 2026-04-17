"""
Tests for bot.py — no Telegram API or network access.
All Telegram objects are mocked.
"""
import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Set required env vars before importing config/bot
os.environ.setdefault("TELEGRAM_TOKEN", "test_token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "12345")
os.environ.setdefault("DATABASE_URL", ":memory:")  # won't be used directly in these tests

from bot import (
    _authorised,
    _fuzzy_find,
    _habit_status_line,
    done_command,
    fail_command,
    skip_command,
    status_command,
)

# ---------------------------------------------------------------------------
# Helpers for building mock Update objects
# ---------------------------------------------------------------------------

AUTHORISED_CHAT_ID = 12345
UNAUTHORISED_CHAT_ID = 99999


def _make_update(chat_id: int, text: str = "/status", args: list[str] = None) -> MagicMock:
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.message.text = text
    update.message.reply_text = AsyncMock()
    # PTB passes args via context, not update
    return update


def _make_context(args: list[str] = None) -> MagicMock:
    ctx = MagicMock()
    ctx.args = args or []
    ctx.user_data = {}
    return ctx


def _make_habit(
    habit_id: int,
    name: str,
    habit_type: str = "boolean",
    frequency: str = "daily",
    unit: str = None,
    threshold_ok: float = None,
    threshold_good: float = None,
) -> MagicMock:
    h = MagicMock()
    h.__getitem__ = lambda self, key: {
        "id": habit_id,
        "name": name,
        "type": habit_type,
        "frequency": frequency,
        "frequency_days": None,
        "unit": unit,
        "threshold_ok": threshold_ok,
        "threshold_good": threshold_good,
        "numeric_presets": None,
        "active": 1,
    }[key]
    h["id"] = habit_id
    h["name"] = name
    h["type"] = habit_type
    h["frequency"] = frequency
    h["unit"] = unit
    h["threshold_ok"] = threshold_ok
    h["threshold_good"] = threshold_good
    return h


def _make_log(status: str, value=None) -> MagicMock:
    log = MagicMock()
    log.__getitem__ = lambda self, key: {"status": status, "value": value}[key]
    log["status"] = status
    log["value"] = value
    return log


# ---------------------------------------------------------------------------
# _authorised
# ---------------------------------------------------------------------------

def test_authorised_correct_chat():
    update = _make_update(AUTHORISED_CHAT_ID)
    assert _authorised(update) is True


def test_authorised_wrong_chat():
    update = _make_update(UNAUTHORISED_CHAT_ID)
    assert _authorised(update) is False


# ---------------------------------------------------------------------------
# _fuzzy_find
# ---------------------------------------------------------------------------

def test_fuzzy_find_exact():
    h1 = _make_habit(1, "Running")
    h2 = _make_habit(2, "Brush teeth")
    assert _fuzzy_find("Running", [h1, h2]) == [h1]


def test_fuzzy_find_partial():
    h1 = _make_habit(1, "Running")
    h2 = _make_habit(2, "Brush teeth")
    # "run" should match "Running"
    matches = _fuzzy_find("run", [h1, h2])
    assert len(matches) == 1
    assert matches[0]["name"] == "Running"


def test_fuzzy_find_case_insensitive():
    h1 = _make_habit(1, "Brush Teeth")
    assert _fuzzy_find("brush", [h1]) == [h1]
    assert _fuzzy_find("BRUSH", [h1]) == [h1]


def test_fuzzy_find_no_match():
    h1 = _make_habit(1, "Running")
    assert _fuzzy_find("yoga", [h1]) == []


def test_fuzzy_find_ambiguous():
    h1 = _make_habit(1, "Running")
    h2 = _make_habit(2, "Run streak")
    matches = _fuzzy_find("run", [h1, h2])
    assert len(matches) == 2


# ---------------------------------------------------------------------------
# _habit_status_line formatting
# ---------------------------------------------------------------------------

def test_status_line_completed():
    h = _make_habit(1, "Brush teeth")
    log = _make_log("completed")
    line = _habit_status_line(h, log)
    assert "✅" in line
    assert "Brush teeth" in line


def test_status_line_failed():
    h = _make_habit(1, "Running", habit_type="numeric", unit="min")
    log = _make_log("failed", value=5.0)
    line = _habit_status_line(h, log)
    assert "❌" in line
    assert "5.0" in line
    assert "min" in line


def test_status_line_no_log():
    h = _make_habit(1, "Exercise")
    line = _habit_status_line(h, None)
    assert "⬜" in line
    assert "Exercise" in line


def test_status_line_partial_with_value():
    h = _make_habit(1, "Running", habit_type="numeric", unit="min")
    log = _make_log("partial", value=25.0)
    line = _habit_status_line(h, log)
    assert "🟡" in line
    assert "25.0" in line


# ---------------------------------------------------------------------------
# /done with exact and partial names
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_done_exact_match():
    update = _make_update(AUTHORISED_CHAT_ID, "/done Running")
    ctx = _make_context(args=["Running"])
    h = _make_habit(1, "Running")
    log = _make_log("completed")

    with (
        patch("bot.models.get_habits_for_day", return_value=[h]),
        patch("bot.models.upsert_log") as mock_upsert,
        patch("bot.models.get_log", return_value=log),
    ):
        await done_command(update, ctx)
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args
        assert call_args[0][3] == "completed"  # upsert_log(db, habit_id, date, status)


@pytest.mark.asyncio
async def test_done_partial_name():
    update = _make_update(AUTHORISED_CHAT_ID, "/done run")
    ctx = _make_context(args=["run"])
    h = _make_habit(1, "Running")
    log = _make_log("completed")

    with (
        patch("bot.models.get_habits_for_day", return_value=[h]),
        patch("bot.models.upsert_log") as mock_upsert,
        patch("bot.models.get_log", return_value=log),
    ):
        await done_command(update, ctx)
        mock_upsert.assert_called_once()


@pytest.mark.asyncio
async def test_done_ambiguous_name_lists_options():
    update = _make_update(AUTHORISED_CHAT_ID, "/done run")
    ctx = _make_context(args=["run"])
    h1 = _make_habit(1, "Running")
    h2 = _make_habit(2, "Run outside")

    with (
        patch("bot.models.get_habits_for_day", return_value=[h1, h2]),
        patch("bot.models.upsert_log") as mock_upsert,
    ):
        await done_command(update, ctx)
        mock_upsert.assert_not_called()
        # Should have replied with the list of options
        update.message.reply_text.assert_called_once()
        reply_text = update.message.reply_text.call_args[0][0]
        assert "Running" in reply_text
        assert "Run outside" in reply_text


@pytest.mark.asyncio
async def test_done_no_match():
    update = _make_update(AUTHORISED_CHAT_ID, "/done yoga")
    ctx = _make_context(args=["yoga"])

    with (
        patch("bot.models.get_habits_for_day", return_value=[_make_habit(1, "Running")]),
        patch("bot.models.upsert_log") as mock_upsert,
    ):
        await done_command(update, ctx)
        mock_upsert.assert_not_called()


# ---------------------------------------------------------------------------
# Unauthorised chat ID is ignored
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unauthorised_chat_id_ignored():
    update = _make_update(UNAUTHORISED_CHAT_ID)
    ctx = _make_context()
    with patch("bot.models.get_habits_for_day") as mock_get:
        await status_command(update, ctx)
        mock_get.assert_not_called()
        update.message.reply_text.assert_not_called()


# ---------------------------------------------------------------------------
# Custom numeric input validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_custom_numeric_rejects_non_numeric():
    from bot import custom_numeric_input

    update = _make_update(AUTHORISED_CHAT_ID, "not-a-number")
    ctx = _make_context()
    ctx.user_data = {"awaiting_custom_habit": {"id": 1, "date": date(2026, 4, 17)}}

    with patch("bot.models.upsert_numeric_log") as mock_upsert:
        await custom_numeric_input(update, ctx)
        mock_upsert.assert_not_called()
        # Bot should prompt the user to try again
        update.message.reply_text.assert_called_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "number" in reply.lower()


@pytest.mark.asyncio
async def test_custom_numeric_accepts_valid_number():
    from bot import custom_numeric_input

    update = _make_update(AUTHORISED_CHAT_ID, "35")
    ctx = _make_context()
    ctx.user_data = {"awaiting_custom_habit": {"id": 1, "date": date(2026, 4, 17)}}
    h = _make_habit(1, "Running", habit_type="numeric", unit="min")
    log = _make_log("partial", value=35.0)

    with (
        patch("bot.models.upsert_numeric_log", return_value="partial"),
        patch("bot.models.get_habit_by_id", return_value=h),
        patch("bot.models.get_log", return_value=log),
    ):
        await custom_numeric_input(update, ctx)
        assert "awaiting_custom_habit" not in ctx.user_data
        update.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_custom_numeric_ignores_no_awaiting_state():
    from bot import custom_numeric_input

    update = _make_update(AUTHORISED_CHAT_ID, "35")
    ctx = _make_context()
    ctx.user_data = {}  # no awaiting state

    with patch("bot.models.upsert_numeric_log") as mock_upsert:
        await custom_numeric_input(update, ctx)
        mock_upsert.assert_not_called()
