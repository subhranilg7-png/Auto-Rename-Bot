"""
/settings — one screen for everything personal: rename format (with live preview), caption,
thumbnail, metadata, and how files are sent. Everything is a button; you type only real values.
"""
import html
import logging

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from helper.database import codeflixbots as db

logger = logging.getLogger(__name__)
_e = html.escape
HTML = ParseMode.HTML

user_state = {}   # user_id -> {'step': 'fmt' | 'cap' | 'meta', 'msg': Message, 'draft': str, 'field': str}

SAMPLE_NAME = "Anime S2 - 05 [720p].mkv"
INSERTS = {
    'se': '{season}', 'ep': '{episode}', 'qu': '{quality}',
    'sxe': 'S{season}E{episode}', 'qb': '[{quality}]', 'dash': ' - ', 'sp': ' ',
}
META_FIELDS = [('title', 'Title'), ('author', 'Author'), ('artist', 'Artist'),
               ('audio', 'Audio'), ('subtitle', 'Subtitle'), ('video', 'Video')]


def btn(text, data):
    return InlineKeyboardButton(text, callback_data=data)


async def show(msg, text, rows):
    try:
        await msg.edit_text(text, parse_mode=HTML, reply_markup=InlineKeyboardMarkup(rows),
                            disable_web_page_preview=True)
    except MessageNotModified:
        pass
    except Exception as e:
        logger.warning(f"Settings edit failed ({e}); sending a new message")
        try:
            await msg.reply_text(text, parse_mode=HTML, reply_markup=InlineKeyboardMarkup(rows),
                                 disable_web_page_preview=True)
        except Exception as e2:
            logger.error(f"Settings send failed: {e2}")


# ── main screen ─────────────────────────────────────────────────────────────────

async def view_main(client, msg, uid, note=None):
    fmt = await db.get_format_template(uid)
    caption = await db.get_caption(uid)
    thumb = await db.get_thumbnail(uid)
    meta = await db.get_metadata(uid)
    media = (await db.get_media_preference(uid)) or 'document'
    text = ("<b>⚙️ Your settings</b>\n\n"
            f"📝 <b>Rename format:</b> {('<code>' + _e(fmt) + '</code>') if fmt else '⚠️ not set'}\n"
            f"💬 <b>Caption:</b> {'✅ set' if caption else '— none'}\n"
            f"🖼 <b>Thumbnail:</b> {'✅ set' if thumb else '— none'}\n"
            f"🏷 <b>Metadata:</b> {meta or 'Off'}\n"
            f"🎞 <b>Send as:</b> {_e(str(media)).capitalize()}"
            + (f"\n\n{note}" if note else ""))
    rows = [[btn("📝 Rename format", "us_fmt"), btn("💬 Caption", "us_cap")],
            [btn("🖼 Thumbnail", "us_th"), btn("🏷 Metadata", "us_meta")],
            [btn("🎞 Send as", "us_media")]]
    if await db.is_admin(uid):
        rows.append([btn("🛠 Admin panel", "pd")])
    rows.append([btn("✖ Close", "us_close")])
    await show(msg, text, rows)


@Client.on_message(filters.private & filters.command('settings'))
async def settings_cmd(client, message):
    user_state.pop(message.from_user.id, None)
    msg = await message.reply_text("⏳")
    await view_main(client, msg, message.from_user.id)


@Client.on_message(filters.private & filters.regex(r"^/"), group=-2)
async def commands_end_prompts(client, message):
    if message.from_user:
        user_state.pop(message.from_user.id, None)


def cb(pattern):
    return Client.on_callback_query(filters.regex(pattern), group=-1)


@cb(r"^us_open$")
async def cb_open(client, cq: CallbackQuery):
    user_state.pop(cq.from_user.id, None)
    await cq.answer()
    msg = await cq.message.reply_text("⏳")
    await view_main(client, msg, cq.from_user.id)


@cb(r"^us_back$")
async def cb_back(client, cq: CallbackQuery):
    user_state.pop(cq.from_user.id, None)
    await cq.answer()
    await view_main(client, cq.message, cq.from_user.id)


@cb(r"^us_close$")
async def cb_close(client, cq: CallbackQuery):
    user_state.pop(cq.from_user.id, None)
    await cq.answer()
    try:
        await cq.message.delete()
    except Exception:
        pass


# ── rename format builder with live preview ─────────────────────────────────────

