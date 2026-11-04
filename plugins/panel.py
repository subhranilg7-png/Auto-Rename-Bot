"""
Admin panel: everything for sub channels, formats, patterns and settings is done with buttons
on ONE message that edits itself. Typed input is only needed for real values (a title, a post
text, a link ...). Commands (/panel, /list_channels, /add_channel, ...) just open this panel.
"""
import re
import html
import uuid
import logging

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import RPCError, MessageNotModified
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from helper.database import codeflixbots as db
from helper.session_state import auto_post_sessions
from helper import backup
from helper import patterns as custom_patterns
from helper.post_render import render_post, check_post_text
from plugins.channel_admin import admin_filter, admin_state

logger = logging.getLogger(__name__)
_e = html.escape
HTML = ParseMode.HTML


def btn(text, data):
    return InlineKeyboardButton(text, callback_data=data)


def kb(rows):
    return InlineKeyboardMarkup(rows)


async def show(msg, text, rows=None):
    """Edit the panel message in place (HTML)."""
    try:
        await msg.edit_text(text, parse_mode=HTML, reply_markup=kb(rows) if rows else None,
                            disable_web_page_preview=True)
    except MessageNotModified:
        pass
    except Exception as e:
        logger.warning(f"Panel edit failed ({e}); sending a new message")
        try:
            await msg.reply_text(text, parse_mode=HTML, reply_markup=kb(rows) if rows else None,
                                 disable_web_page_preview=True)
        except Exception as e2:
            logger.error(f"Panel send failed: {e2}")


def pre(text, limit=350):
    text = text or ''
    if len(text) > limit:
        text = text[:limit] + '…'
    return f"<pre>{_e(text)}</pre>"


def start_prompt(uid, msg, step, back, **data):
    admin_state[uid] = {'action': 'panel', 'step': step, 'msg': msg, 'back': back, 'data': data}


async def _admin_ok(cq):
    if await db.is_admin(cq.from_user.id):
        return True
    await cq.answer("Admins only.", show_alert=True)
    return False


# ═══ Dashboard ══════════════════════════════════════════════════════════════════

async def view_dashboard(client, msg, uid):
    session = auto_post_sessions.get(uid)
    lines = ["<b>🛠 Admin panel</b>", ""]
    rows = []
    if session:
        lines.append(f"🟢 <b>Auto-post active:</b> {_e(session['channel_title'])} — <code>{_e(session['format']['label'])}</code>")
        rows.append([btn("⏹ Stop auto-post", "ps_stop"), btn("🔄 Change", "ps_start")])
    else:
        lines.append("⚪ No auto-post session running.")
        rows.append([btn("▶️ Start auto-post", "ps_start")])
    for cid, fid in await db.ap_recent_get(uid):
        ch = await db.get_subchannel(cid)
        fmt = await db.get_format(cid, fid) if ch else None
        if ch and fmt:
            rows.append([btn(f"⚡ {ch.get('title', cid)} · {fmt['label']}"[:60], f"apfmt_{cid}_{fid}")])
    rows += [
        [btn("📡 Channels", "cpl"), btn("🧩 Patterns", "ptl")],
        [btn("⚙️ Settings", "pset"), btn("📊 Status", "pstat")],
        [btn("✖ Close", "pclose")],
    ]
    await show(msg, "\n".join(lines), rows)


@Client.on_message(filters.private & filters.command('panel') & admin_filter)
async def panel_cmd(client, message):
    admin_state.pop(message.from_user.id, None)
    msg = await message.reply_text("⏳")
    await view_dashboard(client, msg, message.from_user.id)


# ═══ Channels ═══════════════════════════════════════════════════════════════════

async def view_channels(client, msg, hint=None):
    channels = await db.get_all_subchannels()
    text = "<b>📡 Sub channels</b>\n\n" + (hint or "Tap a channel to view and edit everything for it.")
    rows = []
    for ch in channels:
        warn = '⚠️ ' if (not ch.get('invite_link') or not ch.get('formats')) else ''
        rows.append([btn(f"{warn}{ch.get('title', ch['_id'])}"[:60], f"cp:{ch['_id']}")])
    if not channels:
        text += "\n\n<i>No sub channels yet.</i>"
    rows.append([btn("➕ Add channel", "cadd")])
    rows.append([btn("⬅️ Back", "pd")])
    await show(msg, text, rows)


async def view_channel(client, msg, cid, note=None):
    ch = await db.get_subchannel(cid)
    if not ch:
        return await view_channels(client, msg, "That channel no longer exists.")
    n = len(ch.get('formats', []))
    text = (f"<b>📡 {_e(ch.get('title', str(cid)))}</b>\n\n"
            f"<b>ID:</b> <code>{cid}</code>\n"
            f"<b>Invite link:</b> {_e(ch['invite_link']) if ch.get('invite_link') else '⚠️ not set'}\n"
            f"<b>Formats:</b> {n}" + (f"\n\n{note}" if note else ""))
    rows = [
        [btn("📋 Formats", f"cf:{cid}"), btn("➕ Add format", f"fa:{cid}")],
        [btn("🔗 Invite link", f"ci:{cid}"), btn("▶️ Auto-post", f"apch_{cid}")],
        [btn("🗑 Delete channel", f"cx:{cid}")],
        [btn("⬅️ Back", "cpl")],
    ]
    await show(msg, text, rows)


async def view_formats(client, msg, cid):
    ch = await db.get_subchannel(cid)
    if not ch:
        return await view_channels(client, msg)
    formats = ch.get('formats', [])
    text = f"<b>📋 Formats — {_e(ch.get('title', str(cid)))}</b>\n\n" + (
        "Tap a format to view and edit it." if formats else "<i>No formats yet.</i>")
    rows = [[btn(f"🎞 {f['label']}"[:60], f"fp:{cid}:{f['format_id']}")] for f in formats]
    rows.append([btn("➕ Add format", f"fa:{cid}")])
    rows.append([btn("⬅️ Back", f"cp:{cid}")])
    await show(msg, text, rows)


async def view_invite(client, msg, cid, note=None):
    ch = await db.get_subchannel(cid)
    if not ch:
        return await view_channels(client, msg)
    text = (f"<b>🔗 Invite link — {_e(ch.get('title', str(cid)))}</b>\n\n"
            f"{_e(ch['invite_link']) if ch.get('invite_link') else '⚠️ No link set.'}\n\n"
            "This is the link behind the DOWNLOAD button on Main channel posts." + (f"\n\n{note}" if note else ""))
    rows = [[btn("🔄 Create new", f"cin:{cid}"), btn("✏️ Enter manually", f"cie:{cid}")],
            [btn("⬅️ Back", f"cp:{cid}")]]
    await show(msg, text, rows)


# ═══ Formats ════════════════════════════════════════════════════════════════════

