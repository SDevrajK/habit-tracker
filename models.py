import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from loguru import logger

# Weekday integers: 0=Monday … 6=Sunday (matches Python's date.weekday())
WEEKDAY_MAP = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}

VALID_STATUSES = {"completed", "partial", "failed", "skipped", "not_applicable"}


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

CREATE_HABITS = """
CREATE TABLE IF NOT EXISTS habits (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    description     TEXT,
    type            TEXT    NOT NULL CHECK(type IN ('boolean','inverse_boolean','numeric')),
    frequency       TEXT    NOT NULL CHECK(frequency IN ('daily','weekly','specific_days')),
    frequency_days  TEXT,           -- JSON array of weekday ints (0=Mon); NULL if daily
    unit            TEXT,           -- e.g. "min", "apps"; NULL for boolean types
    threshold_ok    REAL,           -- minimum for partial/amber; NULL for boolean
    threshold_good  REAL,           -- minimum for completed/green; NULL for boolean
    numeric_presets TEXT,           -- JSON array of quick-select values; NULL for boolean
    reminder_time   TEXT,           -- HH:MM override; NULL = use global_reminder_time
    active          INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at      DATE    NOT NULL DEFAULT (date('now'))
)
"""

CREATE_LOGS = """
CREATE TABLE IF NOT EXISTS logs (
    id          INTEGER  PRIMARY KEY AUTOINCREMENT,
    habit_id    INTEGER  NOT NULL REFERENCES habits(id),
    date        DATE     NOT NULL,
    status      TEXT     NOT NULL CHECK(status IN ('completed','partial','failed','skipped','not_applicable')),
    value       REAL,
    logged_at   DATETIME NOT NULL DEFAULT (datetime('now')),
    UNIQUE(habit_id, date)
)
"""

CREATE_CONFIG = """
CREATE TABLE IF NOT EXISTS config (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
)
"""

CONFIG_DEFAULTS = {
    "global_reminder_time": "21:00",
    "timezone": "America/Toronto",
}


def init_db(db_path: str) -> None:
    """Create tables and insert default config values if they don't exist."""
    conn = get_connection(db_path)
    with conn:
        conn.execute(CREATE_HABITS)
        conn.execute(CREATE_LOGS)
        conn.execute(CREATE_CONFIG)
        for key, value in CONFIG_DEFAULTS.items():
            conn.execute(
                "INSERT OR IGNORE INTO config(key, value) VALUES (?, ?)", (key, value)
            )
    conn.close()
    logger.info("Database initialised at {}", db_path)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def get_config(db_path: str, key: str) -> Optional[str]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def set_config(db_path: str, key: str, value: str) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            "INSERT INTO config(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
    conn.close()
    logger.debug("Config set: {}={}", key, value)


# ---------------------------------------------------------------------------
# Habits
# ---------------------------------------------------------------------------

def _habit_applies_on(habit: sqlite3.Row, target_date: date) -> bool:
    """Return True if the habit is applicable on the given date."""
    freq = habit["frequency"]
    if freq == "daily":
        return True
    if freq in ("weekly", "specific_days"):
        days = json.loads(habit["frequency_days"] or "[]")
        return target_date.weekday() in days
    return False


def get_habits_for_day(db_path: str, target_date: date) -> list[sqlite3.Row]:
    """Return active habits applicable on target_date, ordered by id."""
    conn = get_connection(db_path)
    habits = conn.execute(
        "SELECT * FROM habits WHERE active = 1 ORDER BY id"
    ).fetchall()
    conn.close()
    return [h for h in habits if _habit_applies_on(h, target_date)]


def get_all_active_habits(db_path: str) -> list[sqlite3.Row]:
    conn = get_connection(db_path)
    rows = conn.execute("SELECT * FROM habits WHERE active = 1 ORDER BY id").fetchall()
    conn.close()
    return rows


def get_habit_by_id(db_path: str, habit_id: int) -> Optional[sqlite3.Row]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM habits WHERE id = ?", (habit_id,)).fetchone()
    conn.close()
    return row


