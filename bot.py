"""
Telegram bot command and callback handlers.

All handlers silently ignore messages from unauthorised chat IDs.
Callback data format:  "log:{habit_id}:{status}"
                       "log:{habit_id}:num:{value}"
                       "log:{habit_id}:custom"
"""
import json
import random
import re
from datetime import date, datetime
from typing import Optional

from loguru import logger
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from configs.config import Config
import models

DB = Config.DATABASE_URL
CHAT_ID = Config.TELEGRAM_CHAT_ID

# ConversationHandler states
(
    ADD_TYPE,
    ADD_FREQUENCY,
    ADD_FREQUENCY_DAYS,
    ADD_UNIT,
    ADD_THRESHOLD_OK,
    ADD_THRESHOLD_GOOD,
    ADD_PRESETS,
) = range(7)


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

def _authorised(update: Update) -> bool:
    return str(update.effective_chat.id) == str(CHAT_ID)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STATUS_EMOJI = {
    "completed": "✅",
    "partial": "🟡",
    "failed": "❌",
    "skipped": "⏭",
    "not_applicable": "—",
    None: "⬜",
}

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

_CONGRATS = [
    "Nice work! 💪",
    "Keep it up!",
    "Streak intact. 🔥",
    "Consistency is everything.",
    "Done. One more day building the habit.",
    "That's what I like to see. ✅",
    "Nailed it.",
    "Small wins add up. 📈",
    "You showed up today.",
    "Another one in the books.",
    "Habit locked in for today. 🔒",
    "Look at you go.",
    "One day at a time. ✨",
    "Future you is grateful.",
    "That's the way.",
]

_PARTIAL_CONGRATS = [
    "Partial counts. Better than nothing. 🟡",
    "Something is better than zero.",
    "Progress, not perfection.",
    "Good enough for today.",
    "A partial win is still a win.",
]


def _congrats(status: str) -> str:
    if status == "completed":
        return random.choice(_CONGRATS)
    if status == "partial":
        return random.choice(_PARTIAL_CONGRATS)
    return ""


def _fuzzy_find(name_query: str, habits: list) -> list:
    """Return habits whose name contains name_query (case-insensitive)."""
    q = name_query.strip().lower()
    return [h for h in habits if q in h["name"].lower()]


def _habit_status_line(habit, log_row) -> str:
    status = log_row["status"] if log_row else None
    emoji = STATUS_EMOJI.get(status, "⬜")
    value_str = ""
    if log_row and log_row["value"] is not None:
        value_str = f" ({log_row['value']}{' ' + habit['unit'] if habit['unit'] else ''})"
    return f"{emoji} {habit['name']}{value_str}"


def _build_log_keyboard(habit, today: date) -> InlineKeyboardMarkup:
    """Build inline keyboard for a single habit in the /log flow."""
    hid = habit["id"]
    htype = habit["type"]
    if htype in ("boolean", "inverse_boolean"):
        done_label = "✓ Done" if htype == "boolean" else "✓ No (good)"
        fail_label = "✗ Failed" if htype == "boolean" else "✗ Yes (bad)"
        buttons = [
            InlineKeyboardButton(done_label, callback_data=f"log:{hid}:completed"),
            InlineKeyboardButton(fail_label, callback_data=f"log:{hid}:failed"),
            InlineKeyboardButton("⏭ Skip", callback_data=f"log:{hid}:skipped"),
        ]
        return InlineKeyboardMarkup([buttons])
    else:  # numeric
        presets = json.loads(habit["numeric_presets"] or "[]")
        preset_buttons = [
            InlineKeyboardButton(str(p), callback_data=f"log:{hid}:num:{p}")
            for p in presets
        ]
        custom_button = InlineKeyboardButton("✏️ Custom", callback_data=f"log:{hid}:custom")
        rows = [preset_buttons[i:i+4] for i in range(0, len(preset_buttons), 4)]
        rows.append([custom_button])
        return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# /status
# ---------------------------------------------------------------------------

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorised(update):
        return
    today = date.today()
    habits = models.get_habits_for_day(DB, today)
    if not habits:
        await update.message.reply_text("No habits applicable today.")
        return
    lines = [f"📋 Today ({today.strftime('%A, %b %d')}):"]
    for h in habits:
        log_row = models.get_log(DB, h["id"], today)
        lines.append(_habit_status_line(h, log_row))
    await update.message.reply_text("\n".join(lines))