async def view_format(client, msg, cid, fid, note=None):
    ch = await db.get_subchannel(cid)
    fmt = await db.get_format(cid, fid) if ch else None
    if not fmt:
        return await view_channels(client, msg, "That format no longer exists.")
    styled = "styled" if fmt.get('main_html') or fmt.get('sub_html') else "classic (bold + R&lt;…&gt;R)"
    text = (f"<b>🎞 {_e(fmt['label'])}</b> — {_e(ch.get('title', str(cid)))}\n\n"
            f"<b>Rename format:</b>\n{pre(fmt['rename_format'], 200)}"
            f"<b>Main post:</b>\n{pre(fmt['main_post'])}"
            f"<b>Sub post:</b>\n{pre(fmt['sub_post'])}"
            f"<b>Thumbnail:</b> ✅ set   <b>Style:</b> {styled}   "
            f"<b>Backup:</b> {'✅' if fmt.get('backup_msg_id') else '⚠️ none'}" + (f"\n\n{note}" if note else ""))
    rows = [
        [btn("✏️ Label", f"fe:lb:{cid}:{fid}"), btn("🖼 Thumbnail", f"fe:th:{cid}:{fid}")],
        [btn("✏️ Rename format", f"fe:rn:{cid}:{fid}")],
        [btn("✏️ Main post", f"fe:mp:{cid}:{fid}"), btn("✏️ Sub post", f"fe:sp:{cid}:{fid}")],
        [btn("👁 Preview", f"fv:{cid}:{fid}"), btn("🗑 Delete", f"fd:{cid}:{fid}")],
        [btn("⬅️ Back", f"cf:{cid}")],
    ]
    await show(msg, text, rows)


FIELD_INFO = {
    'lb': ('label', "Label", "Send the new <b>label</b> (a short name, e.g. the anime title)."),
    'rn': ('rename_format', "Rename format",
           "Send the new <b>rename format</b>. Use <code>{season}</code> <code>{episode}</code> <code>{quality}</code>.\n"
           "Example: <code>Anime Title S{season}E{episode} [{quality}]</code>"),
    'mp': ('main_post', "Main post",
           "Send the new <b>Main channel post</b>, styled the way you want it (bold, italic, links … are kept).\n"
           "Use <code>{season}</code> and <code>{episode}</code> where they should appear."),
    'sp': ('sub_post', "Sub post",
           "Send the new <b>Sub channel post</b>, styled the way you want it (bold, italic, links … are kept).\n"
           "Use <code>{season}</code> and <code>{episode}</code> where they should appear."),
    'th': ('thumbnail', "Thumbnail", "Send the new <b>thumbnail</b> as a photo."),
}


def _all_labels(channels, skip=None):
    out = set()
    for ch in channels:
        for f in ch.get('formats', []):
            if skip and (ch['_id'], f['format_id']) == skip:
                continue
            out.add(f['label'].strip().lower())
    return out


def _clear_thumb_cache(fid):
    import os
    for suffix in ('raw', 'crop'):
        try:
            os.remove(f"downloads/thumbs/{fid}_{suffix}.jpg")
        except OSError:
            pass


async def _refresh_backup(client, cid, fid):
    ch = await db.get_subchannel(cid)
    fmt = await db.get_format(cid, fid) if ch else None
    if ch and fmt:
        await backup.sync_format(client, ch, fmt)


async def apply_field(client, uid, state, message):
    """Validate + save one edited field. Returns an error string, or None on success."""
    cid, fid, key = state['data']['cid'], state['data']['fid'], state['data']['key']
    field, _label, _hint = FIELD_INFO[key]
    fields = {}

    if key == 'th':
        if not message.photo:
            return "Please send a <b>photo</b>."
        fields['thumbnail'] = message.photo.file_id
    else:
        if not message.text:
            return "Please send it as <b>text</b>."
        if key == 'lb':
            value = message.text.strip()
            if not value or len(value) > 40:
                return "The label must be 1–40 characters."
            if value.lower() in _all_labels(await db.get_all_subchannels(), skip=(cid, fid)):
                return "Another format already uses that label — labels must be unique."
            fields['label'] = value
        elif key == 'rn':
            value = message.text.strip()
            if '{episode}' not in value:
                return "The rename format must contain <code>{episode}</code>."
            fields['rename_format'] = value
        else:  # mp / sp
            err = check_post_text(message.text.html, str(message.text))
            if err:
                return err.replace('`', '')
            fields[field] = message.text.html
            fields['main_html' if key == 'mp' else 'sub_html'] = True

    await db.update_format_field(cid, fid, fields)
    if key == 'th':
        _clear_thumb_cache(fid)
    await _refresh_backup(client, cid, fid)
    return None


# ═══ Wizard: new format ═════════════════════════════════════════════════════════

WIZ_STEPS = ['thumb', 'rename', 'main', 'sub', 'label']
WIZ_PROMPTS = {
    'thumb': "Send the <b>thumbnail</b> for this format as a photo.",
    'rename': ("Send the <b>rename format</b>. Use <code>{season}</code> <code>{episode}</code> <code>{quality}</code>.\n"
               "Example: <code>Anime Title S{season}E{episode} [{quality}]</code>"),
    'main': ("Send the <b>Main channel post</b>, styled the way you want it (bold, italic, links … are kept).\n"
             "Use <code>{season}</code> and <code>{episode}</code> where they should appear."),
    'sub': ("Send the <b>Sub channel post</b>, styled the way you want it (bold, italic, links … are kept).\n"
            "Use <code>{season}</code> and <code>{episode}</code> where they should appear."),
    'label': "Send a short <b>label</b> for this format (e.g. the anime title).",
}


async def wiz_prompt(msg, state, error=None):
    step = state['step']
    n = WIZ_STEPS.index(step) + 1
    text = f"<b>➕ New format — step {n}/5</b>\n\n" + (f"⚠️ {error}\n\n" if error else "") + WIZ_PROMPTS[step]
    row = []
    if n > 1:
        row.append(btn("⬅️ Back", "wzb"))
    if step == 'label':
        row.append(btn("⏭ Use automatic label", "wzs"))
    row.append(btn("✖ Cancel", "pc"))
    await show(msg, text, [row])


async def wiz_finish(client, uid, state, label):
    d = state['data']
    cid = d['cid']
    admin_state.pop(uid, None)
    fid = uuid.uuid4().hex[:8]
    fmt = {
        'format_id': fid, 'label': label, 'thumbnail': d['thumbnail'],
        'rename_format': d['rename'], 'main_post': d['main'], 'sub_post': d['sub'],
        'main_html': True, 'sub_html': True,
    }
    await db.add_format(cid, fmt)
    await _refresh_backup(client, cid, fid)
    await view_format(client, state['msg'], cid, fid, note="✅ Format added.")


async def wiz_input(client, uid, state, message):
    step, d = state['step'], state['data']
    msg = state['msg']
    err = None
    if step == 'thumb':
        if not message.photo:
            err = "Please send a <b>photo</b>."
        else:
            d['thumbnail'] = message.photo.file_id
    elif step == 'rename':
        value = (message.text or '').strip()
        if '{episode}' not in value:
            err = "The rename format must contain <code>{episode}</code>."
        else:
            d['rename'] = value
    elif step in ('main', 'sub'):
        if not message.text:
            err = "Please send it as <b>text</b>."
        else:
            err = check_post_text(message.text.html, str(message.text))
            err = err.replace('`', '') if err else None
            if not err:
                d[step] = message.text.html
    elif step == 'label':
        value = (message.text or '').strip()
        if not value or len(value) > 40:
            err = "The label must be 1–40 characters."
        elif value.lower() in _all_labels(await db.get_all_subchannels()):
            err = "Another format already uses that label — labels must be unique."
        else:
            return await wiz_finish(client, uid, state, value)
    if err:
        return await wiz_prompt(msg, state, err)
    state['step'] = WIZ_STEPS[WIZ_STEPS.index(step) + 1]
    await wiz_prompt(msg, state)


# ═══ Add channel ════════════════════════════════════════════════════════════════