def add_habit(
    db_path: str,
    name: str,
    habit_type: str,
    frequency: str,
    frequency_days: Optional[list[int]] = None,
    description: Optional[str] = None,
    unit: Optional[str] = None,
    threshold_ok: Optional[float] = None,
    threshold_good: Optional[float] = None,
    numeric_presets: Optional[list[int]] = None,
    reminder_time: Optional[str] = None,
) -> int:
    conn = get_connection(db_path)
    with conn:
        cursor = conn.execute(
            """INSERT INTO habits
               (name, description, type, frequency, frequency_days, unit,
                threshold_ok, threshold_good, numeric_presets, reminder_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name,
                description,
                habit_type,
                frequency,
                json.dumps(frequency_days) if frequency_days is not None else None,
                unit,
                threshold_ok,
                threshold_good,
                json.dumps(numeric_presets) if numeric_presets is not None else None,
                reminder_time,
            ),
        )
    habit_id = cursor.lastrowid
    conn.close()
    logger.info("Habit added: id={} name={}", habit_id, name)
    return habit_id


def deactivate_habit(db_path: str, habit_id: int) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute("UPDATE habits SET active = 0 WHERE id = ?", (habit_id,))
    conn.close()
    logger.info("Habit deactivated: id={}", habit_id)


def update_habit(db_path: str, habit_id: int, **fields) -> None:
    """Update arbitrary habit columns. Caller is responsible for valid column names."""
    allowed = {
        "name", "description", "threshold_ok", "threshold_good",
        "numeric_presets", "reminder_time", "active",
    }
    invalid = set(fields) - allowed
    if invalid:
        raise ValueError(f"Invalid habit fields: {invalid}")
    if "numeric_presets" in fields and isinstance(fields["numeric_presets"], list):
        fields["numeric_presets"] = json.dumps(fields["numeric_presets"])
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [habit_id]
    conn = get_connection(db_path)
    with conn:
        conn.execute(f"UPDATE habits SET {set_clause} WHERE id = ?", values)
    conn.close()


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

def _derive_status(habit: sqlite3.Row, value: Optional[float]) -> str:
    """Derive the correct log status for a numeric habit from its raw value."""
    if habit["type"] != "numeric":
        raise ValueError("_derive_status is only for numeric habits")
    if value is None:
        return "failed"
    if value >= habit["threshold_good"]:
        return "completed"
    if value >= habit["threshold_ok"]:
        return "partial"
    return "failed"


def upsert_log(
    db_path: str,
    habit_id: int,
    log_date: date,
    status: str,
    value: Optional[float] = None,
) -> None:
    """Insert or update a log entry for (habit_id, date). Idempotent on re-call."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Must be one of {VALID_STATUSES}")
    date_str = log_date.isoformat()
    logged_at = datetime.now(timezone.utc).isoformat()
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            """INSERT INTO logs(habit_id, date, status, value, logged_at)
               VALUES(?, ?, ?, ?, ?)
               ON CONFLICT(habit_id, date)
               DO UPDATE SET status=excluded.status,
                             value=excluded.value,
                             logged_at=excluded.logged_at""",
            (habit_id, date_str, status, value, logged_at),
        )
    conn.close()
    logger.debug("Log upserted: habit_id={} date={} status={} value={}", habit_id, date_str, status, value)


def upsert_numeric_log(
    db_path: str, habit_id: int, log_date: date, value: float
) -> str:
    """Derive status from thresholds, then upsert. Returns the derived status."""
    habit = get_habit_by_id(db_path, habit_id)
    if habit is None:
        raise ValueError(f"Habit {habit_id} not found")
    status = _derive_status(habit, value)
    upsert_log(db_path, habit_id, log_date, status, value)
    return status


def get_log(db_path: str, habit_id: int, log_date: date) -> Optional[sqlite3.Row]:
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT * FROM logs WHERE habit_id = ? AND date = ?",
        (habit_id, log_date.isoformat()),
    ).fetchone()
    conn.close()
    return row


def get_logs_for_habit(
    db_path: str, habit_id: int, start: date, end: date
) -> list[sqlite3.Row]:
    """Return log rows for habit_id between start and end dates inclusive, ordered by date."""
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM logs WHERE habit_id = ? AND date BETWEEN ? AND ? ORDER BY date",
        (habit_id, start.isoformat(), end.isoformat()),
    ).fetchall()
    conn.close()
    return rows


def get_logs_for_day(db_path: str, log_date: date) -> list[sqlite3.Row]:
    """Return all log rows for a given date."""
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM logs WHERE date = ?", (log_date.isoformat(),)
    ).fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Streaks
# ---------------------------------------------------------------------------

