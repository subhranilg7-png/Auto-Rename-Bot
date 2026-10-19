"""
/sequence — number episodes by Telegram message-id order.

While it is ON, forwarded files are only collected (see collect_for_sequence in
file_rename.py). When the user sends `work` (or `/work`, or `work 5` to start at 5),
the collected files are sorted by message id, numbered from the stored "next episode"
counter, and put into the normal persistent rename queue.

Plugin file name starts with "e" on purpose: Pyrogram loads plugins alphabetically and
the first matching handler in a group wins, so this has to load before file_rename.py
(whose catch-all text handler would otherwise swallow `work` and the number replies).
"""
import re
import logging
from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

from helper.database import codeflixbots as db
from plugins.file_rename import add_to_queue, resolve_messages

logger = logging.getLogger(__name__)

# user_id -> True while the next text message is the new episode number
awaiting_number = {}
# user_id -> {'field', 'files', 'start', 'season', 'quality'}   (batch-wide season/quality questions)
asking = {}
# users whose "work" is currently being processed
busy = set()

NUMBER_RE = re.compile(r'^\d{1,4}$')            # episodes up to 9999 (100+ is fine)
SEASON_RE = re.compile(r'^\d{1,2}$')
WORK_RE = re.compile(r'^\s*work(?:\s+(\d{1,4}))?\s*$', re.IGNORECASE)


def fmt_episode(n):
    """Minimum two digits, grows naturally: 5 -> 05, 12 -> 12, 120 -> 120."""
    return f"{int(n):02d}"


def valid_number(text):
    return bool(NUMBER_RE.match(text)) and int(text) >= 1


# ── Panel ──────────────────────────────────────────────────────────────────────

async def build_panel(user_id):
    enabled, next_ep = await db.get_sequence(user_id)
    collected = await db.count_sequence_files(user_id)
    text = (
        "**🎞 Episode Sequence**\n\n"
        f"**Status ▹** `{'On ✅' if enabled else 'Off'}`\n"
        f"**Next episode ▹** `{fmt_episode(next_ep)}`\n"
        f"**Files collected ▹** `{collected}`\n\n"
        "When On, forwarded files are held. Send `work` and they are renamed in "
        "message order, numbering episodes from the next episode above (it overrides "
        "any episode found in the file name, and the \"episode not detected\" message "
        "never shows). `work 5` starts from episode 5. `/clear` discards collected files."
    )
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"On{' ✅' if enabled else ''}", callback_data="sq_on"),
            InlineKeyboardButton(f"Off{'' if enabled else ' ✅'}", callback_data="sq_off"),
        ],
        [
            InlineKeyboardButton("Reset Number", callback_data="sq_reset"),
            InlineKeyboardButton("Add Number", callback_data="sq_add"),
        ],
    ])
    return text, buttons


async def refresh_panel(query: CallbackQuery):
    text, buttons = await build_panel(query.from_user.id)
    try:
        await query.message.edit_text(text, reply_markup=buttons)
    except MessageNotModified:
        pass


@Client.on_message(filters.private & filters.command("sequence"))
async def sequence_cmd(client, message):
    user_id = message.from_user.id
    awaiting_number.pop(user_id, None)
    asking.pop(user_id, None)
    text, buttons = await build_panel(user_id)
    await message.reply_text(text, reply_markup=buttons)


@Client.on_callback_query(filters.regex(r"^sq_(on|off|reset|add|cancel)$"))
async def sequence_cb(client, query: CallbackQuery):
    user_id = query.from_user.id
    action = query.data.split("_", 1)[1]

    if action == "on":
        awaiting_number.pop(user_id, None)
        await db.set_sequence_enabled(user_id, True)
        await query.answer("Sequence is on")
        await refresh_panel(query)

    elif action == "off":
        awaiting_number.pop(user_id, None)
        await db.set_sequence_enabled(user_id, False)
        await query.answer("Sequence is off")
        await refresh_panel(query)

    elif action == "reset":
        awaiting_number.pop(user_id, None)
        await db.set_sequence_next(user_id, 1)
        await query.answer("Next episode reset to 01")
        await refresh_panel(query)

    elif action == "add":
        awaiting_number[user_id] = True
        await query.answer()
        try:
            await query.message.edit_text(
                "**Send the episode number to start from** (e.g. `5`, `12`, `120`).\n"
                "Whole number from 1 to 9999.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Cancel", callback_data="sq_cancel")]]
                ),
            )
        except MessageNotModified:
            pass

    elif action == "cancel":
        awaiting_number.pop(user_id, None)
        await query.answer("Cancelled")
        await refresh_panel(query)


async def _awaiting_number_filter(_, __, message):
    return bool(
        message.from_user
        and message.from_user.id in awaiting_number
        and message.text
        and not message.text.startswith("/")
    )


@Client.on_message(filters.private & filters.text & filters.create(_awaiting_number_filter))
async def receive_number(client, message):
    user_id = message.from_user.id
    value = message.text.strip()

    if value.lower() == "cancel":
        awaiting_number.pop(user_id, None)
        text, buttons = await build_panel(user_id)
        return await message.reply_text(text, reply_markup=buttons)

    if not valid_number(value):
        return await message.reply_text(
            "❌ Invalid number. Send a whole number from 1 to 9999 (e.g. `5` or `120`), or `cancel`."
        )

    awaiting_number.pop(user_id, None)
    await db.set_sequence_next(user_id, int(value))
    text, buttons = await build_panel(user_id)
    await message.reply_text(f"✅ Next episode set to `{fmt_episode(int(value))}`.\n\n{text}", reply_markup=buttons)