async def resolve_channel(client, message):
    """Forwarded message / @username / -100 id → (chat, error_html)."""
    try:
        if message.forward_from_chat:
            chat = await client.get_chat(message.forward_from_chat.id)
        elif message.text:
            chat = await client.get_chat(message.text.strip())
        else:
            return None, "Forward a message from the channel, or send its ID / @username."
        member = await client.get_chat_member(chat.id, "me")
        if not member.privileges:
            return None, "The bot is a member there but <b>not an admin</b>. Make it an admin and try again."
        return chat, None
    except RPCError as e:
        return None, f"Couldn't verify that channel: <code>{_e(str(e))}</code>"


async def finish_add_channel(client, uid, state, link):
    d = state['data']
    admin_state.pop(uid, None)
    existing = await db.get_subchannel(d['channel_id'])
    if existing:
        if link:
            await db.set_invite_link(d['channel_id'], link)
        return await view_channel(client, state['msg'], d['channel_id'],
                                  note="ℹ️ This channel was already added — nothing was lost.")
    await db.add_subchannel(d['channel_id'], d['channel_title'], link, uid)
    await view_channel(client, state['msg'], d['channel_id'],
                       note="✅ Channel added. Tap <b>➕ Add format</b> to set up its first format.")


async def create_link(client, cid):
    try:
        return (await client.create_chat_invite_link(cid)).invite_link, None
    except RPCError as e:
        return None, f"Couldn't create a link: <code>{_e(str(e))}</code> (does the bot have invite-link permission?)"


def valid_link(text):
    t = (text or '').strip()
    return t if t.startswith(('https://t.me/', 'http://t.me/', 'https://telegram.me/')) else None


# ═══ Typed input dispatcher (called from channel_admin's conversation handler) ═══

async def handle_input(client, message, state):
    uid = message.from_user.id
    step, d, msg = state['step'], state['data'], state['msg']

    async def done_delete():
        try:
            await message.delete()
        except Exception:
            pass

    if step == 'edit_field':
        err = await apply_field(client, uid, state, message)
        if err:
            return await prompt_edit(msg, d['cid'], d['fid'], d['key'], err)
        admin_state.pop(uid, None)
        await done_delete()
        return await view_format(client, msg, d['cid'], d['fid'], note="✅ Saved.")

    if step.startswith('wiz_'):
        state['step'] = step[4:]
        await wiz_input(client, uid, state, message)
        if uid in admin_state:
            admin_state[uid]['step'] = 'wiz_' + admin_state[uid]['step']
        return

    if step == 'add_channel_chat':
        chat, err = await resolve_channel(client, message)
        if err:
            return await show(msg, f"<b>➕ Add channel</b>\n\n⚠️ {err}\n\nForward a message from the channel, or send its ID / @username.",
                              [[btn("✖ Cancel", "pc")]])
        d['channel_id'], d['channel_title'] = chat.id, chat.title
        state['step'] = 'add_channel_link'
        await done_delete()
        return await show(msg, f"<b>➕ Add channel — {_e(chat.title)}</b>\n\nSend the <b>invite link</b> for the DOWNLOAD button, "
                               "or let me create one.",
                          [[btn("🔗 Auto-create", "cauto")], [btn("✖ Cancel", "pc")]])

    if step == 'add_channel_link':
        link = valid_link(message.text)
        if not link:
            return await show(msg, f"<b>➕ Add channel — {_e(d['channel_title'])}</b>\n\n⚠️ That doesn't look like a Telegram link "
                                   "(it should start with https://t.me/).\n\nSend the invite link, or let me create one.",
                              [[btn("🔗 Auto-create", "cauto")], [btn("✖ Cancel", "pc")]])
        await done_delete()
        return await finish_add_channel(client, uid, state, link)

    if step == 'invite_manual':
        link = valid_link(message.text)
        if not link:
            return await show(msg, "⚠️ That doesn't look like a Telegram link (https://t.me/…). Send it again.",
                              [[btn("✖ Cancel", "pc")]])
        await db.set_invite_link(d['cid'], link)
        admin_state.pop(uid, None)
        await done_delete()
        return await view_invite(client, msg, d['cid'], note="✅ Saved.")

    if step == 'paste_backup':
        parsed = backup.parse_backup(message)
        if not parsed:
            return await show(msg, "<b>📥 Paste a backup</b>\n\n⚠️ I couldn't read that as a format backup. "
                                   "Forward or paste one post from your Save channel.",
                              [[btn("✖ Cancel", "pc")]])
        d['parsed'] = parsed
        await done_delete()
        return await view_import_choice(client, msg, d['cid'], parsed)

    if step == 'pattern_template':
        try:
            custom_patterns.compile_template(message.text or '')
        except ValueError as e:
            return await show(msg, f"<b>🧩 Pattern</b>\n\n⚠️ {_e(str(e)).replace('`', '')}\n\nSend the pattern again.",
                              [[btn("✖ Cancel", "pc")]])
        d['template'] = message.text.strip()
        state['step'] = 'pattern_sample'
        await done_delete()
        return await show(msg, f"<b>🧩 Pattern</b>\n<code>{_e(d['template'])}</code>\n\nNow send a <b>real filename</b> to test it on.",
                          [[btn("💾 Save without testing", "ptsave")], [btn("✖ Cancel", "pc")]])

    if step == 'pattern_sample':
        regex = custom_patterns.compile_template(d['template'])
        m = regex.search(message.text or '')
        await done_delete()
        if m:
            g = m.groupdict()
            result = (f"✅ <b>Matches.</b>  Season: <code>{g.get('season') or '—'}</code>  "
                      f"Episode: <code>{g.get('episode')}</code>  Quality: <code>{(g.get('quality') or '—')}</code>")
        else:
            result = "❌ <b>No match</b> on that filename."
        return await show(msg, f"<b>🧩 Pattern</b>\n<code>{_e(d['template'])}</code>\n\n{result}",
                          [[btn("💾 Save", "ptsave"), btn("✏️ Change pattern", "ptchg")],
                           [btn("✖ Cancel", "pc")]])

    if step == 'pattern_test':
        from plugins.file_rename import explain_detection
        r = explain_detection(message.text or '')
        await done_delete()
        text = ("<b>🧪 Test a filename</b>\n\n"
                f"Season: <code>{r['season'] or '—'}</code>\n"
                f"Episode: <code>{r['episode'] or '—'}</code>\n"
                f"Quality: <code>{r['quality'] or '—'}</code>\n"
                f"Decided by: {_e(r['source'])}\n\nSend another filename, or go back.")
        return await show(msg, text, [[btn("⬅️ Done", "ptl")]])


# ═══ Callbacks ══════════════════════════════════════════════════════════════════

def cb(pattern):
    return Client.on_callback_query(filters.regex(pattern), group=-1)


@cb(r"^pd$")
async def cb_dashboard(client, cq: CallbackQuery):
    if not await _admin_ok(cq):
        return
    admin_state.pop(cq.from_user.id, None)
    await cq.answer()
    await view_dashboard(client, cq.message, cq.from_user.id)


@cb(r"^pclose$")
async def cb_close(client, cq: CallbackQuery):
    admin_state.pop(cq.from_user.id, None)
    await cq.answer()
    try:
        await cq.message.delete()
    except Exception:
        pass


