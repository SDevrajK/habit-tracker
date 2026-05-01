"""
Flask blueprint for the meals dashboard.
Routes: /meals/
"""
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, render_template, request

import models
from auth import require_dashboard_auth
from configs.config import Config

DB = Config.DATABASE_URL

meals_bp = Blueprint("meals", __name__, url_prefix="/meals")


def _today() -> date:
    return datetime.now(ZoneInfo(Config.TIMEZONE)).date()


@meals_bp.before_request
def require_auth():
    return require_dashboard_auth()


@meals_bp.get("/")
def meals_view():
    date_str = request.args.get("date")
    if date_str:
        try:
            view_date = date.fromisoformat(date_str)
        except ValueError:
            view_date = _today()
    else:
        view_date = _today()

    meals = models.get_meals_for_day(DB, view_date)
    totals = models.get_meal_totals_for_day(DB, view_date)

    # Parse items JSON for display
    meal_list = []
    for m in meals:
        meal_list.append({
            "id": m["id"],
            "time": m["time"],
            "description": m["description"],
            "items": json.loads(m["items"]) if m["items"] else [],
            "calories": m["calories"],
            "protein_g": m["protein_g"],
            "carbs_g": m["carbs_g"],
            "fat_g": m["fat_g"],
        })

    prev_date = (view_date - timedelta(days=1)).isoformat()
    next_date = (view_date + timedelta(days=1)).isoformat()
    is_today = view_date == _today()

    return render_template(
        "meals.html",
        meals=meal_list,
        totals=totals,
        view_date=view_date,
        prev_date=prev_date,
        next_date=next_date,
        is_today=is_today,
    )