@Client.on_message(filters.private & filters.command("clear"))
async def clear_collected(client, message):
    user_id = message.from_user.id
    asking.pop(user_id, None)
    removed = await db.delete_sequence_files(user_id)
    await message.reply_text(
        f"**🗑 Discarded {removed} collected file(s).**" if removed else "**Nothing collected to discard.**"
    )


# ── "work" trigger ─────────────────────────────────────────────────────────────

async def _work_text_filter(_, __, message):
    # Plain-text "work" / "work 5". Only claimed when /sequence is on or files are waiting,
    # so normal chat text and the regular manual-input prompts are never swallowed.
    if not message.from_user or not message.text or not WORK_RE.match(message.text):
        return False
    user_id = message.from_user.id
    enabled, _next = await db.get_sequence(user_id)
    return enabled or await db.count_sequence_files(user_id) > 0


def _start_from_message(message):
    if message.command:                                     # /work or /work 5
        arg = message.command[1] if len(message.command) > 1 else None
    else:                                                   # work / work 5
        arg = WORK_RE.match(message.text).group(1)
    return arg


@Client.on_message(filters.private & filters.command("work"))
@Client.on_message(filters.private & filters.text & filters.create(_work_text_filter))
async def work_cmd(client, message):
    user_id = message.from_user.id
    if user_id in busy or user_id in asking:
        return await message.reply_text("**Already working on it — answer the question above or wait a moment.**")

    arg = _start_from_message(message)
    if arg is not None and not valid_number(arg):
        return await message.reply_text("❌ Use a whole number from 1 to 9999, e.g. `work 5`.")

    files = await db.get_sequence_files(user_id)
    if not files:
        return await message.reply_text("**Nothing collected yet.** Turn on `/sequence` and forward your files first.")

    _enabled, stored_next = await db.get_sequence(user_id)
    start = int(arg) if arg is not None else stored_next

    # Default Season (if on) overrides every detected season, same as everywhere else
    ds_enabled, ds_season = await db.get_default_season(user_id)
    if ds_enabled and ds_season:
        for f in files:
            f['season'] = ds_season

    asking[user_id] = {'files': files, 'start': start, 'season': None, 'quality': None}
    await _next_question(client, message, user_id)


async def _next_question(client, message, user_id):
    """Ask once per missing field for the whole batch, then queue everything."""
    state = asking[user_id]
    files = state['files']

    if state['season'] is None and any(not f.get('season') for f in files):
        n = sum(1 for f in files if not f.get('season'))
        state['field'] = 'season'
        return await message.reply_text(
            f"**⚠️ Could not detect Season for {n} file(s).**\n"
            "Type the season number for them (or `skip`):"
        )

    if state['quality'] is None and any(not f.get('quality') for f in files):
        n = sum(1 for f in files if not f.get('quality'))
        state['field'] = 'quality'
        return await message.reply_text(
            f"**⚠️ Could not detect Quality for {n} file(s).**\n"
            "Type the quality for them, e.g. `720p` (or `skip`):"
        )

    asking.pop(user_id, None)
    await _queue_batch(client, message, user_id, state)


async def _asking_filter(_, __, message):
    return bool(
        message.from_user
        and message.from_user.id in asking
        and message.text
        and not message.text.startswith("/")
    )


@Client.on_message(filters.private & filters.text & filters.create(_asking_filter))
async def receive_batch_answer(client, message):
    user_id = message.from_user.id
    state = asking[user_id]
    value = message.text.strip()

    if value.lower() == "cancel":
        asking.pop(user_id, None)
        return await message.reply_text("**Cancelled.** Your files are still collected — send `work` again or `/clear`.")

    field = state['field']
    if value.lower() == "skip":
        state[field] = ""                  # answered: leave those files without it
    elif field == 'season':
        if not SEASON_RE.match(value) or int(value) < 1:
            return await message.reply_text("❌ Send a whole number from 1 to 99 (e.g. `1` or `01`), or `skip`.")
        state['season'] = value
    else:
        state['quality'] = value

    await _next_question(client, message, user_id)


async def _queue_batch(client, message, user_id, state):
    busy.add(user_id)
    try:
        files = sorted(state['files'], key=lambda f: f['message_id'])
        start = state['start']
        fmt = await db.get_format_template(user_id)
        if not fmt:
            return await message.reply_text("**Please set a rename format using /autorename**")

        msgs = await resolve_messages(client, message.chat.id, files)
        last = start + len(files) - 1
        summary = await message.reply_text(
            f"**✅ {len(files)} file(s) queued** — episodes `{fmt_episode(start)}` to `{fmt_episode(last)}`.\n"
            "Processing starts now."
        )
        for i, (rec, msg) in enumerate(zip(files, msgs)):
            await add_to_queue(
                client, msg, user_id, fmt, rec['file_id'], rec['file_name'], rec['media_type'],
                rec.get('season') or state['season'] or None,
                fmt_episode(start + i),
                rec.get('quality') or state['quality'] or None,
                notify=False, queue_msg=summary,
            )
        # Queue records are saved; now advance the counter and forget the collected files
        await db.set_sequence_next(user_id, last + 1)
        await db.delete_sequence_files(user_id, ids=[f['_id'] for f in files])
    finally:
        busy.discard(user_id)
