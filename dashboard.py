"""
Flask blueprint for the web dashboard.
Routes: /, /heatmap, /calendar, /habits
"""
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from loguru import logger

import models
from configs.config import Config

DB = Config.DATABASE_URL


def _today() -> date:
    """Return the current local date in the configured timezone (not UTC)."""
    return datetime.now(ZoneInfo(Config.TIMEZONE)).date()


dashboard_bp = Blueprint("dashboard", __name__)


# ---------------------------------------------------------------------------
# Today's overview
# ---------------------------------------------------------------------------

@dashboard_bp.get("/")
def today_view():
    today = _today()
    habits = models.get_habits_for_day(DB, today)
    habit_data = []
    for h in habits:
        log_row = models.get_log(DB, h["id"], today)
        streak = models.get_streak(DB, h["id"], today=today)
        habit_data.append({
            "id": h["id"],
            "name": h["name"],
            "type": h["type"],
            "unit": h["unit"],
            "threshold_ok": h["threshold_ok"],
            "threshold_good": h["threshold_good"],
            "status": log_row["status"] if log_row else None,
            "value": log_row["value"] if log_row else None,
            "streak": streak["current"],
        })
    return render_template("today.html", habits=habit_data, today=today)


@dashboard_bp.post("/log_habit")
def log_habit():
    """Manual log from the web dashboard (fallback to Telegram)."""
    habit_id = int(request.form["habit_id"])
    status = request.form.get("status")
    value = request.form.get("value")
    today = _today()

    habit = models.get_habit_by_id(DB, habit_id)
    if not habit:
        return "Habit not found", 404

    if habit["type"] == "numeric" and value:
        models.upsert_numeric_log(DB, habit_id, today, float(value))
    elif status in models.VALID_STATUSES:
        models.upsert_log(DB, habit_id, today, status)

    return redirect(url_for("dashboard.today_view"))


# ---------------------------------------------------------------------------
# Annual heatmap
# ---------------------------------------------------------------------------

@dashboard_bp.get("/heatmap")
def heatmap_view():
    today = _today()
    start = today - timedelta(days=364)
    all_habits = models.get_all_active_habits(DB)

    # Build {date_str: fraction_completed} for the past 365 days
    heatmap_data = {}
    d = start
    while d <= today:
        applicable = models.get_habits_for_day(DB, d)
        if not applicable:
            d += timedelta(days=1)
            continue
        logs = {
            row["habit_id"]: row
            for row in models.get_logs_for_day(DB, d)
        }
        completed = sum(
            1 for h in applicable
            if logs.get(h["id"]) and logs[h["id"]]["status"] in ("completed", "partial")
        )
        heatmap_data[d.isoformat()] = round(completed / len(applicable), 3)
        d += timedelta(days=1)

    return render_template("heatmap.html", heatmap_data=json.dumps(heatmap_data), today=today.isoformat())


# ---------------------------------------------------------------------------
# Per-habit monthly calendar
# ---------------------------------------------------------------------------

@dashboard_bp.get("/calendar")
def calendar_view():
    all_habits = models.get_all_active_habits(DB)
    habit_id_param = request.args.get("habit_id")
    selected_habit = None
    calendar_data = {}

    if habit_id_param:
        try:
            habit_id = int(habit_id_param)
            selected_habit = models.get_habit_by_id(DB, habit_id)
        except (ValueError, TypeError):
            pass

    if not selected_habit and all_habits:
        selected_habit = all_habits[0]

    if selected_habit:
        today = _today()
        start = date(today.year - 1, today.month, 1)
        rows = models.get_logs_for_habit(DB, selected_habit["id"], start, today)
        for row in rows:
            calendar_data[row["date"]] = {
                "status": row["status"],
                "value": row["value"],
            }

    return render_template(
        "calendar.html",
        habits=all_habits,
        selected_habit=selected_habit,
        calendar_data=json.dumps(calendar_data),
        today=_today().isoformat(),
    )


# ---------------------------------------------------------------------------
# Habit manager
# ---------------------------------------------------------------------------

@dashboard_bp.get("/habits")
def habits_view():
    all_habits = models.get_all_active_habits(DB)
    return render_template("habits.html", habits=all_habits)


@dashboard_bp.post("/habits/add")
def add_habit_form():
    name = request.form["name"].strip()
    habit_type = request.form["type"]
    frequency = request.form["frequency"]
    frequency_days_raw = request.form.get("frequency_days", "")
    unit = request.form.get("unit") or None
    threshold_ok_raw = request.form.get("threshold_ok")
    threshold_good_raw = request.form.get("threshold_good")
    presets_raw = request.form.get("numeric_presets", "")

    frequency_days = None
    if frequency_days_raw.strip():
        frequency_days = [int(d.strip()) for d in frequency_days_raw.split(",") if d.strip()]

    threshold_ok = float(threshold_ok_raw) if threshold_ok_raw else None
    threshold_good = float(threshold_good_raw) if threshold_good_raw else None
    numeric_presets = (
        [float(p.strip()) for p in presets_raw.split(",") if p.strip()]
        if presets_raw.strip() else None
    )

    models.add_habit(
        DB,
        name=name,
        habit_type=habit_type,
        frequency=frequency,
        frequency_days=frequency_days,
        unit=unit,
        threshold_ok=threshold_ok,
        threshold_good=threshold_good,
        numeric_presets=numeric_presets,
    )
    return redirect(url_for("dashboard.habits_view"))


@dashboard_bp.post("/habits/<int:habit_id>/edit")
def edit_habit(habit_id: int):
    fields = {}
    for key in ("name", "threshold_ok", "threshold_good", "numeric_presets"):
        val = request.form.get(key)
        if val is not None and val != "":
            if key in ("threshold_ok", "threshold_good"):
                fields[key] = float(val)
            else:
                fields[key] = val
    frequency = request.form.get("frequency")
    if frequency:
        fields["frequency"] = frequency
        frequency_days_raw = request.form.get("frequency_days", "").strip()
        if frequency in ("weekly", "specific_days") and frequency_days_raw:
            fields["frequency_days"] = [int(d.strip()) for d in frequency_days_raw.split(",") if d.strip()]
        elif frequency == "daily":
            fields["frequency_days"] = None
    if fields:
        models.update_habit(DB, habit_id, **fields)
    return redirect(url_for("dashboard.habits_view"))


@dashboard_bp.post("/habits/<int:habit_id>/deactivate")
def deactivate_habit(habit_id: int):
    models.deactivate_habit(DB, habit_id)
    return redirect(url_for("dashboard.habits_view"))