def get_streak(db_path: str, habit_id: int) -> dict:
    """
    Compute current and all-time best streak for a habit.

    Rules (per PRD §7.3):
    - 'completed' or 'partial' → counts toward streak
    - 'skipped' → neutral; does not break and does not extend streak
    - 'not_applicable' → excluded entirely (treated as if the day doesn't exist)
    - 'failed' → breaks streak
    - Days with no log entry are treated as 'failed' for past dates
    """
    habit = get_habit_by_id(db_path, habit_id)
    if habit is None:
        raise ValueError(f"Habit {habit_id} not found")

    today = date.today()
    created_at = date.fromisoformat(habit["created_at"])

    # Build a dict of {date: status} from all log entries
    conn = get_connection(db_path)
    log_rows = conn.execute(
        "SELECT date, status FROM logs WHERE habit_id = ? ORDER BY date",
        (habit_id,),
    ).fetchall()
    conn.close()
    log_map: dict[date, str] = {date.fromisoformat(r["date"]): r["status"] for r in log_rows}

    if not log_map:
        return {"current": 0, "best": 0}

    # Lower bound: earliest of created_at or earliest log (handles seeded historical logs)
    lower_bound = min(created_at, min(log_map.keys()))

    def effective_status(d: date) -> Optional[str]:
        """Return the status for date d, or None if not applicable / future."""
        if d > today:
            return None
        if not _habit_applies_on(habit, d):
            return None  # not applicable — skip entirely
        return log_map.get(d, "failed")  # unlogged past days count as failed

    # Walk backwards from today to compute current streak
    current_streak = 0
    cursor = today
    while cursor >= lower_bound:
        s = effective_status(cursor)
        if s in (None, "skipped", "not_applicable"):
            cursor -= timedelta(days=1)
            continue
        if s in ("completed", "partial"):
            current_streak += 1
        else:  # failed
            break
        cursor -= timedelta(days=1)

    # Walk forward from lower_bound to compute all-time best streak
    best_streak = 0
    running = 0
    d = lower_bound
    while d <= today:
        s = effective_status(d)
        if s in (None, "skipped", "not_applicable"):
            d += timedelta(days=1)
            continue
        if s in ("completed", "partial"):
            running += 1
            best_streak = max(best_streak, running)
        else:
            running = 0
        d += timedelta(days=1)

    best_streak = max(best_streak, current_streak)
    return {"current": current_streak, "best": best_streak}


# ---------------------------------------------------------------------------
# Seed data (PRD §5)
# ---------------------------------------------------------------------------

# Weekday constants
MON, WED, THU, FRI = 0, 2, 3, 4

_SEED_HABITS = [
    # (name, type, frequency, frequency_days, unit, threshold_ok, threshold_good, numeric_presets, reminder_time)
    ("Running",          "numeric",         "daily",         None,             "min", 20.0, 40.0, [0, 15, 20, 30, 45, 60], None),
    ("Fast food",        "inverse_boolean", "daily",         None,             None,  None, None, None,                    None),
    ("Brush teeth",      "boolean",         "daily",         None,             None,  None, None, None,                    None),
    ("Take medicine",    "boolean",         "daily",         None,             None,  None, None, None,                    None),
    ("Job applications", "numeric",         "daily",         None,             "apps", 1.0, 3.0, [0, 1, 2, 3, 5, 10],     None),
    ("Exercise",         "numeric",         "daily",         None,             "min", 20.0, 45.0, [0, 15, 20, 30, 45, 60], None),
    ("Log hours",        "boolean",         "weekly",        [FRI],            None,  None, None, None,                    "16:45"),
    ("Put out trash",    "boolean",         "specific_days", [MON, WED, THU],  None,  None, None, None,                    "19:00"),
]


def seed_habits(db_path: str) -> None:
    """Insert the 8 default habits from PRD §5. Runs only if habits table is empty."""
    conn = get_connection(db_path)
    count = conn.execute("SELECT COUNT(*) FROM habits").fetchone()[0]
    conn.close()
    if count > 0:
        logger.debug("Habits table already populated ({} rows); skipping seed.", count)
        return

    for (name, habit_type, frequency, frequency_days, unit,
         threshold_ok, threshold_good, numeric_presets, reminder_time) in _SEED_HABITS:
        add_habit(
            db_path,
            name=name,
            habit_type=habit_type,
            frequency=frequency,
            frequency_days=frequency_days,
            unit=unit,
            threshold_ok=threshold_ok,
            threshold_good=threshold_good,
            numeric_presets=numeric_presets,
            reminder_time=reminder_time,
        )
    logger.info("Seeded {} default habits.", len(_SEED_HABITS))
