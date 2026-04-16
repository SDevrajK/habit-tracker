"""
Tests for models.py — uses an in-memory SQLite database for isolation.
No network access; no Telegram API calls.
"""
import json
from datetime import date, timedelta

import pytest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from models import (
    init_db,
    add_habit,
    deactivate_habit,
    get_habits_for_day,
    get_all_active_habits,
    get_habit_by_id,
    upsert_log,
    upsert_numeric_log,
    get_log,
    get_logs_for_habit,
    get_streak,
    get_config,
    set_config,
    seed_habits,
    _SEED_HABITS,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    """Fresh in-memory-equivalent DB per test (file in tmp_path for sqlite3 compat)."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    return db_path


@pytest.fixture
def boolean_habit(db):
    habit_id = add_habit(db, name="Test boolean", habit_type="boolean", frequency="daily")
    return habit_id, db


@pytest.fixture
def numeric_habit(db):
    habit_id = add_habit(
        db,
        name="Test numeric",
        habit_type="numeric",
        frequency="daily",
        unit="min",
        threshold_ok=20.0,
        threshold_good=40.0,
        numeric_presets=[0, 20, 40, 60],
    )
    return habit_id, db


@pytest.fixture
def inverse_habit(db):
    habit_id = add_habit(db, name="Fast food", habit_type="inverse_boolean", frequency="daily")
    return habit_id, db


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------

def test_schema_creation(db):
    """Tables should exist after init_db."""
    import sqlite3
    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert {"habits", "logs", "config"} <= tables


def test_default_config_inserted(db):
    assert get_config(db, "global_reminder_time") == "21:00"
    assert get_config(db, "timezone") == "America/Toronto"


def test_config_missing_key_returns_none(db):
    assert get_config(db, "nonexistent_key") is None


def test_set_config_creates_and_updates(db):
    set_config(db, "global_reminder_time", "20:00")
    assert get_config(db, "global_reminder_time") == "20:00"
    set_config(db, "global_reminder_time", "22:30")
    assert get_config(db, "global_reminder_time") == "22:30"


# ---------------------------------------------------------------------------
# upsert_log idempotency
# ---------------------------------------------------------------------------

def test_upsert_log_idempotency(boolean_habit):
    """Re-logging the same habit on the same day updates rather than inserts."""
    import sqlite3
    habit_id, db = boolean_habit
    today = date.today()
    upsert_log(db, habit_id, today, "completed")
    upsert_log(db, habit_id, today, "failed")  # update
    row = get_log(db, habit_id, today)
    assert row["status"] == "failed"
    # Only one row should exist
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM logs WHERE habit_id=? AND date=?",
                         (habit_id, today.isoformat())).fetchone()[0]
    conn.close()
    assert count == 1


def test_upsert_numeric_log_derives_status(numeric_habit):
    habit_id, db = numeric_habit
    today = date.today()
    # Below threshold_ok → failed
    status = upsert_numeric_log(db, habit_id, today, value=10.0)
    assert status == "failed"
    # Between thresholds → partial
    status = upsert_numeric_log(db, habit_id, today, value=30.0)
    assert status == "partial"
    # At or above threshold_good → completed
    status = upsert_numeric_log(db, habit_id, today, value=40.0)
    assert status == "completed"


def test_upsert_log_invalid_status_raises(boolean_habit):
    habit_id, db = boolean_habit
    with pytest.raises(ValueError, match="Invalid status"):
        upsert_log(db, habit_id, date.today(), "excellent")


# ---------------------------------------------------------------------------
# get_habits_for_day filtering
# ---------------------------------------------------------------------------

def test_daily_habit_appears_every_day(db):
    add_habit(db, "Daily thing", "boolean", "daily")
    monday = date(2026, 4, 13)   # a Monday
    sunday = date(2026, 4, 19)   # a Sunday
    for d in (monday, sunday):
        habits = get_habits_for_day(db, d)
        assert any(h["name"] == "Daily thing" for h in habits)


def test_weekly_habit_appears_only_on_correct_weekday(db):
    # Log hours: weekly, Friday only (weekday 4)
    add_habit(db, "Log hours", "boolean", "weekly", frequency_days=[4])
    friday = date(2026, 4, 17)    # Friday
    thursday = date(2026, 4, 16)  # Thursday
    friday_habits = [h["name"] for h in get_habits_for_day(db, friday)]
    thursday_habits = [h["name"] for h in get_habits_for_day(db, thursday)]
    assert "Log hours" in friday_habits
    assert "Log hours" not in thursday_habits


def test_specific_days_habit_filtered_correctly(db):
    # Put out trash: Mon/Wed/Thu (0, 2, 3)
    add_habit(db, "Put out trash", "boolean", "specific_days", frequency_days=[0, 2, 3])
    monday    = date(2026, 4, 13)  # weekday 0
    tuesday   = date(2026, 4, 14)  # weekday 1 — should NOT appear
    wednesday = date(2026, 4, 15)  # weekday 2
    thursday  = date(2026, 4, 16)  # weekday 3
    friday    = date(2026, 4, 17)  # weekday 4 — should NOT appear

    for expected_day in (monday, wednesday, thursday):
        names = [h["name"] for h in get_habits_for_day(db, expected_day)]
        assert "Put out trash" in names, f"Expected trash on {expected_day}"

    for excluded_day in (tuesday, friday):
        names = [h["name"] for h in get_habits_for_day(db, excluded_day)]
        assert "Put out trash" not in names, f"Did not expect trash on {excluded_day}"


def test_inactive_habit_not_returned(db):
    habit_id = add_habit(db, "Inactive habit", "boolean", "daily")
    deactivate_habit(db, habit_id)
    habits = get_habits_for_day(db, date.today())
    assert not any(h["name"] == "Inactive habit" for h in habits)


# ---------------------------------------------------------------------------
# Streak calculation
# ---------------------------------------------------------------------------

def test_streak_basic_consecutive(db):
    habit_id = add_habit(db, "Streak test", "boolean", "daily")
    today = date.today()
    for i in range(5):
        upsert_log(db, habit_id, today - timedelta(days=i), "completed")
    result = get_streak(db, habit_id)
    assert result["current"] == 5
    assert result["best"] >= 5


def test_streak_skipped_does_not_break(db):
    """Skipped days are neutral — streak continues across them."""
    habit_id = add_habit(db, "Skip test", "boolean", "daily")
    today = date.today()
    upsert_log(db, habit_id, today, "completed")
    upsert_log(db, habit_id, today - timedelta(days=1), "skipped")
    upsert_log(db, habit_id, today - timedelta(days=2), "completed")
    result = get_streak(db, habit_id)
    # skipped day is neutral — streak should be 2 active days
    assert result["current"] == 2


def test_streak_failed_resets(db):
    habit_id = add_habit(db, "Fail test", "boolean", "daily")
    today = date.today()
    upsert_log(db, habit_id, today, "completed")
    upsert_log(db, habit_id, today - timedelta(days=1), "failed")
    upsert_log(db, habit_id, today - timedelta(days=2), "completed")
    result = get_streak(db, habit_id)
    assert result["current"] == 1  # only today counts; failed breaks streak
    assert result["best"] >= 1


def test_streak_not_applicable_excluded(db):
    """not_applicable days are excluded entirely from streak computation."""
    habit_id = add_habit(db, "N/A test", "boolean", "daily")
    today = date.today()
    upsert_log(db, habit_id, today, "completed")
    upsert_log(db, habit_id, today - timedelta(days=1), "not_applicable")
    upsert_log(db, habit_id, today - timedelta(days=2), "completed")
    result = get_streak(db, habit_id)
    # not_applicable is skipped over — streak should be 2
    assert result["current"] == 2


def test_streak_partial_counts_as_success(db):
    """partial status (numeric between thresholds) should extend the streak."""
    habit_id = add_habit(
        db, "Partial test", "numeric", "daily",
        unit="min", threshold_ok=20.0, threshold_good=40.0
    )
    today = date.today()
    upsert_log(db, habit_id, today, "partial")
    upsert_log(db, habit_id, today - timedelta(days=1), "completed")
    result = get_streak(db, habit_id)
    assert result["current"] == 2


# ---------------------------------------------------------------------------
# Seed habits
# ---------------------------------------------------------------------------

def test_seed_habits_inserts_all_eight(db):
    seed_habits(db)
    habits = get_all_active_habits(db)
    assert len(habits) == len(_SEED_HABITS)


def test_seed_habits_idempotent(db):
    """Calling seed twice should not double-insert."""
    seed_habits(db)
    seed_habits(db)
    habits = get_all_active_habits(db)
    assert len(habits) == len(_SEED_HABITS)


def test_seed_habits_match_prd(db):
    """Verify specific habit properties match PRD §5."""
    seed_habits(db)
    habits = {h["name"]: h for h in get_all_active_habits(db)}

    # Log hours: weekly, Friday only, reminder at 16:45
    log_hours = habits["Log hours"]
    assert log_hours["frequency"] == "weekly"
    assert json.loads(log_hours["frequency_days"]) == [4]  # Friday
    assert log_hours["reminder_time"] == "16:45"

    # Put out trash: specific days Mon/Wed/Thu, reminder at 19:00
    trash = habits["Put out trash"]
    assert trash["frequency"] == "specific_days"
    assert set(json.loads(trash["frequency_days"])) == {0, 2, 3}
    assert trash["reminder_time"] == "19:00"

    # Fast food: inverse_boolean
    assert habits["Fast food"]["type"] == "inverse_boolean"

    # Running: numeric with thresholds
    running = habits["Running"]
    assert running["type"] == "numeric"
    assert running["threshold_ok"] == 20.0
    assert running["threshold_good"] == 40.0


# ---------------------------------------------------------------------------
# get_logs_for_habit range query
# ---------------------------------------------------------------------------

def test_get_logs_for_habit_range(db):
    habit_id = add_habit(db, "Range test", "boolean", "daily")
    today = date.today()
    for i in range(7):
        upsert_log(db, habit_id, today - timedelta(days=i), "completed")
    # Query last 3 days only
    rows = get_logs_for_habit(db, habit_id, today - timedelta(days=2), today)
    assert len(rows) == 3
    dates = {r["date"] for r in rows}
    for i in range(3):
        assert (today - timedelta(days=i)).isoformat() in dates