# ---------------------------------------------------------------------------
# /habits
# ---------------------------------------------------------------------------

async def habits_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorised(update):
        return
    habits = models.get_all_active_habits(DB)
    if not habits:
        await update.message.reply_text("No active habits.")
        return
    lines = ["🏃 Active habits:"]
    for h in habits:
        freq = h["frequency"]
        if freq == "specific_days":
            days = ", ".join(WEEKDAY_NAMES[d] for d in json.loads(h["frequency_days"] or "[]"))
            freq_str = f"specific days ({days})"
        elif freq == "weekly":
            days = ", ".join(WEEKDAY_NAMES[d] for d in json.loads(h["frequency_days"] or "[]"))
            freq_str = f"weekly ({days})"
        else:
            freq_str = "daily"
        threshold_str = ""
        if h["type"] == "numeric":
            threshold_str = f" | ok≥{h['threshold_ok']}{h['unit'] or ''} good≥{h['threshold_good']}{h['unit'] or ''}"
        lines.append(f"• {h['name']} [{h['type']}] {freq_str}{threshold_str}")
    await update.message.reply_text("\n".join(lines))


# ---------------------------------------------------------------------------
# /log
# ---------------------------------------------------------------------------

async def log_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorised(update):
        return
    today = date.today()
    habits = models.get_habits_for_day(DB, today)
    if not habits:
        await update.message.reply_text("No habits applicable today.")
        return
    for h in habits:
        log_row = models.get_log(DB, h["id"], today)
        current = _habit_status_line(h, log_row)
        phrasing = h["name"]
        if h["type"] == "inverse_boolean":
            phrasing += " (Yes = bad)"
        keyboard = _build_log_keyboard(h, today)
        await update.message.reply_text(
            f"{current}\nLog: {phrasing}", reply_markup=keyboard
        )


async def log_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button taps from /log."""
    if not _authorised(update):
        return
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    # parts: ["log", habit_id, status] or ["log", habit_id, "num", value] or ["log", habit_id, "custom"]
    if len(parts) < 3:
        return
    habit_id = int(parts[1])
    today = date.today()

    if parts[2] == "custom":
        # Store which habit is waiting for a custom numeric value
        context.user_data["awaiting_custom_habit"] = habit_id
        await query.edit_message_text(
            f"Enter a number for {_get_habit_name(habit_id)}:", reply_markup=None
        )
        return

    if parts[2] == "num":
        value = float(parts[3])
        status = models.upsert_numeric_log(DB, habit_id, today, value)
    else:
        status = parts[2]
        models.upsert_log(DB, habit_id, today, status)

    habit = models.get_habit_by_id(DB, habit_id)
    log_row = models.get_log(DB, habit_id, today)
    updated_line = _habit_status_line(habit, log_row)
    congrats = _congrats(status)
    if congrats:
        updated_line += f"\n{congrats}"
    await query.edit_message_text(updated_line, reply_markup=None)


async def custom_numeric_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Receive free-text number after 'custom' button tap."""
    if not _authorised(update):
        return
    habit_id = context.user_data.get("awaiting_custom_habit")
    if habit_id is None:
        return
    text = update.message.text.strip()
    try:
        value = float(text)
    except ValueError:
        await update.message.reply_text(
            f"That doesn't look like a number. Please send a numeric value."
        )
        return
    today = date.today()
    status = models.upsert_numeric_log(DB, habit_id, today, value)
    habit = models.get_habit_by_id(DB, habit_id)
    context.user_data.pop("awaiting_custom_habit", None)
    log_row = models.get_log(DB, habit_id, today)
    msg = f"Logged: {_habit_status_line(habit, log_row)}"
    congrats = _congrats(status)
    if congrats:
        msg += f"\n{congrats}"
    await update.message.reply_text(msg)


def _get_habit_name(habit_id: int) -> str:
    h = models.get_habit_by_id(DB, habit_id)
    return h["name"] if h else str(habit_id)


# ---------------------------------------------------------------------------
# /done, /fail, /skip
# ---------------------------------------------------------------------------

