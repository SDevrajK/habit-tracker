"""
Tests for meal logging: models CRUD, nutrition parsing, and bot command.
"""
import json
from datetime import date
from unittest.mock import patch, MagicMock

import pytest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from models import (
    init_db,
    add_meal,
    get_meals_for_day,
    get_meal_totals_for_day,
    count_meals_for_day,
    ensure_meal_habit,
    get_all_active_habits,
)
from nutrition import parse_items, fetch_nutrition


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    return db_path


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestAddMeal:
    def test_add_and_retrieve(self, db):
        meal_id = add_meal(db, date(2026, 4, 30), "12:30", "chicken, rice",
                           json.dumps(["chicken", "rice"]), 500.0, 40.0, 50.0, 10.0)
        assert meal_id > 0
        meals = get_meals_for_day(db, date(2026, 4, 30))
        assert len(meals) == 1
        assert meals[0]["description"] == "chicken, rice"
        assert meals[0]["calories"] == 500.0

    def test_multiple_meals_same_day(self, db):
        add_meal(db, date(2026, 4, 30), "08:00", "oatmeal")
        add_meal(db, date(2026, 4, 30), "12:00", "sandwich")
        add_meal(db, date(2026, 4, 30), "18:00", "pasta")
        meals = get_meals_for_day(db, date(2026, 4, 30))
        assert len(meals) == 3
        assert meals[0]["time"] == "08:00"
        assert meals[2]["time"] == "18:00"

    def test_no_meals_returns_empty(self, db):
        meals = get_meals_for_day(db, date(2026, 1, 1))
        assert meals == []

    def test_null_nutrition(self, db):
        add_meal(db, date(2026, 4, 30), "12:00", "mystery food")
        meals = get_meals_for_day(db, date(2026, 4, 30))
        assert meals[0]["calories"] is None
        assert meals[0]["protein_g"] is None


class TestMealTotals:
    def test_totals_with_nutrition(self, db):
        add_meal(db, date(2026, 4, 30), "08:00", "eggs", None, 200.0, 15.0, 2.0, 14.0)
        add_meal(db, date(2026, 4, 30), "12:00", "salad", None, 300.0, 10.0, 30.0, 8.0)
        totals = get_meal_totals_for_day(db, date(2026, 4, 30))
        assert totals["count"] == 2
        assert totals["calories"] == 500.0
        assert totals["protein_g"] == 25.0
        assert totals["carbs_g"] == 32.0
        assert totals["fat_g"] == 22.0

    def test_totals_null_nutrition(self, db):
        add_meal(db, date(2026, 4, 30), "12:00", "food")
        totals = get_meal_totals_for_day(db, date(2026, 4, 30))
        assert totals["count"] == 1
        assert totals["calories"] is None

    def test_totals_empty_day(self, db):
        totals = get_meal_totals_for_day(db, date(2026, 1, 1))
        assert totals["count"] == 0


class TestCountMeals:
    def test_count(self, db):
        assert count_meals_for_day(db, date(2026, 4, 30)) == 0
        add_meal(db, date(2026, 4, 30), "08:00", "breakfast")
        assert count_meals_for_day(db, date(2026, 4, 30)) == 1
        add_meal(db, date(2026, 4, 30), "12:00", "lunch")
        assert count_meals_for_day(db, date(2026, 4, 30)) == 2


class TestEnsureMealHabit:
    def test_creates_habit(self, db):
        ensure_meal_habit(db)
        habits = get_all_active_habits(db)
        meal_habits = [h for h in habits if h["name"] == "Log meals"]
        assert len(meal_habits) == 1
        h = meal_habits[0]
        assert h["type"] == "numeric"
        assert h["threshold_ok"] == 2.0
        assert h["threshold_good"] == 3.0

    def test_idempotent(self, db):
        ensure_meal_habit(db)
        ensure_meal_habit(db)
        habits = get_all_active_habits(db)
        meal_habits = [h for h in habits if h["name"] == "Log meals"]
        assert len(meal_habits) == 1


# ---------------------------------------------------------------------------
# Nutrition parsing tests
# ---------------------------------------------------------------------------

class TestParseItems:
    def test_basic(self):
        assert parse_items("chicken, rice, broccoli") == ["chicken", "rice", "broccoli"]

    def test_single_item(self):
        assert parse_items("oatmeal") == ["oatmeal"]

    def test_strips_whitespace(self):
        assert parse_items("  eggs ,  toast , butter  ") == ["eggs", "toast", "butter"]

    def test_filters_empty(self):
        assert parse_items("eggs,,toast,") == ["eggs", "toast"]

    def test_empty_string(self):
        assert parse_items("") == []


class TestFetchNutrition:
    def test_no_key_returns_none(self):
        assert fetch_nutrition(["chicken"], None) is None

    def test_empty_key_returns_none(self):
        assert fetch_nutrition(["chicken"], "") is None

    def test_empty_items_returns_none(self):
        assert fetch_nutrition([], "some-key") is None

    def test_success(self):
        mock_response = json.dumps([
            {"calories": 200, "protein_g": 30, "carbs_total_g": 0, "fat_total_g": 8}
        ]).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("nutrition.urllib.request.urlopen", return_value=mock_resp):
            result = fetch_nutrition(["chicken breast"], "test-key")

        assert result is not None
        assert result["calories"] == 200.0
        assert result["protein_g"] == 30.0
        assert result["carbs_g"] == 0.0
        assert result["fat_g"] == 8.0
        assert len(result["raw"]) == 1

    def test_api_failure_returns_none(self):
        with patch("nutrition.urllib.request.urlopen", side_effect=Exception("timeout")):
            result = fetch_nutrition(["chicken"], "test-key")
        assert result is None

    def test_partial_failure_still_returns(self):
        """If one item fails but another succeeds, return partial results."""
        call_count = 0

        def mock_urlopen(req, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("failed")
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps([
                {"calories": 100, "protein_g": 5, "carbs_total_g": 20, "fat_total_g": 2}
            ]).encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("nutrition.urllib.request.urlopen", side_effect=mock_urlopen):
            result = fetch_nutrition(["bad item", "rice"], "test-key")

        assert result is not None
        assert result["calories"] == 100.0