async def view_builder(msg, uid, error=None):
    from plugins.file_rename import fill_template
    state = user_state[uid]
    draft = state['draft']
    ext = '.' + SAMPLE_NAME.rsplit('.', 1)[1]
    preview = (fill_template(draft, '2', '05', '720p') + ext) if draft else '—'
    warn = ""
    if draft and not any(x in draft for x in ('{episode}', 'Episode')):
        warn = "\n⚠️ No episode number in this format — every file of a show would get the same name."
    text = ("<b>📝 Rename format</b>\n\n"
            f"<b>Format:</b> {('<code>' + _e(draft) + '</code>') if draft else '<i>empty</i>'}\n"
            f"<b>Preview:</b> <code>{_e(preview)}</code>\n"
            f"<i>(for a file like {_e(SAMPLE_NAME)})</i>{warn}\n\n"
            "Tap to add variables, or type the whole format yourself."
            + (f"\n\n⚠️ {error}" if error else ""))
    rows = [[btn("➕ {season}", "us_ins:se"), btn("➕ {episode}", "us_ins:ep"), btn("➕ {quality}", "us_ins:qu")],
            [btn("➕ S{season}E{episode}", "us_ins:sxe"), btn("➕ [{quality}]", "us_ins:qb")],
            [btn("➕ ' - '", "us_ins:dash"), btn("➕ space", "us_ins:sp"), btn("⌫ Clear", "us_clr")],
            [btn("💾 Save", "us_save"), btn("✖ Cancel", "us_back")]]
    await show(msg, text, rows)


@cb(r"^us_fmt$")
async def cb_fmt(client, cq: CallbackQuery):
    uid = cq.from_user.id
    await cq.answer()
    user_state[uid] = {'step': 'fmt', 'msg': cq.message, 'draft': (await db.get_format_template(uid)) or ''}
    await view_builder(cq.message, uid)


@cb(r"^us_ins:(se|ep|qu|sxe|qb|dash|sp)$")
async def cb_insert(client, cq: CallbackQuery):
    uid = cq.from_user.id
    state = user_state.get(uid)
    if not state or state['step'] != 'fmt':
        return await cq.answer("That screen expired — open /settings again.", show_alert=True)
    state['draft'] += INSERTS[cq.matches[0].group(1)]
    await cq.answer()
    await view_builder(cq.message, uid)


@cb(r"^us_clr$")
async def cb_clear(client, cq: CallbackQuery):
    uid = cq.from_user.id
    state = user_state.get(uid)
    if not state or state['step'] != 'fmt':
        return await cq.answer("That screen expired — open /settings again.", show_alert=True)
    state['draft'] = ''
    await cq.answer()
    await view_builder(cq.message, uid)


@cb(r"^us_save$")
async def cb_save(client, cq: CallbackQuery):
    uid = cq.from_user.id
    state = user_state.get(uid)
    if not state or state['step'] != 'fmt':
        return await cq.answer("That screen expired — open /settings again.", show_alert=True)
    if not state['draft'].strip():
        return await cq.answer("The format is empty.", show_alert=True)
    await db.set_format_template(uid, state['draft'].strip())
    user_state.pop(uid, None)
    await cq.answer("Saved ✅")
    await view_main(client, cq.message, uid, note="✅ Rename format saved.")


# ── caption ─────────────────────────────────────────────────────────────────────

@cb(r"^us_cap$")
async def cb_caption(client, cq: CallbackQuery):
    uid = cq.from_user.id
    caption = await db.get_caption(uid)
    user_state.pop(uid, None)
    await cq.answer()
    text = ("<b>💬 Caption</b>\n\n"
            f"<b>Current:</b> {('<code>' + _e(caption) + '</code>') if caption else '— none (the new file name is used)'}\n\n"
            "Variables: <code>{filename}</code> <code>{filesize}</code> <code>{duration}</code>")
    await show(cq.message, text, [[btn("✏️ Set / change", "us_capset")],
                                  [btn("🗑 Remove", "us_capdel")], [btn("⬅️ Back", "us_back")]])


@cb(r"^us_capset$")
async def cb_caption_set(client, cq: CallbackQuery):
    uid = cq.from_user.id
    await cq.answer()
    user_state[uid] = {'step': 'cap', 'msg': cq.message}
    await show(cq.message, "<b>💬 Caption</b>\n\nSend the new caption.\n"
                           "Variables: <code>{filename}</code> <code>{filesize}</code> <code>{duration}</code>",
               [[btn("✖ Cancel", "us_cap")]])


@cb(r"^us_capdel$")
async def cb_caption_del(client, cq: CallbackQuery):
    await db.set_caption(cq.from_user.id, None)
    await cq.answer("Removed")
    await view_main(client, cq.message, cq.from_user.id, note="✅ Caption removed.")


# ── thumbnail ───────────────────────────────────────────────────────────────────

@cb(r"^us_th$")
async def cb_thumb(client, cq: CallbackQuery):
    uid = cq.from_user.id
    thumb = await db.get_thumbnail(uid)
    await cq.answer()
    text = ("<b>🖼 Thumbnail</b>\n\n"
            f"{'✅ A thumbnail is set.' if thumb else '— No thumbnail set.'}\n\n"
            "To set or replace it, <b>just send me a photo</b> (it is cropped to a square).")
    rows = []
    if thumb:
        rows.append([btn("👁 View", "us_thv"), btn("🗑 Delete", "us_thd")])
    rows.append([btn("⬅️ Back", "us_back")])
    await show(cq.message, text, rows)


