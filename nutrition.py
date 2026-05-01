"""
Nutrition parsing module.

Splits a meal description into items and fetches nutrition data from
API Ninjas. Designed for easy swap to a local LLM in the future —
callers only depend on the return dict shape from fetch_nutrition().
"""
import json
import urllib.request
import urllib.error
from typing import Optional

from loguru import logger


def parse_items(description: str) -> list[str]:
    """Split a comma-separated meal description into individual items."""
    return [item.strip() for item in description.split(",") if item.strip()]


def fetch_nutrition(items: list[str], api_key: Optional[str]) -> Optional[dict]:
    """Fetch nutrition data for a list of food items via API Ninjas.

    Returns {"calories": float, "protein_g": float, "carbs_g": float,
             "fat_g": float, "raw": list} on success, or None if no API
    key is configured or the API call fails entirely.
    """
    if not api_key or not items:
        return None

    totals = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
    raw_responses: list[dict] = []

    for item in items:
        try:
            url = f"https://api.api-ninjas.com/v1/nutrition?query={urllib.request.quote(item)}"
            req = urllib.request.Request(url, headers={"X-Api-Key": api_key})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            raw_responses.append({"query": item, "results": data})
            for entry in data:
                totals["calories"] += entry.get("calories", 0)
                totals["protein_g"] += entry.get("protein_g", 0)
                totals["carbs_g"] += entry.get("carbs_total_g", 0)
                totals["fat_g"] += entry.get("fat_total_g", 0)
        except Exception as exc:
            logger.warning("Nutrition API failed for '{}': {}", item, exc)
            raw_responses.append({"query": item, "error": str(exc)})

    if not any("results" in r for r in raw_responses):
        return None

    totals["calories"] = round(totals["calories"], 1)
    totals["protein_g"] = round(totals["protein_g"], 1)
    totals["carbs_g"] = round(totals["carbs_g"], 1)
    totals["fat_g"] = round(totals["fat_g"], 1)
    totals["raw"] = raw_responses
    return totals
