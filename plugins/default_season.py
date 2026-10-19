import re
import logging
from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from helper.database import codeflixbots as db

logger = logging.getLogger(__name__)

# user_id -> {'enable_after': bool}
# Users who tapped "Change Season" (or "On" with no season set) and whose next
# text message is the season number.
awaiting_season = {}

SEASON_RE = re.compile(r'^\d{1,2}$')


def is_valid_season(text):
    """1-2 digits, value 1-99. Leading zeros allowed (01, 02, 03)."""
    return bool(SEASON_RE.match(text)) and int(text) >= 1


async def build_panel(user_id):
    enabled, season = await db.get_default_season(user_id)
    enabled = enabled and bool(season)

    text = (
        "**🎬 Default Season**\n\n"
        f"**Status ▹** `{'On ✅' if enabled else 'Off'}`\n"
        f"**Season ▹** `{season if season else 'Not set'}`\n\n"
        "When On, every file is renamed with this season. It overrides the "
        "`[SO]` tag and any season found in the file name or caption, and the "
        "\"season not detected\" prompt is never shown."
    )
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"On{' ✅' if enabled else ''}", callback_data="ds_on"),
            InlineKeyboardButton(f"Off{'' if enabled else ' ✅'}", callback_data="ds_off"),
        ],
        [InlineKeyboardButton("Change Season", callback_data="ds_change")],
    ])
    return text, buttons


async def refresh_panel(query: CallbackQuery):
    text, buttons = await build_panel(query.from_user.id)
    try:
        await query.message.edit_text(text, reply_markup=buttons)
    except MessageNotModified:
        pass


async def ask_for_season(query: CallbackQuery, lead=""):
    prompt = (
        f"{lead}**Send the season number** (e.g. `1`, `01`, `2`).\n"
        "Whole number from 1 to 99. Leading zeros are kept as typed."
    )
    try:
        await query.message.edit_text(
            prompt,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Cancel", callback_data="ds_cancel")]]
            ),
        )
    except MessageNotModified:
        pass


@Client.on_message(filters.private & filters.command("defaultseason"))
async def default_season_cmd(client, message):
    user_id = message.from_user.id
    awaiting_season.pop(user_id, None)  # reset any half-finished season entry
    text, buttons = await build_panel(user_id)
    await message.reply_text(text, reply_markup=buttons, disable_web_page_preview=True)


@Client.on_callback_query(filters.regex(r"^ds_(on|off|change|cancel)$"))
async def default_season_cb(client, query: CallbackQuery):
    user_id = query.from_user.id
    action = query.data.split("_", 1)[1]

    if action == "off":
        awaiting_season.pop(user_id, None)
        await db.set_default_season_enabled(user_id, False)
        await query.answer("Default season is off")
        await refresh_panel(query)

    elif action == "on":
        _, season = await db.get_default_season(user_id)
        if not season:
            # Never turn it on with an empty season: collect one first.
            awaiting_season[user_id] = {"enable_after": True}
            await query.answer()
            await ask_for_season(query, lead="No season is set yet.\n\n")
        else:
            awaiting_season.pop(user_id, None)
            await db.set_default_season_enabled(user_id, True)
            await query.answer("Default season is on")
            await refresh_panel(query)

    elif action == "change":
        awaiting_season[user_id] = {"enable_after": False}
        await query.answer()
        await ask_for_season(query)

    elif action == "cancel":
        awaiting_season.pop(user_id, None)
        await query.answer("Cancelled")
        await refresh_panel(query)


async def _awaiting_season_filter(_, __, message):
    # Only match while the user is expected to send a season number, and never
    # swallow commands. For everyone else this returns False, so the regular
    # manual-input handler in file_rename.py still gets their messages.
    return bool(
        message.from_user
        and message.from_user.id in awaiting_season
        and message.text
        and not message.text.startswith("/")
    )


awaiting_season_filter = filters.create(_awaiting_season_filter)


@Client.on_message(filters.private & filters.text & awaiting_season_filter)
async def receive_season(client, message):
    user_id = message.from_user.id
    value = message.text.strip()

    if value.lower() == "cancel":
        awaiting_season.pop(user_id, None)
        text, buttons = await build_panel(user_id)
        return await message.reply_text(text, reply_markup=buttons)

    if not is_valid_season(value):
        return await message.reply_text(
            "❌ Invalid season. Send a whole number from 1 to 99 (e.g. `1` or `01`), "
            "or `cancel`."
        )

    state = awaiting_season.pop(user_id)
    await db.set_default_season(user_id, value)
    if state.get("enable_after"):
        await db.set_default_season_enabled(user_id, True)

    text, buttons = await build_panel(user_id)
    await message.reply_text(f"✅ Season set to `{value}`.\n\n{text}", reply_markup=buttons)