@cb(r"^us_thv$")
async def cb_thumb_view(client, cq: CallbackQuery):
    thumb = await db.get_thumbnail(cq.from_user.id)
    if not thumb:
        return await cq.answer("No thumbnail set.", show_alert=True)
    await cq.answer()
    try:
        await client.send_photo(cq.from_user.id, thumb)
    except Exception:
        await client.send_message(cq.from_user.id, "That thumbnail can't be shown any more — send a new photo.")


@cb(r"^us_thd$")
async def cb_thumb_del(client, cq: CallbackQuery):
    from plugins.file_rename import clear_thumb_cache
    await db.set_thumbnail(cq.from_user.id, file_id=None)
    clear_thumb_cache(cq.from_user.id)
    await cq.answer("Deleted")
    await view_main(client, cq.message, cq.from_user.id, note="✅ Thumbnail deleted.")


# ── metadata ────────────────────────────────────────────────────────────────────

async def view_meta(client, msg, uid):
    meta = await db.get_metadata(uid) or 'Off'
    lines = ["<b>🏷 Metadata</b>", "", f"<b>Embed metadata:</b> {meta}", ""]
    for key, label in META_FIELDS:
        value = await getattr(db, f"get_{key}")(uid)
        lines.append(f"<b>{label}:</b> {_e(str(value)) if value else '—'}")
    rows = [[btn("🔄 Turn " + ("off" if meta == 'On' else "on"), "us_mt")]]
    row = []
    for key, label in META_FIELDS:
        row.append(btn(f"✏️ {label}", f"us_mf:{key}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([btn("⬅️ Back", "us_back")])
    await show(msg, "\n".join(lines), rows)


@cb(r"^us_meta$")
async def cb_meta(client, cq: CallbackQuery):
    user_state.pop(cq.from_user.id, None)
    await cq.answer()
    await view_meta(client, cq.message, cq.from_user.id)


@cb(r"^us_mt$")
async def cb_meta_toggle(client, cq: CallbackQuery):
    uid = cq.from_user.id
    current = await db.get_metadata(uid) or 'Off'
    await db.set_metadata(uid, 'Off' if current == 'On' else 'On')
    await cq.answer("Saved")
    await view_meta(client, cq.message, uid)


@cb(r"^us_mf:(title|author|artist|audio|subtitle|video)$")
async def cb_meta_field(client, cq: CallbackQuery):
    uid = cq.from_user.id
    field = cq.matches[0].group(1)
    await cq.answer()
    user_state[uid] = {'step': 'meta', 'msg': cq.message, 'field': field}
    await show(cq.message, f"<b>🏷 {field.capitalize()}</b>\n\nSend the new value.", [[btn("✖ Cancel", "us_meta")]])


# ── send as ─────────────────────────────────────────────────────────────────────

@cb(r"^us_media$")
async def cb_media(client, cq: CallbackQuery):
    current = (await db.get_media_preference(cq.from_user.id)) or 'document'
    await cq.answer()
    rows = [[btn(("✅ " if current == k else "") + label, f"us_md:{k}")]
            for k, label in (('document', '📜 Document'), ('video', '🎬 Video'), ('audio', '🎵 Audio'))]
    rows.append([btn("⬅️ Back", "us_back")])
    await show(cq.message, "<b>🎞 Send files as</b>", rows)


@cb(r"^us_md:(document|video|audio)$")
async def cb_media_set(client, cq: CallbackQuery):
    await db.set_media_preference(cq.from_user.id, cq.matches[0].group(1))
    await cq.answer("Saved ✅")
    await view_main(client, cq.message, cq.from_user.id, note="✅ Saved.")


# ── typed input ─────────────────────────────────────────────────────────────────

@Client.on_message(filters.private & filters.text & ~filters.regex(r"^/"), group=3)
async def settings_input(client, message):
    uid = message.from_user.id
    state = user_state.get(uid)
    if not state:
        return
    text = message.text.strip()
    msg = state['msg']

    async def tidy():
        try:
            await message.delete()
        except Exception:
            pass

    if state['step'] == 'fmt':
        state['draft'] = text
        await tidy()
        return await view_builder(msg, uid)
    if state['step'] == 'cap':
        await db.set_caption(uid, text)
        user_state.pop(uid, None)
        await tidy()
        return await view_main(client, msg, uid, note="✅ Caption saved.")
    if state['step'] == 'meta':
        await getattr(db, f"set_{state['field']}")(uid, text)
        user_state.pop(uid, None)
        await tidy()
        return await view_meta(client, msg, uid)