async def _log_by_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE, status: str
) -> None:
    if not _authorised(update):
        return
    args = context.args
    if not args:
        await update.message.reply_text(f"Usage: /{status.split('_')[0]} <habit name>")
        return
    query = " ".join(args)
    today = date.today()
    habits = models.get_habits_for_day(DB, today)
    matches = _fuzzy_find(query, habits)
    if not matches:
        await update.message.reply_text(f"No active habit today matches '{query}'.")
        return
    if len(matches) > 1:
        names = "\n".join(f"• {h['name']}" for h in matches)
        await update.message.reply_text(f"Ambiguous — did you mean:\n{names}")
        return
    habit = matches[0]
    models.upsert_log(DB, habit["id"], today, status)
    log_row = models.get_log(DB, habit["id"], today)
    msg = _habit_status_line(habit, log_row)
    congrats = _congrats(status)
    if congrats:
        msg += f"\n{congrats}"
    await update.message.reply_text(msg)


async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _log_by_name(update, context, "completed")


async def fail_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _log_by_name(update, context, "failed")


async def skip_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _log_by_name(update, context, "skipped")


# ---------------------------------------------------------------------------
# /remove and /setreminder
# ---------------------------------------------------------------------------

async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorised(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /remove <habit name>")
        return
    query = " ".join(context.args)
    habits = models.get_all_active_habits(DB)
    matches = _fuzzy_find(query, habits)
    if not matches:
        await update.message.reply_text(f"No active habit matches '{query}'.")
        return
    if len(matches) > 1:
        names = "\n".join(f"• {h['name']}" for h in matches)
        await update.message.reply_text(f"Ambiguous — did you mean:\n{names}")
        return
    habit = matches[0]
    models.deactivate_habit(DB, habit["id"])
    await update.message.reply_text(f"✅ '{habit['name']}' has been deactivated.")


async def setreminder_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorised(update):
        return
    if not context.args or not re.match(r"^\d{2}:\d{2}$", context.args[0]):
        await update.message.reply_text("Usage: /setreminder HH:MM  (e.g. /setreminder 21:00)")
        return
    new_time = context.args[0]
    models.set_config(DB, "global_reminder_time", new_time)
    await update.message.reply_text(f"✅ Daily reminder updated to {new_time}.")


# ---------------------------------------------------------------------------
# /add conversation
# ---------------------------------------------------------------------------

async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _authorised(update):
        return ConversationHandler.END
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /add <habit name>")
        return ConversationHandler.END
    context.user_data["new_habit"] = {"name": " ".join(args)}
    await update.message.reply_text(
        "What type is this habit?\n"
        "  1 — boolean (yes/no)\n"
        "  2 — inverse_boolean (no = success)\n"
        "  3 — numeric (log a number)"
    )
    return ADD_TYPE


async def add_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    types = {"1": "boolean", "2": "inverse_boolean", "3": "numeric"}
    choice = update.message.text.strip()
    if choice not in types:
        await update.message.reply_text("Please reply 1, 2, or 3.")
        return ADD_TYPE
    context.user_data["new_habit"]["type"] = types[choice]
    await update.message.reply_text(
        "Frequency?\n"
        "  1 — daily\n"
        "  2 — weekly (specific day)\n"
        "  3 — specific days (e.g. Mon/Wed/Thu)"
    )
    return ADD_FREQUENCY


async def add_frequency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    freqs = {"1": "daily", "2": "weekly", "3": "specific_days"}
    choice = update.message.text.strip()
    if choice not in freqs:
        await update.message.reply_text("Please reply 1, 2, or 3.")
        return ADD_FREQUENCY
    context.user_data["new_habit"]["frequency"] = freqs[choice]
    if freqs[choice] == "daily":
        context.user_data["new_habit"]["frequency_days"] = None
        return await _ask_unit_or_finish(update, context)
    await update.message.reply_text(
        "Which days? Enter weekday numbers separated by commas.\n"
        "  0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun\n"
        "  Example: 0,2,3"
    )
    return ADD_FREQUENCY_DAYS


async def add_frequency_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        days = [int(d.strip()) for d in update.message.text.split(",")]
        if not all(0 <= d <= 6 for d in days):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Please enter valid weekday numbers (0–6) separated by commas.")
        return ADD_FREQUENCY_DAYS
    context.user_data["new_habit"]["frequency_days"] = days
    return await _ask_unit_or_finish(update, context)


async def _ask_unit_or_finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if context.user_data["new_habit"]["type"] == "numeric":
        await update.message.reply_text("What is the unit? (e.g. min, apps, km)")
        return ADD_UNIT
    return await _save_habit(update, context)


async def add_unit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_habit"]["unit"] = update.message.text.strip()
    await update.message.reply_text("Enter threshold_ok (minimum for partial/amber completion):")
    return ADD_THRESHOLD_OK


async def add_threshold_ok(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        val = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Please enter a number.")
        return ADD_THRESHOLD_OK
    context.user_data["new_habit"]["threshold_ok"] = val
    await update.message.reply_text("Enter threshold_good (minimum for full/green completion):")
    return ADD_THRESHOLD_GOOD


async def add_threshold_good(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        val = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Please enter a number.")
        return ADD_THRESHOLD_GOOD
    context.user_data["new_habit"]["threshold_good"] = val
    await update.message.reply_text(
        "Enter quick-select preset values separated by commas (e.g. 0,15,30,60):"
    )
    return ADD_PRESETS


async def add_presets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        presets = [float(p.strip()) for p in update.message.text.split(",")]
    except ValueError:
        await update.message.reply_text("Please enter numbers separated by commas.")
        return ADD_PRESETS
    context.user_data["new_habit"]["numeric_presets"] = presets
    return await _save_habit(update, context)


async def _save_habit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    nh = context.user_data.pop("new_habit")
    habit_id = models.add_habit(
        DB,
        name=nh["name"],
        habit_type=nh["type"],
        frequency=nh["frequency"],
        frequency_days=nh.get("frequency_days"),
        unit=nh.get("unit"),
        threshold_ok=nh.get("threshold_ok"),
        threshold_good=nh.get("threshold_good"),
        numeric_presets=nh.get("numeric_presets"),
    )
    await update.message.reply_text(
        f"✅ Habit '{nh['name']}' added (id={habit_id})."
    )
    return ConversationHandler.END


async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("new_habit", None)
    await update.message.reply_text("Habit creation cancelled.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# End-of-day auto-fail (called from scheduler)
# ---------------------------------------------------------------------------

async def auto_fail_unlogged(bot_app: "Application") -> None:
    """Mark all unlogged applicable habits as failed. Called at 23:59 daily."""
    today = date.today()
    habits = models.get_habits_for_day(Config.DATABASE_URL, today)
    count = 0
    for h in habits:
        log_row = models.get_log(Config.DATABASE_URL, h["id"], today)
        if log_row is None:
            models.upsert_log(Config.DATABASE_URL, h["id"], today, "failed")
            count += 1
    logger.info("Auto-fail: marked {} habits as failed for {}", count, today)


# ---------------------------------------------------------------------------
# Application builder
# ---------------------------------------------------------------------------

def build_application(token: str) -> Application:
    application = Application.builder().token(token).build()

    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            ADD_TYPE:           [MessageHandler(filters.TEXT & ~filters.COMMAND, add_type)],
            ADD_FREQUENCY:      [MessageHandler(filters.TEXT & ~filters.COMMAND, add_frequency)],
            ADD_FREQUENCY_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_frequency_days)],
            ADD_UNIT:           [MessageHandler(filters.TEXT & ~filters.COMMAND, add_unit)],
            ADD_THRESHOLD_OK:   [MessageHandler(filters.TEXT & ~filters.COMMAND, add_threshold_ok)],
            ADD_THRESHOLD_GOOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_threshold_good)],
            ADD_PRESETS:        [MessageHandler(filters.TEXT & ~filters.COMMAND, add_presets)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    )

    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("habits", habits_command))
    application.add_handler(CommandHandler("log", log_command))
    application.add_handler(CommandHandler("done", done_command))
    application.add_handler(CommandHandler("fail", fail_command))
    application.add_handler(CommandHandler("skip", skip_command))
    application.add_handler(CommandHandler("remove", remove_command))
    application.add_handler(CommandHandler("setreminder", setreminder_command))
    application.add_handler(add_conv)
    application.add_handler(CallbackQueryHandler(log_callback, pattern=r"^log:"))
    # Custom numeric input: only fires when bot is awaiting a value
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            custom_numeric_input,
        )
    )

    return application
