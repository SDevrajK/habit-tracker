# PRD: Fitness Tracking Extension

## Introduction / Overview

Extend the existing Habit Tracker app with a dedicated fitness tracking module. The module covers body weight, seven circumference measurements, and derived body composition ratios. Data is logged via Telegram bot commands and visualised through a new private web dashboard section with emphasis on clear, high-quality trend charts that make progress visible at a glance.

Weightlifting statistics (exercise, sets, reps, load) are defined here as a lower-priority phase 2 feature and are scoped separately in §8.

---

## Goals

1. Allow quick logging of body weight and circumference measurements via Telegram without leaving the existing bot workflow.
2. Store all fitness data in the existing SQLite database (no new database process or file format).
3. Auto-compute derived metrics (WHtR, WHR) from raw measurements — no manual calculation required.
4. Provide a private web dashboard section (`/fitness/`) with polished, readable trend visualisations covering the full measurement history.
5. Protect both the habits dashboard and the new fitness pages behind HTTP Basic Auth so no data is publicly accessible.

---

## User Stories

- As Sayeed, I want to type `/weight 182.4` in Telegram and have my weight logged instantly, so I don't have to open a browser.
- As Sayeed, I want to use `/measurements` in Telegram and be guided through selecting a body part and entering a value, so logging a circumference is fast and hard to mis-enter.
- As Sayeed, I want to open `/fitness/weight` and see a clean line chart of my weight history, so I can see my trend at a glance.
- As Sayeed, I want to open `/fitness/measurements` and see all circumference trends on one page, so I can compare how different body parts are changing relative to each other.
- As Sayeed, I want WHtR and WHR auto-computed and shown alongside my raw measurements, so I don't need a calculator to interpret my data.
- As Sayeed, I want the dashboard to require a password, so my personal body data is not publicly visible.

---

## Functional Requirements

### §1 — Authentication

1.1 All routes under `/` (habits dashboard) and `/fitness/` must be protected by HTTP Basic Auth using a single username/password pair read from environment variables (`DASHBOARD_USER`, `DASHBOARD_PASS`).

1.2 Unauthenticated requests must return HTTP 401 with a `WWW-Authenticate` header so browsers prompt for credentials.

1.3 Credentials must never be hardcoded; the app must raise `EnvironmentError` on startup if either variable is absent (consistent with existing fail-fast pattern in `configs/config.py`).

### §2 — Database Schema

2.1 Add a `body_metrics` table to the existing SQLite database:

```sql
CREATE TABLE IF NOT EXISTS body_metrics (
    id         INTEGER  PRIMARY KEY AUTOINCREMENT,
    date       DATE     NOT NULL,
    metric     TEXT     NOT NULL,   -- see §2.3 for valid values
    value      REAL     NOT NULL,
    unit       TEXT     NOT NULL,   -- 'kg', 'lbs', 'cm', 'in'
    logged_at  DATETIME NOT NULL DEFAULT (datetime('now')),
    UNIQUE(date, metric)            -- one entry per metric per day; upsert on conflict
)
```

2.2 Add a `user_profile` table to store static reference data needed for derived metrics:

```sql
CREATE TABLE IF NOT EXISTS user_profile (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
)
-- keys: 'height_cm', 'preferred_weight_unit', 'preferred_length_unit'
```

2.3 Valid `metric` values for `body_metrics`:

| metric key | Description |
|---|---|
| `weight` | Body weight |
| `waist` | Waist circumference |
| `hip` | Hip circumference |
| `chest` | Chest circumference |
| `neck` | Neck circumference |
| `upper_arm_left` | Left upper arm circumference |
| `upper_arm_right` | Right upper arm circumference |
| `thigh_left` | Left thigh circumference |
| `thigh_right` | Right thigh circumference |

2.4 `init_db()` in `models.py` must create both new tables idempotently (no migration tooling required; `CREATE TABLE IF NOT EXISTS` is sufficient).

### §3 — Data Access Layer (`models.py`)

3.1 `upsert_body_metric(db, date, metric, value, unit)` — inserts or updates a single body metric entry using `ON CONFLICT(date, metric) DO UPDATE`.