@cb(r"^pc$")
async def cb_prompt_cancel(client, cq: CallbackQuery):
    if not await _admin_ok(cq):
        return
    state = admin_state.pop(cq.from_user.id, None)
    await cq.answer("Cancelled")
    back = (state or {}).get('back', 'pd')
    await goto(client, cq.message, cq.from_user.id, back)


async def goto(client, msg, uid, code):
    """Re-open a view from its callback code."""
    parts = code.split(':')
    head = parts[0]
    if head == 'cp':
        return await view_channel(client, msg, int(parts[1]))
    if head == 'cf':
        return await view_formats(client, msg, int(parts[1]))
    if head == 'ci':
        return await view_invite(client, msg, int(parts[1]))
    if head == 'fp':
        return await view_format(client, msg, int(parts[1]), parts[2])
    if head == 'fa':
        return await view_add_format(client, msg, int(parts[1]))
    if head == 'cpl':
        return await view_channels(client, msg)
    if head == 'ptl':
        return await view_patterns(client, msg)
    if head == 'pset':
        return await view_settings(client, msg)
    return await view_dashboard(client, msg, uid)


# ── channels ────────────────────────────────────────────────────────────────────

@cb(r"^cpl$")
async def cb_channels(client, cq):
    if not await _admin_ok(cq):
        return
    admin_state.pop(cq.from_user.id, None)
    await cq.answer()
    await view_channels(client, cq.message)


@cb(r"^cp:(-?\d+)$")
async def cb_channel(client, cq):
    if not await _admin_ok(cq):
        return
    admin_state.pop(cq.from_user.id, None)
    await cq.answer()
    await view_channel(client, cq.message, int(cq.matches[0].group(1)))


@cb(r"^cf:(-?\d+)$")
async def cb_formats(client, cq):
    if not await _admin_ok(cq):
        return
    await cq.answer()
    await view_formats(client, cq.message, int(cq.matches[0].group(1)))


@cb(r"^cadd$")
async def cb_add_channel(client, cq):
    if not await _admin_ok(cq):
        return
    await cq.answer()
    start_prompt(cq.from_user.id, cq.message, 'add_channel_chat', 'cpl')
    await show(cq.message, "<b>➕ Add channel</b>\n\nForward a message from the channel, or send its ID / @username.\n"
                           "The bot must already be an admin there (with invite-link permission).",
               [[btn("✖ Cancel", "pc")]])


@Client.on_message(filters.private & filters.command('add_channel') & admin_filter)
async def add_channel_cmd(client, message):
    msg = await message.reply_text("⏳")
    start_prompt(message.from_user.id, msg, 'add_channel_chat', 'cpl')
    await show(msg, "<b>➕ Add channel</b>\n\nForward a message from the channel, or send its ID / @username.\n"
                    "The bot must already be an admin there (with invite-link permission).",
               [[btn("✖ Cancel", "pc")]])


@cb(r"^cauto$")
async def cb_auto_link(client, cq):
    if not await _admin_ok(cq):
        return
    state = admin_state.get(cq.from_user.id)
    if not state or state.get('step') != 'add_channel_link':
        return await cq.answer("That step has expired.", show_alert=True)
    link, err = await create_link(client, state['data']['channel_id'])
    if err:
        await cq.answer("Couldn't create a link", show_alert=True)
        return await show(cq.message, f"<b>➕ Add channel — {_e(state['data']['channel_title'])}</b>\n\n⚠️ {err}\n\n"
                                      "Send an invite link yourself instead.", [[btn("✖ Cancel", "pc")]])
    await cq.answer()
    await finish_add_channel(client, cq.from_user.id, state, link)


@cb(r"^ci:(-?\d+)$")
async def cb_invite(client, cq):
    if not await _admin_ok(cq):
        return
    await cq.answer()
    await view_invite(client, cq.message, int(cq.matches[0].group(1)))


@cb(r"^cin:(-?\d+)$")
async def cb_invite_new(client, cq):
    if not await _admin_ok(cq):
        return
    cid = int(cq.matches[0].group(1))
    link, err = await create_link(client, cid)
    if err:
        await cq.answer("Couldn't create a link", show_alert=True)
        return await view_invite(client, cq.message, cid, note=f"⚠️ {err}")
    await db.set_invite_link(cid, link)
    await cq.answer("New link created")
    await view_invite(client, cq.message, cid, note="✅ New link saved.")


@cb(r"^cie:(-?\d+)$")
async def cb_invite_manual(client, cq):
    if not await _admin_ok(cq):
        return
    cid = int(cq.matches[0].group(1))
    await cq.answer()
    start_prompt(cq.from_user.id, cq.message, 'invite_manual', f"ci:{cid}", cid=cid)
    await show(cq.message, "<b>🔗 Invite link</b>\n\nSend the invite link (https://t.me/…).", [[btn("✖ Cancel", "pc")]])


# ── delete channel ──────────────────────────────────────────────────────────────

@cb(r"^cx:(-?\d+)$")
async def cb_delete_channel(client, cq):
    if not await _admin_ok(cq):
        return
    cid = int(cq.matches[0].group(1))
    ch = await db.get_subchannel(cid)
    if not ch:
        return await cq.answer("Channel not found.", show_alert=True)
    await cq.answer()
    await show(cq.message,
               f"<b>🗑 Delete {_e(ch.get('title', str(cid)))}?</b>\n\nThis removes the channel and its "
               f"{len(ch.get('formats', []))} saved format(s) (and their backup posts) from the bot. "
               "The Telegram channel itself is not touched.",
               [[btn("✅ Yes, delete", f"cxy:{cid}"), btn("✖ Cancel", f"cp:{cid}")]])


@cb(r"^cxy:(-?\d+)$")
async def cb_delete_channel_yes(client, cq):
    if not await _admin_ok(cq):
        return
    cid = int(cq.matches[0].group(1))
    ch = await db.get_subchannel(cid)
    if not ch:
        return await cq.answer("Already deleted.")
    for fmt in ch.get('formats', []):
        await backup.delete_backup(client, fmt)
        _clear_thumb_cache(fmt['format_id'])
    await db.delete_subchannel(cid)
    for uid in [u for u, s in auto_post_sessions.items() if s.get('channel_id') == cid]:
        auto_post_sessions.pop(uid, None)
        await db.ap_session_del(uid)
    await db.ap_groups_delete_for_channel(cid)
    try:
        import plugins.auto_post as ap
        for key in [k for k in ap.pending_groups if k[1] == cid]:
            group = ap.pending_groups.pop(key)
            if group.get('timer_task'):
                group['timer_task'].cancel()
    except Exception as e:
        logger.error(f"Could not clear pending groups for {cid}: {e}")
    await cq.answer("Deleted ✅")
    save = await db.get_save_channel()
    if save:
        try:
            await client.send_message(save, f"<b>🗑 Sub channel deleted</b>\n\n<b>Channel:</b> {_e(ch.get('title', ''))}\n"
                                            f"<b>Channel ID:</b> <code>{cid}</code>", parse_mode=HTML)
        except Exception as e:
            logger.error(f"Could not log channel deletion: {e}")
    await view_channels(client, cq.message, f"✅ Deleted <b>{_e(ch.get('title', str(cid)))}</b>.")


# ── add format chooser: new / copy / paste ──────────────────────────────────────

