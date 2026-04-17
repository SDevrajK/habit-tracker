"""
Flask blueprint for the fitness tracking dashboard.
Routes: /fitness/, /fitness/weight, /fitness/measurements, /fitness/profile
"""
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, redirect, render_template, request, url_for
from loguru import logger

import models
from auth import require_dashboard_auth
from configs.config import Config

DB = Config.DATABASE_URL

fitness_bp = Blueprint("fitness", __name__, url_prefix="/fitness")


def _today() -> date:
    return datetime.now(ZoneInfo(Config.TIMEZONE)).date()


@fitness_bp.before_request
def require_auth():
    return require_dashboard_auth()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_METRIC_LABELS = {
    "weight": "Weight",
    "waist": "Waist",
    "hip": "Hip",
    "chest": "Chest",
    "neck": "Neck",
    "upper_arm_left": "Arm (L)",
    "upper_arm_right": "Arm (R)",
    "thigh_left": "Thigh (L)",
    "thigh_right": "Thigh (R)",
}

_INCHES_TO_CM = 2.54


def _to_cm(value: float, unit: str) -> float:
    """Convert a measurement value to centimeters."""
    if unit == "in":
        return value * _INCHES_TO_CM
    return value


def _whtr_interpretation(ratio: float) -> str:
    if ratio < 0.5:
        return "Healthy range"
    if ratio < 0.6:
        return "Elevated"
    return "High"


def _sparkline_data(db_path: str, metric: str, days: int = 90) -> list[dict]:
    """Return recent metric data formatted for the JS sparkline renderer."""
    today = _today()
    start = today - timedelta(days=days)
    rows = models.get_body_metrics(db_path, metric, start, today)
    return [{"date": row["date"], "value": row["value"]} for row in rows]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@fitness_bp.get("/")
def overview():
    profile = models.get_user_profile(DB)
    latest = models.get_latest_body_metrics(DB)
    height_cm = float(profile["height_cm"]) if "height_cm" in profile else None

    # Build metric cards with sparkline data
    metric_cards = []
    for metric_key in models.VALID_METRICS:
        row = latest.get(metric_key)
        card = {
            "key": metric_key,
            "label": _METRIC_LABELS.get(metric_key, metric_key),
            "value": row["value"] if row else None,
            "unit": row["unit"] if row else None,
            "date": row["date"] if row else None,
            "sparkline": _sparkline_data(DB, metric_key),
        }
        metric_cards.append(card)

    # Compute ratios
    whtr = None
    whtr_text = None
    whr = None
    whr_text = None

    waist_row = latest.get("waist")
    hip_row = latest.get("hip")

    if waist_row and height_cm:
        waist_cm = _to_cm(waist_row["value"], waist_row["unit"])
        try:
            whtr = models.compute_whtr(waist_cm, height_cm)
            whtr_text = _whtr_interpretation(whtr)
        except ValueError:
            pass

    if waist_row and hip_row:
        waist_cm = _to_cm(waist_row["value"], waist_row["unit"])
        hip_cm = _to_cm(hip_row["value"], hip_row["unit"])
        try:
            whr = models.compute_whr(waist_cm, hip_cm)
            whr_text = "Normal" if whr < 0.9 else "Elevated"
        except ValueError:
            pass

    return render_template(
        "fitness_overview.html",
        metric_cards=metric_cards,
        whtr=whtr,
        whtr_text=whtr_text,
        whr=whr,
        whr_text=whr_text,
        height_cm=height_cm,
        profile=profile,
    )


@fitness_bp.get("/weight")
def weight():
    today = _today()
    start = date(2020, 1, 1)  # all history
    rows = models.get_body_metrics(DB, "weight", start, today)
    profile = models.get_user_profile(DB)
    unit = profile.get("preferred_weight_unit", "lbs")

    data = [{"date": r["date"], "value": r["value"]} for r in rows]

    stats = {}
    if data:
        values = [d["value"] for d in data]
        stats["current"] = values[-1]
        stats["min"] = min(values)
        stats["max"] = max(values)
        stats["change"] = round(values[-1] - values[0], 1)

    return render_template(
        "fitness_weight.html",
        data_json=json.dumps(data),
        unit=unit,
        stats=stats,
    )


@fitness_bp.get("/measurements")
def measurements():
    today = _today()
    start = date(2020, 1, 1)
    profile = models.get_user_profile(DB)
    unit = profile.get("preferred_length_unit", "in")
    height_cm = float(profile["height_cm"]) if "height_cm" in profile else None

    def _series(metric: str, label: str, color: str) -> dict:
        rows = models.get_body_metrics(DB, metric, start, today)
        return {
            "label": label,
            "color": color,
            "data": [{"date": r["date"], "value": r["value"]} for r in rows],
            "unit": unit,
        }

    # Single-site measurements
    single_site = [
        _series("waist", "Waist", "#e74c3c"),
        _series("hip", "Hip", "#3498db"),
        _series("chest", "Chest", "#2ecc71"),
        _series("neck", "Neck", "#9b59b6"),
    ]

    # Arms
    arms = [
        _series("upper_arm_left", "Left Arm", "#3498db"),
        _series("upper_arm_right", "Right Arm", "#e67e22"),
    ]

    # Thighs
    thighs = [
        _series("thigh_left", "Left Thigh", "#3498db"),
        _series("thigh_right", "Right Thigh", "#e67e22"),
    ]

    # Compute ratio trends
    whtr_data = []
    whr_data = []
    waist_rows = models.get_body_metrics(DB, "waist", start, today)
    hip_rows = models.get_body_metrics(DB, "hip", start, today)

    hip_by_date = {r["date"]: r for r in hip_rows}

    for wr in waist_rows:
        waist_cm = _to_cm(wr["value"], wr["unit"])
        if height_cm:
            try:
                whtr_data.append({"date": wr["date"], "value": round(models.compute_whtr(waist_cm, height_cm), 3)})
            except ValueError:
                pass
        hip_r = hip_by_date.get(wr["date"])
        if hip_r:
            hip_cm = _to_cm(hip_r["value"], hip_r["unit"])
            try:
                whr_data.append({"date": wr["date"], "value": round(models.compute_whr(waist_cm, hip_cm), 3)})
            except ValueError:
                pass

    ratios = [
        {"label": "WHtR", "color": "#e74c3c", "data": whtr_data, "unit": ""},
        {"label": "WHR", "color": "#3498db", "data": whr_data, "unit": ""},
    ]

    return render_template(
        "fitness_measurements.html",
        single_site_json=json.dumps(single_site),
        arms_json=json.dumps(arms),
        thighs_json=json.dumps(thighs),
        ratios_json=json.dumps(ratios),
        unit=unit,
    )


@fitness_bp.post("/profile")
def save_profile():
    height_cm = request.form.get("height_cm")
    if height_cm:
        try:
            val = float(height_cm)
            if val > 0:
                models.set_user_profile(DB, "height_cm", str(val))
        except ValueError:
            pass
    return redirect(url_for("fitness.overview"))