3.2 `get_body_metrics(db, metric, start_date, end_date) → list[Row]` — returns all entries for a given metric in date order.

3.3 `get_latest_body_metrics(db) → dict[str, Row]` — returns the most recent entry for each metric.

3.4 `get_user_profile(db) → dict[str, str]` — returns all key/value pairs from `user_profile`.

3.5 `set_user_profile(db, key, value)` — upserts a single profile key.

3.6 Derived metrics are computed in the data layer (not templates):
- `compute_whtr(waist_cm, height_cm) → float` — `waist / height`
- `compute_whr(waist_cm, hip_cm) → float` — `waist / hip`

Both functions must validate that inputs are positive non-zero floats and raise `ValueError` otherwise.

### §4 — Telegram Bot Commands

4.1 `/weight [value]` — logs body weight immediately without a conversation.
- If `value` is provided inline (e.g. `/weight 182.4`), log it and confirm.
- If called with no argument, bot replies asking for the value (single follow-up message, not a full ConversationHandler).
- Unit defaults to `user_profile.preferred_weight_unit`; if not set, default to `lbs`.
- Reply confirms: `"Weight logged: 182.4 lbs ✓"`

4.2 `/measurements` — multi-step `ConversationHandler` to log a circumference.
- **State 1:** Bot sends inline keyboard with all nine measurement options (§2.3) plus a Cancel button.
- **State 2:** Bot asks for numeric value and unit (cm or in). Inline keyboard offers [cm] [in] quick-select for unit.
- **State 3:** Confirmation message; returns to idle.
- Cancellable at any step with /cancel.

4.3 `/fitness` — replies with a formatted summary of the most recent value for each metric, plus computed WHtR and WHR if waist, hip, and height are available. Example format:

```
📊 Latest Fitness Stats (2026-04-16)
Weight:     182.4 lbs
Waist:       34.0 cm  │ WHtR: 0.48
Hip:         38.5 cm  │ WHR:  0.88
Chest:       40.2 cm
Neck:        16.1 cm
Arm (L/R):  13.8 / 14.0 cm
Thigh (L/R): 22.1 / 22.4 cm
```

4.4 All new bot commands must pass through the existing `_authorised()` guard in `bot.py` — no new auth logic in handlers.

### §5 — Web Dashboard (`fitness.py` blueprint)

5.1 Register a new `Blueprint("fitness", url_prefix="/fitness")` in `fitness.py`. Mount it in `app.py` alongside the existing `dashboard_bp`.

5.2 **`GET /fitness/`** — Overview page.
- Most recent value for each metric in a summary card layout.
- One sparkline chart per metric (last 90 days) to give a quick visual of recent trend.
- WHtR and WHR displayed with a plain-language interpretation:
  - WHtR < 0.5 → "Healthy range"
  - WHtR 0.5–0.59 → "Elevated"
  - WHtR ≥ 0.6 → "High"

5.3 **`GET /fitness/weight`** — Weight trend page.
- Full-history line chart (all logged entries).
- Moving average overlay (7-day window).
- Y-axis scaled to actual data range (not forced to zero).
- Hoverable data points showing exact value and date.

5.4 **`GET /fitness/measurements`** — Circumference trends page.
- One line chart per measurement group:
  - Single-site measurements (waist, hip, chest, neck) on one combined chart with toggleable series.
  - Bilateral measurements (arms, thighs) shown as two lines per chart (left/right), or averaged if preferred — configurable via a toggle on the page.
- Computed ratios (WHtR, WHR) displayed as their own trend line below the main charts.
- Full history, hoverable data points.

5.5 Charts must use the same charting library already used in `static/charts.js` (currently used for the heatmap). If the existing library cannot produce line charts, select a lightweight JS charting library (e.g. Chart.js) and use it consistently across all new fitness pages.

5.6 All fitness pages must extend `base.html` and appear in the nav under a "Fitness" section.

### §6 — Navigation Updates

6.1 `base.html` nav must add a "Fitness" section with links to `/fitness/`, `/fitness/weight`, and `/fitness/measurements`.

6.2 The existing "Habits" nav section is unchanged.