async def view_add_format(client, msg, cid):
    ch = await db.get_subchannel(cid)
    if not ch:
        return await view_channels(client, msg)
    rows = [[btn("🆕 New — step by step", f"fn:{cid}")],
            [btn("📋 Copy from another format", f"fc:{cid}")],
            [btn("📥 Paste a backup message", f"fi:{cid}")],
            [btn("⬅️ Back", f"cp:{cid}")]]
    await show(msg, f"<b>➕ Add format — {_e(ch.get('title', str(cid)))}</b>\n\n"
                    "• <b>New</b>: 5 quick steps.\n"
                    "• <b>Copy</b>: start from a format of any channel, then edit what differs.\n"
                    "• <b>Paste</b>: forward a backup post from your Save channel.", rows)


@cb(r"^fa:(-?\d+)$")
async def cb_add_format(client, cq):
    if not await _admin_ok(cq):
        return
    admin_state.pop(cq.from_user.id, None)
    await cq.answer()
    await view_add_format(client, cq.message, int(cq.matches[0].group(1)))


@cb(r"^fn:(-?\d+)$")
async def cb_new_format(client, cq):
    if not await _admin_ok(cq):
        return
    cid = int(cq.matches[0].group(1))
    await cq.answer()
    start_prompt(cq.from_user.id, cq.message, 'wiz_thumb', f"fa:{cid}", cid=cid)
    await wiz_prompt(cq.message, {'step': 'thumb', 'data': {'cid': cid}})


@cb(r"^wzb$")
async def cb_wiz_back(client, cq):
    if not await _admin_ok(cq):
        return
    state = admin_state.get(cq.from_user.id)
    if not state or not state['step'].startswith('wiz_'):
        return await cq.answer("That step has expired.", show_alert=True)
    step = state['step'][4:]
    prev = WIZ_STEPS[max(0, WIZ_STEPS.index(step) - 1)]
    state['step'] = 'wiz_' + prev
    await cq.answer()
    await wiz_prompt(cq.message, {'step': prev, 'data': state['data']})


@cb(r"^wzs$")
async def cb_wiz_skip_label(client, cq):
    if not await _admin_ok(cq):
        return
    state = admin_state.get(cq.from_user.id)
    if not state or state['step'] != 'wiz_label':
        return await cq.answer("That step has expired.", show_alert=True)
    words = [w for w in state['data']['rename'].split() if '{' not in w and re.search(r'[A-Za-z]{2}', w)]
    base = ' '.join(words[:3]) or 'Format'
    taken = _all_labels(await db.get_all_subchannels())
    label, n = base, 2
    while label.lower() in taken:
        label, n = f"{base} {n}", n + 1
    await cq.answer()
    await wiz_finish(client, cq.from_user.id, state, label)


# copy from another format
@cb(r"^fc:(-?\d+)$")
async def cb_copy_pick_channel(client, cq):
    if not await _admin_ok(cq):
        return
    cid = int(cq.matches[0].group(1))
    channels = [c for c in await db.get_all_subchannels() if c.get('formats')]
    if not channels:
        return await cq.answer("No formats exist yet to copy from.", show_alert=True)
    await cq.answer()
    rows = [[btn(f"{c.get('title', c['_id'])} ({len(c['formats'])})"[:60], f"fcs:{cid}:{c['_id']}")] for c in channels]
    rows.append([btn("⬅️ Back", f"fa:{cid}")])
    await show(cq.message, "<b>📋 Copy a format</b>\n\nCopy from which channel?", rows)


@cb(r"^fcs:(-?\d+):(-?\d+)$")
async def cb_copy_pick_format(client, cq):
    if not await _admin_ok(cq):
        return
    cid, src = int(cq.matches[0].group(1)), int(cq.matches[0].group(2))
    ch = await db.get_subchannel(src)
    if not ch or not ch.get('formats'):
        return await cq.answer("Nothing to copy there.", show_alert=True)
    await cq.answer()
    rows = [[btn(f"🎞 {f['label']}"[:60], f"fcf:{cid}:{src}:{f['format_id']}")] for f in ch['formats']]
    rows.append([btn("⬅️ Back", f"fc:{cid}")])
    await show(cq.message, f"<b>📋 Copy a format</b> from {_e(ch.get('title', str(src)))}\n\nWhich format?", rows)


def _unique_label(base, taken):
    label, n = base, 2
    while label.lower() in taken:
        label, n = f"{base} {n}", n + 1
    return label


@cb(r"^fcf:(-?\d+):(-?\d+):([a-f0-9]+)$")
async def cb_copy_format(client, cq):
    if not await _admin_ok(cq):
        return
    cid, src, fid = int(cq.matches[0].group(1)), int(cq.matches[0].group(2)), cq.matches[0].group(3)
    source = await db.get_format(src, fid)
    if not source or not await db.get_subchannel(cid):
        return await cq.answer("Not found.", show_alert=True)
    new_id = uuid.uuid4().hex[:8]
    taken = _all_labels(await db.get_all_subchannels())
    fmt = {k: source[k] for k in ('thumbnail', 'rename_format', 'main_post', 'sub_post')}
    fmt.update({'format_id': new_id, 'label': _unique_label(f"{source['label']} (copy)", taken),
                'main_html': bool(source.get('main_html')), 'sub_html': bool(source.get('sub_html'))})
    await db.add_format(cid, fmt)
    await _refresh_backup(client, cid, new_id)
    await cq.answer("Copied ✅")
    await view_format(client, cq.message, cid, new_id, note="✅ Copied. Edit whatever differs for this channel.")


# paste a backup message
@cb(r"^fi:(-?\d+)$")
async def cb_paste(client, cq):
    if not await _admin_ok(cq):
        return
    cid = int(cq.matches[0].group(1))
    await cq.answer()
    start_prompt(cq.from_user.id, cq.message, 'paste_backup', f"fa:{cid}", cid=cid)
    await show(cq.message, "<b>📥 Paste a backup message</b>\n\nForward (or paste) one format backup post from your Save channel.",
               [[btn("✖ Cancel", "pc")]])


async def view_import_choice(client, msg, cid, parsed):
    exists = await db.get_format(parsed['channel_id'], parsed['format_id'])
    same_channel = parsed['channel_id'] == cid
    summary = (f"<b>{_e(parsed['label'])}</b> — from {_e(parsed['channel_title'])}\n"
               f"Rename format: <code>{_e(parsed['rename_format'][:80])}</code>")
    rows = []
    if same_channel and exists:
        text = f"<b>📥 Backup found</b>\n\n{summary}\n\nThis format already belongs to this channel."
        rows.append([btn("✏️ Open & edit it", f"fp:{cid}:{parsed['format_id']}")])
        rows.append([btn("📋 Copy as new", f"fio:{cid}:copy")])
    elif same_channel:
        text = f"<b>📥 Backup found</b>\n\n{summary}\n\nThis format was deleted from this channel."
        rows.append([btn("♻️ Restore it", f"fio:{cid}:restore")])
        rows.append([btn("📋 Copy as new", f"fio:{cid}:copy")])
    else:
        text = f"<b>📥 Backup found</b>\n\n{summary}\n\nIt belongs to another channel."
        rows.append([btn("📋 Copy to this channel", f"fio:{cid}:copy")])
    rows.append([btn("✖ Cancel", f"fa:{cid}")])
    await show(msg, text, rows)