### §7 — Measurement Protocol Reminder

7.1 The `/fitness/` overview page must display a collapsible reminder of the standard measurement protocol:
- Measure in the morning, after using the bathroom, before eating or drinking, before exercise.
- Use a non-stretchable tape; stand upright, weight equally distributed, arms at sides.
- Take each measurement twice; if they differ by more than 0.5 cm, take a third and average.
- Always use the same anatomical landmark each session.

This is display-only — no protocol enforcement in the app logic.

---

## Non-Goals (Out of Scope)

- **No caliper / skinfold measurements.** Circumference tape only.
- **No body fat percentage estimation** (e.g. U.S. Navy formula) in v1 — too prone to misinterpretation without calibration context.
- **No 3D or 2D body model visualisation.** Trend charts only.
- **No multi-user support.** Single-user, single credential pair.
- **No live chart updates.** Page refresh is sufficient for a personal tracker.
- **No data export** in v1 (CSV, PDF, etc.).
- **No weight unit conversion UI.** Unit is set once in `user_profile` and applied consistently.

---

## Phase 2 — Weightlifting Statistics (Lower Priority)

The following is scoped for a future implementation pass and should not block the above.

**P2.1 — Database:**
```sql
CREATE TABLE IF NOT EXISTS workouts (
    id        INTEGER  PRIMARY KEY AUTOINCREMENT,
    date      DATE     NOT NULL,
    exercise  TEXT     NOT NULL,
    sets_json TEXT     NOT NULL,  -- JSON array: [{"reps": 5, "weight_kg": 80}, ...]
    logged_at DATETIME NOT NULL DEFAULT (datetime('now'))
)
```

**P2.2 — Bot command:** `/lifts` — guided conversation to log an exercise session (exercise name → number of sets → reps and weight per set).

**P2.3 — Dashboard page:** `GET /fitness/lifts` — exercise history, personal records (PR) per exercise, and volume trend over time.

---

## Technical Considerations

- **Auth implementation:** Use a Flask `before_request` hook on both blueprints checking `flask.request.authorization`. The `functools.wraps`-based decorator pattern or a blueprint-level `before_request` are both acceptable; keep it under 20 lines.
- **Chart library:** Add line chart support directly to `static/charts.js` (do not add an external CDN dependency). The existing heatmap renderer lives there; line chart functions should follow the same patterns and be exported the same way.
- **Units:** Weight stored and displayed in **lbs**; all circumferences stored and displayed in **in** (inches). `user_profile` defaults: `preferred_weight_unit = lbs`, `preferred_length_unit = in`. Bot prompts and dashboard labels must reflect these units consistently.
- **Bilateral measurements:** Left and right are stored as separate metric rows (`upper_arm_left`, `upper_arm_right`, `thigh_left`, `thigh_right`) and displayed as **two separate lines** on the chart by default. No averaging toggle required.
- **`user_profile` height:** Required for WHtR. The overview page must gracefully handle missing height (display "Set height in profile to compute WHtR" rather than crashing).
- **Existing tests:** New `body_metrics` and `user_profile` table operations must be covered in `tests/test_models.py` using the existing temp-file SQLite pattern.

---

## Success Metrics

- `/weight 182.4` logs successfully in Telegram in under 3 seconds end-to-end.
- `/measurements` ConversationHandler completes a circumference log in ≤ 4 taps/messages.
- `/fitness/weight` renders a full-history line chart with moving average in under 2 seconds with 365 data points.
- `/fitness/measurements` renders all circumference trend charts correctly with no JavaScript console errors.
- All new model functions covered by tests; full test suite continues to pass (`pytest tests/`).
- Both dashboard and fitness pages return HTTP 401 when accessed without credentials.

---

## Open Questions

All questions resolved:

| # | Question | Decision |
|---|---|---|
| 1 | Weight and length units | **lbs** for weight, **in** for circumferences |
| 2 | Bilateral display | **Split lines** (left and right as separate series, no averaging) |
| 3 | Chart library | **Extend `static/charts.js`** with line chart support — no external CDN |
| 4 | Lifts nav link | **Add only when Phase 2 ships** — no placeholder link in Phase 1 |