@cb(r"^fio:(-?\d+):(copy|restore)$")
async def cb_import(client, cq):
    if not await _admin_ok(cq):
        return
    cid, mode = int(cq.matches[0].group(1)), cq.matches[0].group(2)
    state = admin_state.get(cq.from_user.id)
    parsed = state and state['data'].get('parsed')
    if not parsed:
        return await cq.answer("That backup has expired — paste it again.", show_alert=True)
    taken = _all_labels(await db.get_all_subchannels())
    if mode == 'restore':
        doc = backup.format_doc_from_backup(parsed)
    else:
        doc = backup.format_doc_from_backup(parsed, new_id=uuid.uuid4().hex[:8],
                                            label=_unique_label(f"{parsed['label']} (copy)", taken))
    admin_state.pop(cq.from_user.id, None)
    await db.add_format(cid, doc)
    await _refresh_backup(client, cid, doc['format_id'])
    await cq.answer("Done ✅")
    await view_format(client, cq.message, cid, doc['format_id'],
                      note="✅ Restored." if mode == 'restore' else "✅ Copied. Edit whatever differs for this channel.")


# ── format panel ────────────────────────────────────────────────────────────────

@cb(r"^fp:(-?\d+):([a-f0-9]+)$")
async def cb_format(client, cq):
    if not await _admin_ok(cq):
        return
    admin_state.pop(cq.from_user.id, None)
    await cq.answer()
    await view_format(client, cq.message, int(cq.matches[0].group(1)), cq.matches[0].group(2))


async def prompt_edit(msg, cid, fid, key, error=None):
    _field, label, hint = FIELD_INFO[key]
    fmt = await db.get_format(cid, fid)
    current = ''
    if fmt and key != 'th':
        current = f"<b>Current:</b>\n{pre(fmt[FIELD_INFO[key][0]], 300)}"
    text = (f"<b>✏️ Edit {label}</b>\n\n" + (f"⚠️ {error}\n\n" if error else "") + f"{hint}\n\n{current}")
    await show(msg, text, [[btn("✖ Cancel", f"fp:{cid}:{fid}")]])


@cb(r"^fe:(lb|rn|mp|sp|th):(-?\d+):([a-f0-9]+)$")
async def cb_edit_field(client, cq):
    if not await _admin_ok(cq):
        return
    key, cid, fid = cq.matches[0].group(1), int(cq.matches[0].group(2)), cq.matches[0].group(3)
    await cq.answer()
    start_prompt(cq.from_user.id, cq.message, 'edit_field', f"fp:{cid}:{fid}", cid=cid, fid=fid, key=key)
    await prompt_edit(cq.message, cid, fid, key)


@cb(r"^fv:(-?\d+):([a-f0-9]+)$")
async def cb_preview(client, cq):
    if not await _admin_ok(cq):
        return
    cid, fid = int(cq.matches[0].group(1)), cq.matches[0].group(2)
    ch = await db.get_subchannel(cid)
    fmt = await db.get_format(cid, fid) if ch else None
    if not fmt:
        return await cq.answer("Not found.", show_alert=True)
    await cq.answer("Sending preview…")
    uid = cq.from_user.id
    try:
        sub = render_post(fmt, 'sub', '1', '5')
        main = render_post(fmt, 'main', '1', '5')
        await client.send_message(uid, "<b>👁 Preview — sample S1E5</b>\nFirst the Sub channel post, then the Main channel post.",
                                  parse_mode=HTML)
        await client.send_photo(uid, fmt['thumbnail'], caption=sub, parse_mode=HTML)
        markup = None
        if ch.get('invite_link'):
            markup = kb([[InlineKeyboardButton("DOWNLOAD", url=ch['invite_link'])]])
        await client.send_photo(uid, fmt['thumbnail'], caption=main, parse_mode=HTML, reply_markup=markup)
    except Exception as e:
        await client.send_message(uid, f"<b>⚠️ Preview failed:</b> <code>{_e(str(e))}</code>\n"
                                       "Check the post text for broken formatting.", parse_mode=HTML)


@cb(r"^fd:(-?\d+):([a-f0-9]+)$")
async def cb_delete_format(client, cq):
    if not await _admin_ok(cq):
        return
    cid, fid = int(cq.matches[0].group(1)), cq.matches[0].group(2)
    fmt = await db.get_format(cid, fid)
    if not fmt:
        return await cq.answer("Not found.", show_alert=True)
    await cq.answer()
    await show(cq.message, f"<b>🗑 Delete “{_e(fmt['label'])}”?</b>\n\nIts backup post in the Save channel is deleted too.",
               [[btn("✅ Yes, delete", f"fdy:{cid}:{fid}"), btn("✖ Cancel", f"fp:{cid}:{fid}")]])


@cb(r"^fdy:(-?\d+):([a-f0-9]+)$")
async def cb_delete_format_yes(client, cq):
    if not await _admin_ok(cq):
        return
    cid, fid = int(cq.matches[0].group(1)), cq.matches[0].group(2)
    fmt = await db.get_format(cid, fid)
    if not fmt:
        return await cq.answer("Already deleted.")
    await backup.delete_backup(client, fmt)
    await db.delete_format(cid, fid)
    _clear_thumb_cache(fid)
    for uid in [u for u, s in auto_post_sessions.items() if s['channel_id'] == cid and s['format']['format_id'] == fid]:
        auto_post_sessions.pop(uid, None)
        await db.ap_session_del(uid)
    await cq.answer("Deleted ✅")
    await view_formats(client, cq.message, cid)


# ── old commands now open the panel ─────────────────────────────────────────────

@Client.on_message(filters.private & filters.command(['list_channels', 'add_format', 'delete_format', 'delete_channel']) & admin_filter)
async def old_commands(client, message):
    admin_state.pop(message.from_user.id, None)
    msg = await message.reply_text("⏳")
    await view_channels(client, msg, "Tap a channel, then use its buttons (Formats, Add format, Delete channel …).")


# ═══ Auto-post start / stop from the dashboard ══════════════════════════════════

@cb(r"^ps_start$")
async def cb_start_picker(client, cq):
    if not await _admin_ok(cq):
        return
    import plugins.auto_post as ap
    text, markup = await ap._channel_picker_view()
    await cq.answer()
    rows = list(markup.inline_keyboard) if markup else []
    rows = [r for r in rows if not (len(r) == 1 and r[0].callback_data == 'apcancel')]
    rows.append([btn("⬅️ Back", "pd")])
    await show(cq.message, text.replace('**', ''), rows)


@cb(r"^ps_stop$")
async def cb_stop(client, cq):
    if not await _admin_ok(cq):
        return
    import plugins.auto_post as ap
    await ap.stop_session(client, cq.from_user.id)
    await cq.answer("Auto-post stopped")
    await view_dashboard(client, cq.message, cq.from_user.id)


# ═══ Status ═════════════════════════════════════════════════════════════════════

async def view_status(client, msg, uid):
    import plugins.auto_post as ap
    import plugins.file_rename as fr
    session = auto_post_sessions.get(uid)
    queued = len(fr.user_queues.get(uid, []))
    processing = fr.user_processing.get(uid, False)
    collecting = len([k for k in ap.pending_groups if k[0] == uid])
    waiting = len(ap.user_jobs.get(uid, []))
    running = uid in ap._running_group
    window = await db.get_autopost_window(ap.DEFAULT_WINDOW_SECONDS)
    lines = ["<b>📊 Status</b>", ""]
    lines.append(f"<b>Auto-post:</b> {('🟢 ' + _e(session['channel_title']) + ' — ' + _e(session['format']['label'])) if session else '⚪ off'}")
    lines.append(f"  collecting: {collecting} • waiting: {waiting} • posting now: {'yes' if running else 'no'}")
    lines.append(f"<b>Rename queue:</b> {queued} waiting • {'⚙️ working' if processing else 'idle'}")
    lines.append(f"<b>Grouping window:</b> {window}s")
    await show(msg, "\n".join(lines),
               [[btn("🔄 Refresh", "pstat"), btn("❌ Cancel everything", "pqc")], [btn("⬅️ Back", "pd")]])


@cb(r"^pstat$")
async def cb_status(client, cq):
    if not await _admin_ok(cq):
        return
    await cq.answer()
    await view_status(client, cq.message, cq.from_user.id)


@cb(r"^pqc$")
async def cb_cancel_all(client, cq):
    if not await _admin_ok(cq):
        return
    import plugins.file_rename as fr
    summary = await fr.cancel_everything(cq.from_user.id)
    await cq.answer("Cancelled" if any(summary.values()) else "Nothing to cancel")
    await view_status(client, cq.message, cq.from_user.id)


# ═══ Settings ═══════════════════════════════════════════════════════════════════

async def _chat_label(client, chat_id):
    if not chat_id:
        return "⚠️ not set"
    try:
        return _e((await client.get_chat(chat_id)).title or str(chat_id))
    except Exception:
        return f"<code>{chat_id}</code>"


async def view_settings(client, msg, note=None):
    import plugins.auto_post as ap
    window = await db.get_autopost_window(ap.DEFAULT_WINDOW_SECONDS)
    main, save = await db.get_main_channel(), await db.get_save_channel()
    stickers = '✅' if (await db.get_main_sticker() and await db.get_sub_sticker()) else '⚠️ not set'
    text = ("<b>⚙️ Settings</b>\n\n"
            f"<b>Main channel:</b> {await _chat_label(client, main)}\n"
            f"<b>Save channel (backups):</b> {await _chat_label(client, save)}\n"
            f"<b>Stickers:</b> {stickers}\n"
            f"<b>Grouping window:</b> {window}s  <i>(how long to wait for more qualities of an episode)</i>"
            + (f"\n\n{note}" if note else ""))
    win_row = [btn(("✅ " if window == s else "") + f"{s}s", f"pw:{s}") for s in (10, 15, 30, 60)]
    rows = [[btn("📢 Main channel", "psm"), btn("💾 Save channel", "pss")],
            [btn("🎭 Stickers", "pst")],
            win_row,
            [btn("📤 Back up all formats", "pbk"), btn("♻️ Restore from backup", "prs")],
            [btn("⬅️ Back", "pd")]]
    await show(msg, text, rows)


@cb(r"^pset$")
async def cb_settings(client, cq):
    if not await _admin_ok(cq):
        return
    admin_state.pop(cq.from_user.id, None)
    await cq.answer()
    await view_settings(client, cq.message)


@cb(r"^pw:(\d+)$")
async def cb_window(client, cq):
    if not await _admin_ok(cq):
        return
    await db.set_autopost_window(int(cq.matches[0].group(1)))
    await cq.answer("Saved")
    await view_settings(client, cq.message)


@cb(r"^(psm|pss)$")
async def cb_set_channel(client, cq):
    if not await _admin_ok(cq):
        return
    action = 'set_main_channel' if cq.matches[0].group(1) == 'psm' else 'set_save_channel'
    which = 'Main' if action == 'set_main_channel' else 'Save'
    await cq.answer()
    admin_state[cq.from_user.id] = {'action': action, 'step': 'awaiting_channel', 'data': {}, 'msg': cq.message}
    await show(cq.message, f"<b>📢 {which} channel</b>\n\nForward a message from the {which} channel, or send its ID / @username.\n"
                           "The bot must already be an admin there.", [[btn("✖ Cancel", "pset-cancel")]])


@cb(r"^pset-cancel$")
async def cb_set_cancel(client, cq):
    admin_state.pop(cq.from_user.id, None)
    await cq.answer("Cancelled")
    await view_settings(client, cq.message)


@cb(r"^pst$")
async def cb_stickers(client, cq):
    if not await _admin_ok(cq):
        return
    await cq.answer()
    admin_state[cq.from_user.id] = {'action': 'set_stickers', 'step': 'awaiting_main_sticker', 'data': {}, 'msg': cq.message}
    await show(cq.message, "<b>🎭 Stickers</b>\n\nSend the sticker to use after every <b>Main channel</b> post (sticker 1).",
               [[btn("✖ Cancel", "pset-cancel")]])


@cb(r"^pbk$")
async def cb_backup_all(client, cq):
    if not await _admin_ok(cq):
        return
    if not await db.get_save_channel():
        return await cq.answer("Set a Save channel first.", show_alert=True)
    await cq.answer("Backing up…")
    done = 0
    for ch in await db.get_all_subchannels():
        for fmt in ch.get('formats', []):
            if not fmt.get('backup_msg_id') and await backup.sync_format(client, ch, fmt):
                done += 1
    await view_settings(client, cq.message, note=f"✅ Backed up {done} format(s) that had no backup post.")


async def run_restore(client, uid):
    r = await backup.restore_all(client, uid)
    if r.get('error'):
        return f"⚠️ {_e(r['error'])}"
    return (f"✅ Found {r['found']} backup post(s): restored {r['restored']}, "
            f"{r['present']} already present.")


@cb(r"^prs$")
async def cb_restore(client, cq):
    if not await _admin_ok(cq):
        return
    await cq.answer("Scanning the Save channel…")
    note = await run_restore(client, cq.from_user.id)
    await view_settings(client, cq.message, note=note)


@Client.on_message(filters.private & filters.command('restore_formats') & admin_filter)
async def restore_cmd(client, message):
    msg = await message.reply_text("⏳ Scanning the Save channel…")
    await show(msg, await run_restore(client, message.from_user.id))


# ═══ Patterns ═══════════════════════════════════════════════════════════════════

async def view_patterns(client, msg, note=None):
    docs = await db.patterns_all()
    text = ("<b>🧩 Detection patterns</b>\n\n"
            "Write the filename shape with <code>{season}</code> <code>{episode}</code> <code>{quality}</code> "
            "(and <code>*</code> for “anything”). Yours are tried first, then the built-in rules 🔒."
            + ("\n\n<i>No custom patterns yet.</i>" if not docs else "")
            + (f"\n\n{note}" if note else ""))
    rows = [[btn(f"{i}. {'🟢' if d.get('enabled', True) else '⚪'} {d['template']}"[:60], f"pt:{d['_id']}")]
            for i, d in enumerate(docs, start=1)]
    rows.append([btn("➕ Add pattern", "pta"), btn("🧪 Test a filename", "ptt")])
    rows.append([btn("🔒 Built-in rules", "ptb")])
    rows.append([btn("⬅️ Back", "pd")])
    await show(msg, text, rows)


@cb(r"^ptl$")
async def cb_patterns(client, cq):
    if not await _admin_ok(cq):
        return
    admin_state.pop(cq.from_user.id, None)
    await cq.answer()
    await view_patterns(client, cq.message)


@cb(r"^ptb$")
async def cb_builtin(client, cq):
    if not await _admin_ok(cq):
        return
    from plugins.file_rename import BUILTIN_EXAMPLES
    await cq.answer()
    lines = ["<b>🔒 Built-in rules</b> (locked — they can't be edited or deleted)\n",
             "<b>Season / episode</b> (tried in this order):"]
    lines += [f"{i}. <code>{_e(x)}</code>" for i, x in enumerate(BUILTIN_EXAMPLES, start=1)]
    lines.append("\n<b>Quality:</b> <code>4k/2160p, 2k/1440p, 1080p, 720p, 576p, 480p, HDRip/HDTV, [720p]</code>")
    await show(cq.message, "\n".join(lines), [[btn("⬅️ Back", "ptl")]])


async def view_pattern(client, msg, pid, note=None):
    docs = await db.patterns_all()
    doc = next((d for d in docs if d['_id'] == pid), None)
    if not doc:
        return await view_patterns(client, msg, "That pattern no longer exists.")
    fields = ', '.join(custom_patterns.fields_in(doc['template']))
    pos = [d['_id'] for d in docs].index(pid) + 1
    text = (f"<b>🧩 Pattern {pos} of {len(docs)}</b>\n\n<code>{_e(doc['template'])}</code>\n\n"
            f"<b>Finds:</b> {fields}\n<b>Status:</b> {'🟢 on' if doc.get('enabled', True) else '⚪ off'}"
            + (f"\n\n{note}" if note else ""))
    rows = [[btn("✏️ Edit", f"pte:{pid}"),
             btn("⏸ Turn off" if doc.get('enabled', True) else "▶️ Turn on", f"pts:{pid}")],
            [btn("⬆️ Move up", f"ptu:{pid}"), btn("⬇️ Move down", f"ptv:{pid}")],
            [btn("🗑 Delete", f"ptd:{pid}")],
            [btn("⬅️ Back", "ptl")]]
    await show(msg, text, rows)


@cb(r"^pt:([a-f0-9]+)$")
async def cb_pattern(client, cq):
    if not await _admin_ok(cq):
        return
    await cq.answer()
    await view_pattern(client, cq.message, cq.matches[0].group(1))


@cb(r"^pts:([a-f0-9]+)$")
async def cb_pattern_toggle(client, cq):
    if not await _admin_ok(cq):
        return
    pid = cq.matches[0].group(1)
    doc = next((d for d in await db.patterns_all() if d['_id'] == pid), None)
    if not doc:
        return await cq.answer("Not found.", show_alert=True)
    await db.pattern_update(pid, {'enabled': not doc.get('enabled', True)})
    await custom_patterns.reload_patterns(db)
    await cq.answer("Saved")
    await view_pattern(client, cq.message, pid)


async def _move(pid, delta):
    docs = await db.patterns_all()
    ids = [d['_id'] for d in docs]
    if pid not in ids:
        return
    i, j = ids.index(pid), ids.index(pid) + delta
    if not 0 <= j < len(docs):
        return
    a, b = docs[i], docs[j]
    await db.pattern_update(a['_id'], {'order': b['order']})
    await db.pattern_update(b['_id'], {'order': a['order']})
    await custom_patterns.reload_patterns(db)


@cb(r"^pt([uv]):([a-f0-9]+)$")
async def cb_pattern_move(client, cq):
    if not await _admin_ok(cq):
        return
    pid = cq.matches[0].group(2)
    await _move(pid, -1 if cq.matches[0].group(1) == 'u' else 1)
    await cq.answer("Moved")
    await view_pattern(client, cq.message, pid)


@cb(r"^ptd:([a-f0-9]+)$")
async def cb_pattern_delete(client, cq):
    if not await _admin_ok(cq):
        return
    pid = cq.matches[0].group(1)
    doc = next((d for d in await db.patterns_all() if d['_id'] == pid), None)
    if not doc:
        return await cq.answer("Not found.", show_alert=True)
    await cq.answer()
    await show(cq.message, f"<b>🗑 Delete this pattern?</b>\n\n<code>{_e(doc['template'])}</code>",
               [[btn("✅ Yes, delete", f"ptdy:{pid}"), btn("✖ Cancel", f"pt:{pid}")]])


@cb(r"^ptdy:([a-f0-9]+)$")
async def cb_pattern_delete_yes(client, cq):
    if not await _admin_ok(cq):
        return
    await db.pattern_delete(cq.matches[0].group(1))
    await custom_patterns.reload_patterns(db)
    await cq.answer("Deleted ✅")
    await view_patterns(client, cq.message, "✅ Pattern deleted.")


@cb(r"^pta$")
async def cb_pattern_add(client, cq):
    if not await _admin_ok(cq):
        return
    await cq.answer()
    start_prompt(cq.from_user.id, cq.message, 'pattern_template', 'ptl')
    await show(cq.message, "<b>🧩 New pattern</b>\n\nSend the filename shape, e.g.\n"
                           "<code>[SubsPlease] * - {episode} ({quality}) *</code>\n"
                           "<code>* S{season} - {episode} [{quality}]</code>\n\n"
                           "<code>*</code> means “anything”. <code>{episode}</code> is required.",
               [[btn("✖ Cancel", "pc")]])


@cb(r"^pte:([a-f0-9]+)$")
async def cb_pattern_edit(client, cq):
    if not await _admin_ok(cq):
        return
    pid = cq.matches[0].group(1)
    doc = next((d for d in await db.patterns_all() if d['_id'] == pid), None)
    if not doc:
        return await cq.answer("Not found.", show_alert=True)
    await cq.answer()
    start_prompt(cq.from_user.id, cq.message, 'pattern_template', f"pt:{pid}", editing=pid)
    await show(cq.message, f"<b>✏️ Edit pattern</b>\n\nCurrent: <code>{_e(doc['template'])}</code>\n\nSend the new pattern.",
               [[btn("✖ Cancel", "pc")]])


@cb(r"^ptchg$")
async def cb_pattern_change(client, cq):
    if not await _admin_ok(cq):
        return
    state = admin_state.get(cq.from_user.id)
    if not state or 'template' not in state['data']:
        return await cq.answer("That step has expired.", show_alert=True)
    state['step'] = 'pattern_template'
    await cq.answer()
    await show(cq.message, "<b>✏️ Change pattern</b>\n\nSend the new pattern.", [[btn("✖ Cancel", "pc")]])


@cb(r"^ptsave$")
async def cb_pattern_save(client, cq):
    if not await _admin_ok(cq):
        return
    state = admin_state.get(cq.from_user.id)
    if not state or 'template' not in state['data']:
        return await cq.answer("That step has expired.", show_alert=True)
    d = state['data']
    existing = [x['template'] for x in await db.patterns_all() if x['_id'] != d.get('editing')]
    if d['template'] in existing:
        return await cq.answer("You already have that pattern.", show_alert=True)
    if d.get('editing'):
        await db.pattern_update(d['editing'], {'template': d['template']})
        note = "✅ Pattern updated."
    else:
        await db.pattern_add(d['template'])
        note = "✅ Pattern saved. It is now tried before the built-in rules."
    admin_state.pop(cq.from_user.id, None)
    await custom_patterns.reload_patterns(db)
    await cq.answer("Saved ✅")
    await view_patterns(client, cq.message, note)


@cb(r"^ptt$")
async def cb_pattern_test(client, cq):
    if not await _admin_ok(cq):
        return
    await cq.answer()
    start_prompt(cq.from_user.id, cq.message, 'pattern_test', 'ptl')
    await show(cq.message, "<b>🧪 Test a filename</b>\n\nSend any filename and I'll show what would be detected.",
               [[btn("⬅️ Back", "ptl")]])
